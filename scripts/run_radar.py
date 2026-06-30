"""
run_radar.py
============
ตัวรันหลักของระบบ TikTok Trend Radar
GitHub Actions จะเรียกไฟล์นี้ทุก 3 ชั่วโมงตามที่ตั้งไว้ใน .github/workflows/trend_radar.yml

หน้าที่:
1. โหลด config.json (รายชื่อคีย์เวิร์ดที่ต้องการติดตาม)
2. ดึงข้อมูล Google Trends ของแต่ละ batch (live mode, fallback เป็น simulate ถ้าดึงไม่ได้)
3. คำนวณ velocity/acceleration
4. บันทึกผลลง data/history.csv (สะสมประวัติ) และ data/latest.json (สแนปช็อตล่าสุด)
5. ถ้าเจอคำที่ momentum สูงเกิน threshold -> ส่งแจ้งเตือนผ่าน LINE
"""

import sys
import time
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from trend_engine import (
    TrendConfig,
    fetch_live_trend,
    simulate_trend_data,
    compute_velocity_acceleration,
    rank_keywords_by_momentum,
    LABEL_DISPLAY,
    ALERT_PHASES,
)
from line_notifier import send_line_message, format_alert_message
from meme_product_map import match_product
from keyword_discovery import discover_keywords

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_radar")

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"
DATA_DIR = REPO_ROOT / "data"
HISTORY_CSV = DATA_DIR / "history.csv"
LATEST_JSON = DATA_DIR / "latest.json"
# state กันแจ้งเตือนซ้ำ: เก็บเวลาเตือนล่าสุดของแต่ละคีย์เวิร์ด (commit กลับ repo เพื่อจำข้ามรอบ)
ALERT_STATE_JSON = DATA_DIR / "alert_state.json"
# สำเนา latest.json ไว้ใน docs/ ด้วย เพื่อให้ dashboard บน GitHub Pages อ่านได้
DOCS_DIR = REPO_ROOT / "docs"
DOCS_LATEST_JSON = DOCS_DIR / "latest.json"
DOCS_HISTORY_JSON = DOCS_DIR / "history.json"
# คำใหม่น่าจับตาจาก keyword discovery (โชว์บน dashboard + แนบท้าย LINE)
SUGGESTIONS_JSON = DATA_DIR / "suggestions.json"
DOCS_SUGGESTIONS_JSON = DOCS_DIR / "suggestions.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def process_batch(keywords: list, geo: str, timeframe: str, mode: str) -> pd.DataFrame:
    """ดึงข้อมูลของ batch หนึ่งชุด แล้วคืนค่าเป็น report DataFrame"""
    if mode == "live":
        config = TrendConfig(keywords=keywords, geo=geo, timeframe=timeframe)
        df = fetch_live_trend(config)
        if df is None:
            logger.warning(f"Batch {keywords}: live ไม่สำเร็จ -> fallback ไปใช้ simulate")
            df = simulate_trend_data(keywords, pattern="noise")
            source = "simulate_fallback"
        else:
            source = "live"
    else:
        # หมุนแพทเทิร์นให้ครบทุกเฟส (GROWTH/PEAK/INTRO/DECLINE/STABLE)
        # เพื่อให้โหมด simulate ทดสอบ classifier + dashboard ได้จริง ไม่ใช่เห็นแต่ GROWTH
        cycle = ["viral_spike", "plateauing", "emerging", "dying", "noise"]
        pattern_map = {kw: cycle[i % len(cycle)] for i, kw in enumerate(keywords)}
        df = simulate_trend_data(keywords, pattern=pattern_map)
        source = "simulate"

    results = compute_velocity_acceleration(df)
    report = rank_keywords_by_momentum(results)
    report["source"] = source
    return report


