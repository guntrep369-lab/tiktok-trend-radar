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
def _pattern_base(pattern: str, t: np.ndarray, n_points: int) -> np.ndarray:
    """
    คืน base curve ตามแพทเทิร์นที่ขอ (t คือเวลานอร์มัลไลซ์ 0->1)
    ออกแบบให้แต่ละแพทเทิร์นไปตกในเฟสที่ต่างกัน เพื่อทดสอบ classifier ได้ครบ:
      viral_spike -> GROWTH   (โตเร็วและยังเร่ง)
      plateauing  -> PEAK     (ยังโตแต่แรงเร่งแผ่ว)
      emerging    -> INTRO    (คะแนนยังต่ำ <35 แต่เริ่มไต่ขึ้นเร็ว)
      dying       -> DECLINE  (กำลังตก)
      flat/noise  -> STABLE   (นิ่ง ไม่มีทิศทาง)
    """
    if pattern == "viral_spike":
        # โตแบบเร่ง: ช่วงท้าย v เป็นบวกและ a เป็นบวก -> GROWTH
        return 5 + 90 * (t ** 3)
    if pattern == "plateauing":
        # รากที่สอง: ยังไต่ขึ้นเร็วพอ (v>0) แต่ชะลอตัว (a<0) ตลอด -> PEAK
        return 95 * np.sqrt(t)
    if pattern == "emerging":
        # โค้งกำลังสองคูณ 30: จบที่ ~30 (ยังต่ำกว่าเกณฑ์ INTRO) แต่ช่วงท้ายชันพอให้ v เป็นบวกชัด
        return 30 * (t ** 2)
    if pattern == "dying":
        # ลดลงเป็นเส้นตรงชันสม่ำเสมอ: v ติดลบชัดเจนตลอด -> DECLINE
        return 90 - 60 * t
    # flat / noise / ไม่รู้จัก -> นิ่งที่ ~30
    return np.full(n_points, 30.0)


def _resolve_patterns(pattern, keywords: list) -> dict:
    """
    แปลงพารามิเตอร์ pattern ให้เป็น map {keyword: pattern_name}
    รองรับ 3 รูปแบบ:
      - str            -> ใช้แพทเทิร์นเดียวกับทุกคำ (ค่าเริ่มต้นเดิม, backward compatible)
      - list/tuple     -> วนแพทเทิร์นตามลำดับคำ
      - dict           -> ระบุรายคำ (คำที่ไม่ได้ระบุ fallback เป็น viral_spike)
    """
    if isinstance(pattern, dict):
        return {kw: pattern.get(kw, "viral_spike") for kw in keywords}
    if isinstance(pattern, (list, tuple)):
        return {kw: pattern[i % len(pattern)] for i, kw in enumerate(keywords)}
    return {kw: pattern for kw in keywords}


