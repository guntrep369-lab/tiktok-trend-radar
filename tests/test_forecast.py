"""เทสต์โมเดลพยากรณ์อายุที่เหลือ (forecast_lifespan)"""
import numpy as np
import pandas as pd
import pytest

from trend_engine import forecast_lifespan, compute_velocity_acceleration

pytest.importorskip("scipy")  # ข้ามทั้งไฟล์ถ้าเครื่องไม่มี scipy


def _gauss_series(periods, mu=20, sigma=6, A=80, base=5):
    idx = pd.date_range("2026-01-01", periods=periods, freq="h")
    t = np.arange(periods, dtype=float)
    y = base + A * np.exp(-((t - mu) ** 2) / (2 * sigma ** 2))
    return pd.Series(y, index=idx)


def test_recovers_known_curve_past_peak():
    # เส้นระฆังที่เลยพีคแล้วแต่ยังไม่ตาย -> fit แม่น, เหลือเวลาเป็นบวก
    s = _gauss_series(periods=31)  # พีคที่ชม.20, ข้อมูลถึงชม.30
    fc = forecast_lifespan(s)
    assert fc is not None and fc["ok"]
    assert fc["fit_r2"] > 0.95          # เส้นสะอาด -> fit ควรเกือบเป๊ะ
    assert fc["past_peak"] is True
    assert fc["days_remaining"] > 0
    assert fc["days_to_peak"] == 0      # เลยพีคแล้ว


def test_too_few_points_returns_none():
    s = _gauss_series(periods=5)
    assert forecast_lifespan(s) is None


def test_noise_is_not_confident():
    # ข้อมูลสุ่มล้วน ไม่เป็นระฆัง -> ต้องไม่ฟันธง (None หรือ ok=False)
    idx = pd.date_range("2026-01-01", periods=40, freq="h")
    y = np.random.default_rng(0).uniform(20, 80, 40)
    fc = forecast_lifespan(pd.Series(y, index=idx))
    assert fc is None or fc.get("ok") is False


def test_rising_curve_runs():
    # ครึ่งซ้ายของระฆัง (ยังขาขึ้น พีคในอนาคต) -> ต้องรันได้ไม่ error
    s = _gauss_series(periods=16)  # ข้อมูลถึงชม.15 พีคที่ชม.20
    fc = forecast_lifespan(s)
    if fc and fc.get("ok"):
        assert fc["days_to_peak"] >= 0


def test_wired_into_compute():
    # ฟิลด์พยากรณ์ต้องโผล่ใน output ของ compute_velocity_acceleration เสมอ + ทำงานจริงเมื่อ index เป็นเวลา
    s = _gauss_series(periods=31)
    df = pd.DataFrame({"kw": s})  # คง DatetimeIndex ไว้
    res = compute_velocity_acceleration(df)["kw"]
    for key in ("days_remaining", "days_to_peak", "forecast_r2"):
        assert key in res
    assert res["days_remaining"] is not None  # เส้นสะอาด -> ควร fit ผ่านและได้ค่าจริง
