"""
trend_engine.py
================
โมดูลหลักสำหรับดึงข้อมูล Google Trends และคำนวณ Velocity / Acceleration
ใช้ร่วมกับ run_radar.py (ตัวรันหลักของระบบ)

แนวคิดคณิตศาสตร์:
- Velocity (v)     = อัตราการเปลี่ยนแปลงของ search interest ต่อช่วงเวลา (1st derivative)
- Acceleration (a) = อัตราการเปลี่ยนแปลงของ velocity (2nd derivative)
"""

import time
import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("trend_engine")


@dataclass
class TrendConfig:
    keywords: list
    timeframe: str = "now 1-d"
    geo: str = "TH"
    sleep_between_calls: float = 5.0


# ──────────────────────────────────────────────────────────
# LIVE FETCHER
# ──────────────────────────────────────────────────────────
def fetch_live_trend(config: TrendConfig, retries: int = 3) -> Optional[pd.DataFrame]:
    """
    ดึงข้อมูล interest_over_time จาก Google Trends ผ่าน pytrends
    มี retry + exponential backoff รองรับ error 429 (rate limit)
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.error("ยังไม่ได้ติดตั้ง pytrends")
        return None

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            pytrends = TrendReq(hl="th-TH", tz=420)
            pytrends.build_payload(
                kw_list=config.keywords,
                timeframe=config.timeframe,
                geo=config.geo,
            )
            df = pytrends.interest_over_time()

            if df.empty:
                logger.warning(f"ไม่มีข้อมูลสำหรับ: {config.keywords}")
                return None

            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            return df

        except Exception as e:
            last_error = e
            wait = (2 ** attempt) * config.sleep_between_calls
            logger.warning(f"พยายามครั้งที่ {attempt}/{retries} ล้มเหลว ({e}) -> รอ {wait:.0f}s")
            if attempt < retries:
                time.sleep(wait)

    logger.error(f"ดึงข้อมูล live ไม่สำเร็จหลังจาก {retries} ครั้ง: {last_error}")
    return None


# ──────────────────────────────────────────────────────────
# SIMULATION FETCHER (ใช้ตอน test/dev หรือ Google บล็อก)
# ──────────────────────────────────────────────────────────
def simulate_trend_data(
    keywords: list,
    hours: int = 24,
    interval_minutes: int = 15,
    pattern: str = "viral_spike",
    seed: Optional[int] = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_points = int((hours * 60) / interval_minutes)
    timestamps = [
        datetime.now() - timedelta(minutes=interval_minutes * (n_points - i))
        for i in range(n_points)
    ]

    data = {}
    for kw in keywords:
        t = np.linspace(0, 1, n_points)
        if pattern == "viral_spike":
            base = 5 + 90 * (t ** 3)
        elif pattern == "plateauing":
            base = 80 * (1 - np.exp(-4 * t))
        elif pattern == "dying":
            base = 90 * np.exp(-3 * t)
        else:
            base = np.full(n_points, 30.0)

        noise = rng.normal(0, 3, n_points)
        series = np.clip(base + noise, 0, 100)
        data[kw] = series

    return pd.DataFrame(data, index=pd.DatetimeIndex(timestamps, name="date"))


# ──────────────────────────────────────────────────────────
# VELOCITY / ACCELERATION ENGINE
# ──────────────────────────────────────────────────────────
def compute_velocity_acceleration(df: pd.DataFrame, smooth_window: int = 3) -> dict:
    results = {}

    for kw in df.columns:
        series = df[kw].astype(float)
        smoothed = series.rolling(window=smooth_window, min_periods=1).mean()

        velocity = smoothed.diff()
        acceleration = velocity.diff()

        recent_v = velocity.tail(3).mean()
        recent_a = acceleration.tail(3).mean()
        current_score = series.iloc[-1]

        momentum_score = (recent_v * 0.7) + (recent_a * 0.3)
        label = _classify_trend(recent_v, recent_a)

        results[kw] = {
            "current_score": round(float(current_score), 2),
            "avg_velocity": round(float(recent_v), 3),
            "avg_acceleration": round(float(recent_a), 3),
            "momentum_score": round(float(momentum_score), 3),
            "label": label,
        }

    return results


def _classify_trend(v: float, a: float, v_threshold: float = 0.3, a_threshold: float = 0.1) -> str:
    if v > v_threshold and a > a_threshold:
        return "PEAK_RISING"
    elif v > v_threshold and a <= a_threshold:
        return "GROWING_SLOWING"
    elif abs(v) <= v_threshold:
        return "PLATEAU"
    elif v < -v_threshold and a < -a_threshold:
        return "DYING_FAST"
    else:
        return "DECLINING"


LABEL_DISPLAY = {
    "PEAK_RISING": "🚀 PEAK RISING — รีบทำคลิป NOW",
    "GROWING_SLOWING": "📈 GROWING (ชะลอตัว) — ยังทำได้ แต่อย่าช้า",
    "PLATEAU": "➖ PLATEAU/STABLE — กระแสนิ่ง ไม่เร่งด่วน",
    "DYING_FAST": "💀 DYING FAST — ข้าม ไปคำอื่นดีกว่า",
    "DECLINING": "📉 DECLINING — เกาะกระแสได้อีกนิดเดียว",
}


def rank_keywords_by_momentum(results: dict) -> pd.DataFrame:
    report = pd.DataFrame(results).T
    report = report.sort_values("momentum_score", ascending=False)
    report.index.name = "keyword"
    return report