def simulate_trend_data(
    keywords: list,
    hours: int = 24,
    interval_minutes: int = 15,
    pattern="viral_spike",
    seed: Optional[int] = None,
    noise_std: float = 1.5,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_points = int((hours * 60) / interval_minutes)
    timestamps = [
        datetime.now() - timedelta(minutes=interval_minutes * (n_points - i))
        for i in range(n_points)
    ]
    pattern_map = _resolve_patterns(pattern, keywords)

    data = {}
    t = np.linspace(0, 1, n_points)
    for kw in keywords:
        base = _pattern_base(pattern_map[kw], t, n_points)
        noise = rng.normal(0, noise_std, n_points)
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
        label = _classify_trend(recent_v, recent_a, current_score=current_score)

        results[kw] = {
            "current_score": round(float(current_score), 2),
            "avg_velocity": round(float(recent_v), 3),
            "avg_acceleration": round(float(recent_a), 3),
            "momentum_score": round(float(momentum_score), 3),
            "label": label,
        }

    return results


def _classify_trend(
    v: float,
    a: float,
    current_score: float = 50.0,
    v_threshold: float = 0.3,
    a_threshold: float = 0.1,
    low_score_threshold: float = 35.0,
) -> str:
    """
    จัดเฟสชีวิตมีมเป็น 4 ช่วงตามกราฟระฆังคว่ำ: เกิด -> พุ่ง -> พีค -> ดับ

    พารามิเตอร์:
      v                  = velocity (ความเร็วการเปลี่ยนแปลง) เฉลี่ยช่วงท้าย
      a                  = acceleration (อัตราเร่ง) เฉลี่ยช่วงท้าย
      current_score      = คะแนน interest ล่าสุด (0-100) ใช้แยกเฟส "เกิด"
      v_threshold        = เกณฑ์ตัดสินว่า v ถือว่า "นิ่ง" หรือ "เคลื่อนไหว"
      a_threshold        = เกณฑ์ตัดสินว่า a ถือว่า "เร่ง" จริง
      low_score_threshold = คะแนนต่ำกว่านี้ + กำลังโต = ยังอยู่เฟสเกิด

    ตรรกะหลัก (เรียงตามลำดับความสำคัญ):
      1. ดับ (DECLINE)  : v ติดลบชัดเจน -> คนเบื่อแล้ว ตลาดวาย
      2. เกิด (INTRO)   : score ยังต่ำ แต่ v เริ่มเป็นบวก -> เพิ่งโผล่ จับตาไว้
      3. พุ่ง (GROWTH)  : v เป็นบวก และ a เป็นบวก -> จังหวะทอง! กำลังเร่งขึ้น
      4. พีค (PEAK)     : v ยังบวก แต่ a แผ่ว/ติดลบ -> โตอยู่แต่หมดแรงเร่ง ใกล้อิ่ม
      5. นิ่ง (STABLE)  : v แทบไม่ขยับ -> ไม่มีกระแสให้เกาะ
    """
    # 1) เฟสดับ — velocity ติดลบ = กระแสกำลังตก (เช็คก่อนเพื่อน เพราะอันตรายสุด)
    if v < -v_threshold:
        return "DECLINE"

    # 2) เฟสเกิด — คะแนนยังต่ำ แต่เริ่มขยับขึ้น = ของใหม่ที่น่าจับตา
    if current_score < low_score_threshold and v > v_threshold:
        return "INTRO"

    # 3) เฟสพุ่ง (จังหวะทอง) — กำลังโต และยัง "เร่ง" อยู่ (a เป็นบวก)
    if v > v_threshold and a > a_threshold:
        return "GROWTH"

    # 4) เฟสพีค — ยังโตอยู่ แต่แรงเร่งแผ่วลง/เริ่มติดลบ = ใกล้สุดยอด
    if v > v_threshold and a <= a_threshold:
        return "PEAK"

    # 5) ที่เหลือ = นิ่ง ไม่มีทิศทางชัด
    return "STABLE"


# label -> ข้อความที่ทีมคอนเทนต์อ่านแล้วตัดสินใจได้ทันที
LABEL_DISPLAY = {
    "INTRO":   "🌱 เกิด (Introduction) — เพิ่งโผล่ จับตาไว้ ยังไม่ต้องลงมือ",
    "GROWTH":  "🚀 พุ่ง (Growth) — จังหวะทอง! รีบทำคอนเทนต์ใน 3 ชม.",
    "PEAK":    "🔥 พีค (Peak) — โตอยู่แต่ใกล้อิ่ม ทำได้แต่ต้องรีบ",
    "DECLINE": "📉 ดับ (Decline) — คนเบื่อแล้ว หยุด เปลี่ยนคำใหม่",
    "STABLE":  "➖ นิ่ง (Stable) — ไม่มีกระแสให้เกาะ",
}

# เฟสที่ควรส่ง alert (จังหวะที่ลงมือแล้วคุ้ม) — ใช้ตอนเชื่อมกับ LINE ในส่วนที่ 3
ALERT_PHASES = {"GROWTH", "PEAK"}


def rank_keywords_by_momentum(results: dict) -> pd.DataFrame:
    report = pd.DataFrame(results).T
    report = report.sort_values("momentum_score", ascending=False)
    report.index.name = "keyword"
    return report