def append_to_history(report: pd.DataFrame, run_timestamp: str):
    """เพิ่มผลลัพธ์ของรอบนี้เข้าไปใน history.csv (สะสมไปเรื่อยๆ ไม่เขียนทับ)"""
    DATA_DIR.mkdir(exist_ok=True)
    report_to_save = report.reset_index()
    report_to_save.insert(0, "run_timestamp", run_timestamp)

    if HISTORY_CSV.exists():
        report_to_save.to_csv(HISTORY_CSV, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        report_to_save.to_csv(HISTORY_CSV, mode="w", header=True, index=False, encoding="utf-8-sig")

    logger.info(f"บันทึก {len(report_to_save)} แถวลง {HISTORY_CSV.name}")


def save_latest_snapshot(all_reports: pd.DataFrame, run_timestamp: str):
    """บันทึกสแนปช็อตล่าสุดเป็น JSON (เขียนทับทุกครั้ง ใช้ดูสถานะปัจจุบัน)"""
    DATA_DIR.mkdir(exist_ok=True)
    records = all_reports.reset_index().to_dict(orient="records")
    # แนบหมวดสินค้าที่ควรขายให้ทุกคีย์เวิร์ด (ใช้แสดงบน dashboard)
    for rec in records:
        rec["product_suggestion"] = match_product(rec["keyword"])
    snapshot = {
        "run_timestamp": run_timestamp,
        "results": records,
    }
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    # เขียนสำเนาไว้ใน docs/ ให้ dashboard บน GitHub Pages อ่าน
    DOCS_DIR.mkdir(exist_ok=True)
    with open(DOCS_LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(f"บันทึกสแนปช็อตล่าสุดลง {LATEST_JSON.name} และ docs/")


def prune_history(max_runs: int):
    """
    จำกัดขนาด history.csv ให้เก็บแค่ max_runs รอบล่าสุด (กันไฟล์โตไม่จำกัดไปเรื่อยๆ)
    เขียนทับทั้งไฟล์ครั้งเดียวต่อรอบ — ไม่กระทบ logic อื่นเพราะคอลัมน์เหมือนเดิม
    """
    if max_runs <= 0 or not HISTORY_CSV.exists():
        return
    try:
        df = pd.read_csv(HISTORY_CSV)
    except Exception as e:
        logger.warning(f"prune history: อ่าน history.csv ไม่ได้ ({e}) -> ข้าม")
        return
    if "run_timestamp" not in df.columns:
        return

    unique_runs = sorted(df["run_timestamp"].unique())
    if len(unique_runs) <= max_runs:
        return

    keep = set(unique_runs[-max_runs:])
    before = len(df)
    df = df[df["run_timestamp"].isin(keep)]
    df.to_csv(HISTORY_CSV, mode="w", header=True, index=False, encoding="utf-8-sig")
    logger.info(f"prune history.csv: {before} -> {len(df)} แถว (เก็บ {max_runs} รอบล่าสุด)")


def build_history_json(max_runs: int = 50):
    """
    อ่าน history.csv แปลงเป็น JSON สำหรับวาดกราฟย้อนหลังใน dashboard
    เก็บแค่ max_runs รอบล่าสุด (กันไฟล์ใหญ่เกิน)

    โครงสร้างผลลัพธ์:
    {
      "timestamps": ["2026-...", ...],          # แกน X (เรียงเก่า -> ใหม่)
      "series": {
        "คอลลาเจน": {"momentum": [...], "score": [...]},
        ...
      }
    }
    """
    if not HISTORY_CSV.exists():
        logger.info("ยังไม่มี history.csv -> ข้ามการสร้าง history.json")
        return

    try:
        df = pd.read_csv(HISTORY_CSV)
    except Exception as e:
        logger.warning(f"อ่าน history.csv ไม่ได้: {e}")
        return

    if df.empty or "run_timestamp" not in df.columns:
        return

    # เอาเฉพาะ max_runs รอบล่าสุด (เรียงตามเวลา)
    unique_runs = sorted(df["run_timestamp"].unique())
    recent_runs = unique_runs[-max_runs:]
    df = df[df["run_timestamp"].isin(recent_runs)]

    series = {}
    for kw in df["keyword"].unique():
        kw_df = df[df["keyword"] == kw].sort_values("run_timestamp")
        # จับคู่ค่ากับ timestamp (เผื่อบางรอบไม่มีคำนี้)
        run_map = dict(zip(kw_df["run_timestamp"], zip(kw_df["momentum_score"], kw_df["current_score"])))
        momentum, score = [], []
        for ts in recent_runs:
            if ts in run_map:
                momentum.append(round(float(run_map[ts][0]), 2))
                score.append(round(float(run_map[ts][1]), 1))
            else:
                momentum.append(None)  # ช่องว่างถ้ารอบนั้นไม่มีคำนี้
                score.append(None)
        series[str(kw)] = {"momentum": momentum, "score": score}

    history = {"timestamps": [str(t) for t in recent_runs], "series": series}

    DOCS_DIR.mkdir(exist_ok=True)
    with open(DOCS_HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logger.info(f"บันทึกประวัติ {len(recent_runs)} รอบลง docs/history.json")


def find_alerts(all_reports: pd.DataFrame, threshold: float) -> list:
    """
    หาคำที่ควรแจ้งเตือน = อยู่ในเฟส GROWTH หรือ PEAK (จังหวะที่ลงมือแล้วคุ้ม)
    และ momentum ผ่าน threshold ขั้นต่ำ
    พร้อมแนบหมวดสินค้าที่ควรขาย (Meme-Product Matching)
    """
    alerts = []
    for kw, row in all_reports.iterrows():
        # เงื่อนไข 1: ต้องอยู่ในเฟสที่ควรลงมือ (พุ่ง/พีค)
        if row["label"] not in ALERT_PHASES:
            continue
        # เงื่อนไข 2: momentum ต้องผ่านเกณฑ์ขั้นต่ำ (กันสัญญาณอ่อนเกินไป)
        if row["momentum_score"] < threshold:
            continue

        alerts.append({
            "keyword": kw,
            "momentum_score": row["momentum_score"],
            "current_score": row["current_score"],
            "label": row["label"],
            "label_display": LABEL_DISPLAY.get(row["label"], row["label"]),
            "product_suggestion": match_product(kw),  # แนบหมวดสินค้าตามอารมณ์
        })
    return alerts


# ──────────────────────────────────────────────────────────
# ALERT DE-DUP (กันสแปม: ไม่เตือนคำเดิมซ้ำทุก 3 ชม.)
# ──────────────────────────────────────────────────────────
def load_alert_state() -> dict:
    """อ่าน state เวลาเตือนล่าสุดของแต่ละคีย์เวิร์ด (คืน {} ถ้าไม่มี/อ่านไม่ได้)"""
    if not ALERT_STATE_JSON.exists():
        return {}
    try:
        with open(ALERT_STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"อ่าน alert_state.json ไม่ได้ ({e}) -> เริ่มใหม่")
        return {}


def save_alert_state(state: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(ALERT_STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def filter_recent_alerts(alerts: list, state: dict, cooldown_hours: float, now: datetime) -> list:
    """
    คัดคำที่เพิ่งเตือนไปภายใน cooldown_hours ออก เพื่อไม่ให้สแปมคำเดิมทุกรอบ
    คำที่ยังไม่เคยเตือน หรือเตือนไปนานเกิน cooldown แล้ว = ส่งได้
    """
    fresh = []
    for a in alerts:
        last = state.get(a["keyword"])
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if now - last_dt < timedelta(hours=cooldown_hours):
                    continue  # ยังอยู่ในช่วง cooldown -> ข้าม
            except ValueError:
                pass  # timestamp เพี้ยน -> ถือว่าเตือนได้
        fresh.append(a)
    return fresh


# ──────────────────────────────────────────────────────────
# KEYWORD DISCOVERY (เสนอคำใหม่น่าจับตา ไม่เพิ่มเข้า config อัตโนมัติ)
# ──────────────────────────────────────────────────────────
def run_discovery(existing_keywords: list, run_timestamp: str):
    """
    ค้นหาคำเทรนด์ใหม่ + คำใกล้เคียง แล้วเขียนลง suggestions.json (data/ + docs/)
    ห่อด้วย try/except เสมอ เพราะดึง Google Trends เพิ่มแล้วพลาดได้ ไม่ควรล้ม pipeline
    คืน dict ผลลัพธ์ (หรือ None ถ้าพลาด) ไว้แนบท้าย LINE
    """
    try:
        result = discover_keywords(existing_keywords)
    except Exception as e:
        logger.warning(f"keyword discovery ล้มเหลว ({e}) -> ข้าม")
        return None

    payload = {
        "generated_at": run_timestamp,
        "trending_today": result.get("trending_today", []),
        "related": result.get("related", {}),
    }
    DATA_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    for path in (SUGGESTIONS_JSON, DOCS_SUGGESTIONS_JSON):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(
        f"keyword discovery: เจอคำเทรนด์ใหม่ {len(payload['trending_today'])} คำ, "
        f"คำใกล้เคียง {sum(len(v) for v in payload['related'].values())} คำ -> suggestions.json"
    )
    return payload


def main():
    parser = argparse.ArgumentParser(description="TikTok Trend Radar - ตัวรันหลัก")
    parser.add_argument(
        "--mode", choices=["live", "simulate"], default="live",
        help="live = ดึงข้อมูลจริงจาก Google Trends, simulate = จำลองข้อมูล (สำหรับทดสอบ)",
    )
    args = parser.parse_args()

    config = load_config()
    geo = config.get("geo", "TH")
    timeframe = config.get("timeframe", "now 1-d")
    threshold = config.get("momentum_alert_threshold", 1.5)
    batches = config.get("keyword_batches", [])
    # หน่วงเวลาระหว่าง batch ในโหมด live เพื่อลดความเสี่ยงโดน Google Trends rate limit (429)
    batch_delay = config.get("batch_delay_seconds", 8)
    # ช่วง cooldown ของการแจ้งเตือนคำเดิม (ชม.) — กันสแปมคำที่ค้างเฟส GROWTH/PEAK หลายรอบ
    cooldown_hours = config.get("alert_cooldown_hours", 12)
    enable_discovery = config.get("enable_keyword_discovery", True)
    # เก็บประวัติใน history.csv ไม่เกินกี่รอบ (กันไฟล์โตไม่จำกัด)
    max_history_runs = config.get("max_history_runs", 200)

    if not batches:
        logger.error("ไม่มีคีย์เวิร์ดใน config.json -> เพิ่มคำในช่อง keyword_batches ก่อนรัน")
        sys.exit(1)

    run_dt = datetime.now(timezone.utc)
    run_timestamp = run_dt.isoformat()
    logger.info(f"เริ่มรอบการทำงาน: {run_timestamp} | โหมด: {args.mode}")

    all_reports = []
    for i, batch in enumerate(batches, start=1):
        logger.info(f"ประมวลผล batch {i}/{len(batches)}: {batch}")
        try:
            report = process_batch(batch, geo, timeframe, args.mode)
            all_reports.append(report)
            append_to_history(report, run_timestamp)
        except Exception as e:
            logger.error(f"Batch {batch} ล้มเหลว: {e}", exc_info=True)
        # หน่วงก่อนยิง batch ถัดไป (เฉพาะ live และไม่ใช่ batch สุดท้าย)
        if args.mode == "live" and i < len(batches) and batch_delay > 0:
            time.sleep(batch_delay)

    if not all_reports:
        logger.error("ทุก batch ล้มเหลว ไม่มีข้อมูลให้บันทึก/แจ้งเตือน")
        sys.exit(1)

    combined = pd.concat(all_reports)
    save_latest_snapshot(combined, run_timestamp)
    prune_history(max_history_runs)
    build_history_json()

    # ── ค้นหาคำใหม่น่าจับตา (เฉพาะ live; ไม่เพิ่มเข้า config อัตโนมัติ ให้คนคัดเอง) ──
    suggestions = None
    if enable_discovery and args.mode == "live":
        existing = [kw for batch in batches for kw in batch]
        suggestions = run_discovery(existing, run_timestamp)

    # ── แจ้งเตือนผ่าน LINE เมื่อเจอคำในเฟส GROWTH/PEAK (จังหวะทอง) ──
    alerts = find_alerts(combined, threshold)
    if not alerts:
        logger.info("ไม่มีคำใดอยู่ในเฟสพุ่ง/พีค ในรอบนี้")
    else:
        # กันสแปม: ตัดคำที่เพิ่งเตือนไปภายใน cooldown ออก
        alert_state = load_alert_state()
        fresh = filter_recent_alerts(alerts, alert_state, cooldown_hours, run_dt)
        skipped = len(alerts) - len(fresh)
        if skipped:
            logger.info(f"ข้าม {skipped} คำที่เพิ่งเตือนไปภายใน {cooldown_hours} ชม. (กันซ้ำ)")
        if fresh:
            logger.info(f"ส่งแจ้งเตือน {len(fresh)} คำในเฟสพุ่ง/พีค (จังหวะทอง)")
            message = format_alert_message(fresh, suggestions=suggestions)
            send_line_message(message)
            # บันทึกเวลาเตือนล่าสุด เฉพาะคำที่เพิ่งส่งจริง
            for a in fresh:
                alert_state[a["keyword"]] = run_timestamp
            save_alert_state(alert_state)
        else:
            logger.info("คำในเฟสพุ่ง/พีค ทั้งหมดยังอยู่ใน cooldown -> ไม่ส่งซ้ำ")

    logger.info("จบรอบการทำงาน")


if __name__ == "__main__":
    main()
