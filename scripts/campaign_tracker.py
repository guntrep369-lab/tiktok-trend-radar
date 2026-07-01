"""
campaign_tracker.py
===================
ปิด feedback loop ของระบบ: ผูก 'คลิปที่โพสต์จริง' -> 'คีย์เวิร์ด/อารมณ์ต้นทาง' -> 'ผลงานจริง'
(วิว/คลิก/ออเดอร์/ยอดขาย) เพื่อตอบคำถามที่สำคัญที่สุดของธุรกิจ:
    "คีย์เวิร์ด/อารมณ์ไหน ทำเงินจริง?"

ทำไมต้องมี:
ระบบเดิมจูน threshold ด้วย 'momentum ของ Google Trends' ซึ่งเป็นแค่ตัวแทนของเงิน
ไฟล์นี้ทำให้เราวัด ROI จริงจากปลายทาง (TikTok Shop) แล้วป้อนกลับเข้ามาตัดสินใจ

TikTok Shop ไม่มี public API ดึงยอด affiliate รายคนง่ายๆ -> รองรับ 2 ทาง:
  1. กรอกมือ (log / update)
  2. import CSV ที่ export จาก TikTok Shop affiliate dashboard (import)

วิธีใช้:
    # บันทึกคลิปใหม่ที่โพสต์ (อารมณ์เติมให้อัตโนมัติจากคีย์เวิร์ด)
    python scripts/campaign_tracker.py log --video-id VID123 --keyword "คอลลาเจน"

    # อัปเดตผลงานทีหลัง (ดึงตัวเลขจาก dashboard มากรอก)
    python scripts/campaign_tracker.py update --video-id VID123 --views 12000 --clicks 340 --orders 18 --gmv 5400

    # import ผลงานจาก CSV ที่ export มา (จับคู่ด้วย video_id)
    python scripts/campaign_tracker.py import --file affiliate_export.csv

    # ดูสรุป ROI ต่อคีย์เวิร์ด/อารมณ์ + เขียน performance.json ให้ dashboard
    python scripts/campaign_tracker.py report
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from meme_product_map import match_product

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("campaign_tracker")

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CAMPAIGNS_CSV = DATA_DIR / "campaigns.csv"
PERFORMANCE_JSON = DATA_DIR / "performance.json"
DOCS_PERFORMANCE_JSON = DOCS_DIR / "performance.json"
# น้ำหนัก ROI ต่ออารมณ์ (normalized, ไม่มีตัวเลขยอดขายดิบ) — commit ได้ ใช้ถ่วง ranking ใน CI
ROI_WEIGHTS_JSON = DATA_DIR / "roi_weights.json"

COLUMNS = ["campaign_id", "video_id", "keyword", "mood_key", "mood_display",
           "posted_at", "views", "clicks", "orders", "gmv", "notes"]
METRIC_COLS = ["views", "clicks", "orders", "gmv"]

# ชื่อคอลัมน์ที่อาจเจอใน CSV ที่ export จาก TikTok Shop (map -> ชื่อภายในของเรา)
IMPORT_ALIASES = {
    "video_id": ["video_id", "video id", "videoid", "post id", "content id"],
    "views":    ["views", "video views", "vv", "ยอดวิว"],
    "clicks":   ["clicks", "product clicks", "คลิก"],
    "orders":   ["orders", "items sold", "units sold", "ออเดอร์", "ชิ้นที่ขายได้"],
    "gmv":      ["gmv", "est. commission", "commission", "revenue", "ยอดขาย", "คอมมิชชั่น"],
}


# ──────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────
def load_campaigns() -> pd.DataFrame:
    if not CAMPAIGNS_CSV.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(CAMPAIGNS_CSV)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = 0 if c in METRIC_COLS else ""
    for c in METRIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df[COLUMNS]


def save_campaigns(df: pd.DataFrame):
    DATA_DIR.mkdir(exist_ok=True)
    df[COLUMNS].to_csv(CAMPAIGNS_CSV, index=False, encoding="utf-8-sig")


# ──────────────────────────────────────────────────────────
# AGGREGATION (pure — เทสต์ได้โดยไม่ต้องแตะไฟล์)
# ──────────────────────────────────────────────────────────
def _agg_group(df: pd.DataFrame, key_cols: list) -> list:
    """รวมตัวเลขผลงานตามกลุ่ม (คีย์เวิร์ด หรือ อารมณ์) แล้วเรียงตาม gmv รวม"""
    rows = []
    for keys, g in df.groupby(key_cols):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rec = dict(zip(key_cols, keys))
        n = len(g)
        views = float(g["views"].sum())
        clicks = float(g["clicks"].sum())
        orders = float(g["orders"].sum())
        gmv = float(g["gmv"].sum())
        rec.update({
            "n_videos": int(n),
            "views": int(views),
            "clicks": int(clicks),
            "orders": int(orders),
            "gmv": round(gmv, 2),
            "gmv_per_video": round(gmv / n, 2) if n else 0.0,
            "ctr": round(clicks / views, 4) if views else 0.0,       # คลิก/วิว
            "cvr": round(orders / clicks, 4) if clicks else 0.0,     # ออเดอร์/คลิก
        })
        rows.append(rec)
    return sorted(rows, key=lambda r: r["gmv"], reverse=True)


def aggregate_performance(df: pd.DataFrame) -> dict:
    """สรุปผลงานรวม + ต่อคีย์เวิร์ด + ต่ออารมณ์ (โครงสร้างพร้อมเขียน JSON ให้ dashboard)"""
    if df.empty:
        return {"generated_at": datetime.now(timezone.utc).isoformat(),
                "totals": {"videos": 0, "views": 0, "clicks": 0, "orders": 0, "gmv": 0.0},
                "by_keyword": [], "by_mood": []}
    totals = {
        "videos": int(len(df)),
        "views": int(df["views"].sum()),
        "clicks": int(df["clicks"].sum()),
        "orders": int(df["orders"].sum()),
        "gmv": round(float(df["gmv"].sum()), 2),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "by_keyword": _agg_group(df, ["keyword"]),
        "by_mood": _agg_group(df, ["mood_key", "mood_display"]),
    }


def compute_roi_weights(perf: dict, min_videos: int = 3, lo: float = 0.5, hi: float = 2.0) -> dict:
    """
    แปลงผลงานจริงต่ออารมณ์ -> น้ำหนัก ROI แบบ normalized (mood_key -> multiplier)
    วิธี: weight = gmv_ต่อคลิป / ค่าเฉลี่ยของทุกอารมณ์ แล้ว clamp ไว้ที่ [lo, hi] กันสุดโต่งตอนข้อมูลน้อย
    - เอาเฉพาะอารมณ์ที่มีคลิป >= min_videos และ gmv/คลิป > 0 (กัน noise)
    - ต้องมีอย่างน้อย 2 อารมณ์ถึงจะเทียบกันได้ ไม่งั้นคืน {} (= ไม่ถ่วงน้ำหนัก)
    ผลลัพธ์เป็นค่าสัมพัทธ์ล้วน ไม่มีตัวเลขยอดขายดิบ -> commit ขึ้น repo ได้
    """
    moods = [m for m in perf.get("by_mood", [])
             if m.get("n_videos", 0) >= min_videos and m.get("gmv_per_video", 0) > 0]
    if len(moods) < 2:
        return {}
    mean = sum(m["gmv_per_video"] for m in moods) / len(moods)
    if mean <= 0:
        return {}
    weights = {}
    for m in moods:
        w = m["gmv_per_video"] / mean
        weights[m["mood_key"]] = round(max(lo, min(hi, w)), 2)
    return weights


# ──────────────────────────────────────────────────────────
# COMMANDS
# ──────────────────────────────────────────────────────────
def cmd_log(args):
    df = load_campaigns()
    if (df["video_id"].astype(str) == str(args.video_id)).any():
        logger.error(f"มี video_id '{args.video_id}' อยู่แล้ว -> ใช้ 'update' แทน")
        sys.exit(1)
    prod = match_product(args.keyword)
    row = {
        "campaign_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "video_id": args.video_id,
        "keyword": args.keyword,
        "mood_key": prod["mood_key"],
        "mood_display": prod["mood_display"],
        "posted_at": args.posted_at or datetime.now(timezone.utc).date().isoformat(),
        "views": args.views, "clicks": args.clicks, "orders": args.orders, "gmv": args.gmv,
        "notes": args.notes or "",
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_campaigns(df)
    logger.info(f"บันทึกคลิป: {args.keyword} (อารมณ์: {prod['mood_display']}) -> {CAMPAIGNS_CSV.name}")


def cmd_update(args):
    df = load_campaigns()
    mask = df["video_id"].astype(str) == str(args.video_id)
    if not mask.any():
        logger.error(f"ไม่พบ video_id '{args.video_id}' -> ใช้ 'log' เพื่อสร้างก่อน")
        sys.exit(1)
    for field in METRIC_COLS:
        val = getattr(args, field)
        if val is not None:
            df.loc[mask, field] = val
    if args.notes is not None:
        df.loc[mask, "notes"] = args.notes
    save_campaigns(df)
    logger.info(f"อัปเดตผลงาน video_id '{args.video_id}' เรียบร้อย")


def _resolve_alias(columns, aliases):
    low = {c.lower().strip(): c for c in columns}
    for a in aliases:
        if a in low:
            return low[a]
    return None


def cmd_import(args):
    src = pd.read_csv(args.file)
    vid_col = _resolve_alias(src.columns, IMPORT_ALIASES["video_id"])
    if not vid_col:
        logger.error(f"ไม่พบคอลัมน์ video_id ใน {args.file} (รองรับ: {IMPORT_ALIASES['video_id']})")
        sys.exit(1)
    metric_map = {m: _resolve_alias(src.columns, IMPORT_ALIASES[m]) for m in METRIC_COLS}

    df = load_campaigns()
    updated, skipped = 0, 0
    for _, r in src.iterrows():
        vid = str(r[vid_col])
        mask = df["video_id"].astype(str) == vid
        if not mask.any():
            skipped += 1                  # ไม่เคย log คลิปนี้ -> ข้าม (ต้อง log ก่อนถึงรู้คีย์เวิร์ด)
            continue
        for m, col in metric_map.items():
            if col is not None and pd.notna(r[col]):
                df.loc[mask, m] = pd.to_numeric(r[col], errors="coerce")
        updated += 1
    save_campaigns(df)
    logger.info(f"import จาก {Path(args.file).name}: อัปเดต {updated} คลิป, ข้าม {skipped} (ยังไม่ได้ log)")


def cmd_report(args):
    df = load_campaigns()
    perf = aggregate_performance(df)

    DATA_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    for path in (PERFORMANCE_JSON, DOCS_PERFORMANCE_JSON):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(perf, f, ensure_ascii=False, indent=2)

    t = perf["totals"]
    logger.info(f"\n=== ผลงานรวม ===")
    logger.info(f"คลิป {t['videos']} | วิว {t['views']:,} | คลิก {t['clicks']:,} | ออเดอร์ {t['orders']:,} | GMV {t['gmv']:,.0f}")
    if not perf["by_mood"]:
        logger.info("\n(ยังไม่มีข้อมูลคลิป — ใช้ 'log' เริ่มบันทึกก่อน)")
        return
    logger.info(f"\n=== ตามอารมณ์ (เรียงตาม GMV) ===")
    for m in perf["by_mood"][:args.top]:
        logger.info(f"  {m['mood_display']:<34} GMV {m['gmv']:>9,.0f} | {m['n_videos']} คลิป | {m['gmv_per_video']:,.0f}/คลิป")
    logger.info(f"\n=== Top คีย์เวิร์ด (เรียงตาม GMV) ===")
    for k in perf["by_keyword"][:args.top]:
        logger.info(f"  {k['keyword']:<24} GMV {k['gmv']:>9,.0f} | {k['n_videos']} คลิป | วิว {k['views']:,}")
    logger.info(f"\nเขียน {PERFORMANCE_JSON.name} + docs/ แล้ว (dashboard จะโชว์ส่วน 'ผลงานจริง')")


def cmd_weights(args):
    perf = aggregate_performance(load_campaigns())
    weights = compute_roi_weights(perf, min_videos=args.min_videos)
    if not weights:
        logger.info(f"ข้อมูลยังไม่พอสร้างน้ำหนัก ROI (ต้องมี >= 2 อารมณ์ที่มีคลิป >= {args.min_videos} "
                    f"และมียอดขาย) — สะสมข้อมูลเพิ่มก่อน")
        return
    DATA_DIR.mkdir(exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "weights": weights}
    with open(ROI_WEIGHTS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("=== น้ำหนัก ROI ต่ออารมณ์ (ยิ่งสูง = ทำเงินดีกว่าค่าเฉลี่ย) ===")
    for k, w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
        logger.info(f"  {k:<26} x{w}")
    logger.info(f"\nเขียน {ROI_WEIGHTS_JSON.name} แล้ว — commit ไฟล์นี้เพื่อให้ ranking บน CI ถ่วงน้ำหนักด้วยรายได้จริง")


def main():
    ap = argparse.ArgumentParser(description="ตัวติดตามผลงาน affiliate (ปิด feedback loop)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log", help="บันทึกคลิปใหม่ที่โพสต์")
    p_log.add_argument("--video-id", required=True)
    p_log.add_argument("--keyword", required=True)
    p_log.add_argument("--posted-at", default=None, help="YYYY-MM-DD (ดีฟอลต์=วันนี้)")
    p_log.add_argument("--views", type=int, default=0)
    p_log.add_argument("--clicks", type=int, default=0)
    p_log.add_argument("--orders", type=int, default=0)
    p_log.add_argument("--gmv", type=float, default=0.0)
    p_log.add_argument("--notes", default=None)
    p_log.set_defaults(func=cmd_log)

    p_up = sub.add_parser("update", help="อัปเดตตัวเลขผลงานของคลิปเดิม")
    p_up.add_argument("--video-id", required=True)
    p_up.add_argument("--views", type=int, default=None)
    p_up.add_argument("--clicks", type=int, default=None)
    p_up.add_argument("--orders", type=int, default=None)
    p_up.add_argument("--gmv", type=float, default=None)
    p_up.add_argument("--notes", default=None)
    p_up.set_defaults(func=cmd_update)

    p_im = sub.add_parser("import", help="import ผลงานจาก CSV (จับคู่ด้วย video_id)")
    p_im.add_argument("--file", required=True)
    p_im.set_defaults(func=cmd_import)

    p_rep = sub.add_parser("report", help="สรุป ROI + เขียน performance.json")
    p_rep.add_argument("--top", type=int, default=10)
    p_rep.set_defaults(func=cmd_report)

    p_w = sub.add_parser("weights", help="สร้างน้ำหนัก ROI ต่ออารมณ์ -> roi_weights.json (ถ่วง ranking)")
    p_w.add_argument("--min-videos", type=int, default=3, help="อารมณ์ต้องมีคลิปอย่างน้อยเท่านี้ถึงนับ")
    p_w.set_defaults(func=cmd_weights)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
