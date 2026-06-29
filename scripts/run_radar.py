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
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

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
        df = simulate_trend_data(keywords, pattern="viral_spike")
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
    snapshot = {
        "run_timestamp": run_timestamp,
        "results": all_reports.reset_index().to_dict(orient="records"),
    }
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(f"บันทึกสแนปช็อตล่าสุดลง {LATEST_JSON.name}")


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

    if not batches:
        logger.error("ไม่มีคีย์เวิร์ดใน config.json -> เพิ่มคำในช่อง keyword_batches ก่อนรัน")
        sys.exit(1)

    run_timestamp = datetime.now(timezone.utc).isoformat()
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

    if not all_reports:
        logger.error("ทุก batch ล้มเหลว ไม่มีข้อมูลให้บันทึก/แจ้งเตือน")
        sys.exit(1)

    combined = pd.concat(all_reports)
    save_latest_snapshot(combined, run_timestamp)

    # ── แจ้งเตือนผ่าน LINE เมื่อเจอคำในเฟส GROWTH/PEAK (จังหวะทอง) ──
    alerts = find_alerts(combined, threshold)
    if alerts:
        logger.info(f"พบ {len(alerts)} คำในเฟสพุ่ง/พีค (จังหวะทอง) -> ส่งแจ้งเตือน")
        message = format_alert_message(alerts)
        send_line_message(message)
    else:
        logger.info("ไม่มีคำใดอยู่ในเฟสพุ่ง/พีค ในรอบนี้")

    logger.info("จบรอบการทำงาน")


if __name__ == "__main__":
    main()
