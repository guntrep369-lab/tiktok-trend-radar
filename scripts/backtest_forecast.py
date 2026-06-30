"""
backtest_forecast.py
====================
ทดสอบย้อนหลัง (walk-forward) ว่าโมเดลพยากรณ์อายุที่เหลือ (forecast_lifespan) แม่นแค่ไหน
โดยใช้ข้อมูลที่ระบบสะสมไว้แล้วใน data/history.csv

ไอเดีย:
- history.csv เก็บ current_score ของแต่ละคีย์เวิร์ดทุกครั้งที่รัน (ทุก ~3 ชม.)
  => ต่อกันเป็น time series ข้ามรอบ = วงจรชีวิตจริงของคีย์เวิร์ดนั้น
- สำหรับแต่ละคีย์เวิร์ด เดินไปข้างหน้าทีละจุด: ใช้ข้อมูลถึงเวลา T พยากรณ์ว่า
  "เหลืออีกกี่วัน" แล้วเทียบกับความจริง (เวลาที่ score ตกต่ำกว่า dead_level จริงๆ)
- รายงาน MAE (ค่าคลาดเคลื่อนเฉลี่ยเป็นวัน)

หมายเหตุ: ต้องมีข้อมูลสะสมหลายวันถึงจะ backtest ได้มีความหมาย
ช่วงแรกที่ข้อมูลน้อย สคริปต์จะบอกว่ายังพยากรณ์ไม่ได้ ซึ่งเป็นเรื่องปกติ

วิธีรัน:
    python scripts/backtest_forecast.py
    python scripts/backtest_forecast.py --dead-level 10 --min-points 8
"""

import sys
import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from trend_engine import forecast_lifespan

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backtest")

HISTORY_CSV = Path(__file__).parent.parent / "data" / "history.csv"
SECONDS_PER_DAY = 86400.0


def actual_days_remaining(series: pd.Series, t_now, dead_level: float):
    """
    หาความจริง: นับจากเวลา t_now ไปอีกกี่วัน score ถึงตกต่ำกว่า dead_level ครั้งแรก
    ถ้าไม่เคยตกเลยในข้อมูลที่มี -> คืน None (เซ็นเซอร์ขวา ใช้ประเมินไม่ได้)
    """
    future = series[series.index > t_now]
    dead = future[future < dead_level]
    if dead.empty:
        return None
    return (dead.index[0] - t_now).total_seconds() / SECONDS_PER_DAY


def backtest_keyword(series: pd.Series, dead_level: float, min_points: int):
    """เดิน walk-forward บนคีย์เวิร์ดเดียว คืน list ของ (predicted, actual)"""
    series = series.sort_index()
    pairs = []
    for end in range(min_points, len(series)):
        prefix = series.iloc[:end]
        fc = forecast_lifespan(prefix, dead_level=dead_level)
        if not fc or not fc.get("ok"):
            continue
        actual = actual_days_remaining(series, prefix.index[-1], dead_level)
        if actual is None:
            continue  # อนาคตยังไม่ตาย -> วัดความแม่นไม่ได้
        pairs.append((fc["days_remaining"], actual))
    return pairs


def load_series_by_keyword() -> dict:
    """อ่าน history.csv -> {keyword: pd.Series(current_score, index=run_timestamp)}"""
    if not HISTORY_CSV.exists():
        logger.error(f"ไม่พบ {HISTORY_CSV}")
        sys.exit(1)
    df = pd.read_csv(HISTORY_CSV)
    needed = {"run_timestamp", "keyword", "current_score"}
    if not needed.issubset(df.columns):
        logger.error(f"history.csv ขาดคอลัมน์ที่ต้องใช้: {needed - set(df.columns)}")
        sys.exit(1)
    df["run_timestamp"] = pd.to_datetime(df["run_timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["run_timestamp"])

    out = {}
    for kw, g in df.groupby("keyword"):
        s = g.set_index("run_timestamp")["current_score"].astype(float).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        out[str(kw)] = s
    return out


def main():
    ap = argparse.ArgumentParser(description="Backtest forecast_lifespan กับ history.csv")
    ap.add_argument("--dead-level", type=float, default=10.0)
    ap.add_argument("--min-points", type=int, default=8)
    args = ap.parse_args()

    series_map = load_series_by_keyword()
    logger.info(f"พบ {len(series_map)} คีย์เวิร์ดใน history.csv\n")

    all_pairs = []
    for kw, s in sorted(series_map.items()):
        pairs = backtest_keyword(s, args.dead_level, args.min_points)
        if pairs:
            err = np.mean([abs(p - a) for p, a in pairs])
            logger.info(f"  {kw:<24} n={len(pairs):>3}  MAE={err:5.2f} วัน")
            all_pairs.extend(pairs)
        else:
            logger.info(f"  {kw:<24} (ข้อมูลยังไม่พอ/ยังไม่ตาย — ข้าม)")

    logger.info("")
    if not all_pairs:
        logger.info("ยังไม่มีจุดที่ backtest ได้ — ต้องสะสมข้อมูลให้ครอบคลุมทั้งวงจร (ขึ้น+ตก) มากกว่านี้")
        return

    preds = np.array([p for p, _ in all_pairs])
    acts = np.array([a for _, a in all_pairs])
    mae = float(np.mean(np.abs(preds - acts)))
    bias = float(np.mean(preds - acts))
    logger.info("=" * 48)
    logger.info(f"รวม {len(all_pairs)} จุดพยากรณ์")
    logger.info(f"MAE  = {mae:.2f} วัน   (ยิ่งต่ำยิ่งดี)")
    logger.info(f"Bias = {bias:+.2f} วัน  (บวก=พยากรณ์ยาวเกินจริง, ลบ=สั้นเกินจริง)")


if __name__ == "__main__":
    main()
