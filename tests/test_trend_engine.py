"""เทสต์เครื่องคำนวณ velocity/acceleration และตัวจัดเฟส (classifier)"""
import numpy as np
import pandas as pd

from trend_engine import (
    _classify_trend,
    _resolve_patterns,
    _pattern_base,
    compute_velocity_acceleration,
    rank_keywords_by_momentum,
    simulate_trend_data,
)


# ── classifier: ทดสอบตรงๆ แบบ deterministic (หัวใจของระบบ) ──
def test_classify_decline():
    # velocity ติดลบชัดเจน -> ดับ (เช็คก่อนเพื่อน)
    assert _classify_trend(v=-1.0, a=0.0, current_score=80) == "DECLINE"


def test_classify_intro():
    # คะแนนต่ำ + เริ่มขยับขึ้น -> เกิด
    assert _classify_trend(v=0.6, a=0.0, current_score=20) == "INTRO"


def test_classify_growth():
    # โต + ยังเร่ง (a เป็นบวก) -> พุ่ง
    assert _classify_trend(v=0.6, a=0.5, current_score=60) == "GROWTH"


def test_classify_peak():
    # โตอยู่แต่แรงเร่งแผ่ว/ติดลบ -> พีค
    assert _classify_trend(v=0.6, a=-0.5, current_score=60) == "PEAK"


def test_classify_stable():
    # แทบไม่ขยับ -> นิ่ง
    assert _classify_trend(v=0.0, a=0.0, current_score=50) == "STABLE"


def test_classify_decline_beats_intro():
    # v ติดลบแรง ต้องเป็น DECLINE แม้คะแนนจะต่ำ (ลำดับความสำคัญถูกต้อง)
    assert _classify_trend(v=-1.0, a=0.0, current_score=10) == "DECLINE"


# ── _resolve_patterns: รองรับ str / list / dict ──
def test_resolve_patterns_str():
    assert _resolve_patterns("dying", ["a", "b"]) == {"a": "dying", "b": "dying"}


def test_resolve_patterns_list_cycles():
    got = _resolve_patterns(["x", "y"], ["a", "b", "c"])
    assert got == {"a": "x", "b": "y", "c": "x"}


def test_resolve_patterns_dict_with_fallback():
    got = _resolve_patterns({"a": "dying"}, ["a", "b"])
    assert got["a"] == "dying"
    assert got["b"] == "viral_spike"  # คำที่ไม่ระบุ -> fallback


# ── _pattern_base: รูปทรงเส้นถูกต้อง (ไม่มี noise -> deterministic) ──
def test_pattern_base_shapes():
    t = np.linspace(0, 1, 50)
    assert _pattern_base("viral_spike", t, 50)[-1] > _pattern_base("viral_spike", t, 50)[0]  # โตขึ้น
    assert _pattern_base("dying", t, 50)[-1] < _pattern_base("dying", t, 50)[0]              # ตกลง
    assert _pattern_base("emerging", t, 50)[-1] < 35                                          # จบต่ำกว่าเกณฑ์ INTRO
    flat = _pattern_base("flat_unknown", t, 50)
    assert np.allclose(flat, 30.0)                                                            # ไม่รู้จัก -> นิ่ง 30


# ── compute_velocity_acceleration: คืนคีย์ครบ + จัดเฟสได้ ──
def test_compute_returns_expected_keys():
    # สร้างเส้นไต่ขึ้นแบบเร่ง (ไม่มี noise) -> ต้องได้ GROWTH
    vals = np.array([i ** 2 for i in range(20)], dtype=float)
    df = pd.DataFrame({"kw": vals})
    res = compute_velocity_acceleration(df)["kw"]
    for key in ("current_score", "avg_velocity", "avg_acceleration", "momentum_score", "label"):
        assert key in res
    assert res["avg_velocity"] > 0
    assert res["label"] == "GROWTH"


def test_compute_detects_decline():
    vals = np.linspace(100, 0, 20)  # ตกเป็นเส้นตรง
    df = pd.DataFrame({"kw": vals})
    assert compute_velocity_acceleration(df)["kw"]["label"] == "DECLINE"


# ── rank: เรียง momentum จากมากไปน้อย ──
def test_rank_sorts_descending():
    results = {
        "low":  {"momentum_score": 0.1, "label": "STABLE", "current_score": 10,
                 "avg_velocity": 0.0, "avg_acceleration": 0.0},
        "high": {"momentum_score": 5.0, "label": "GROWTH", "current_score": 90,
                 "avg_velocity": 2.0, "avg_acceleration": 1.0},
    }
    report = rank_keywords_by_momentum(results)
    assert list(report.index) == ["high", "low"]
    assert report.index.name == "keyword"


# ── integration: simulate หมุนแพทเทิร์น -> เห็นหลายเฟส (เป้าหมายของ bug #3) ──
def test_simulate_produces_phase_variety():
    kws = [f"k{i}" for i in range(20)]
    cycle = ["viral_spike", "plateauing", "emerging", "dying", "noise"]
    pattern_map = {kw: cycle[i % len(cycle)] for i, kw in enumerate(kws)}
    df = simulate_trend_data(kws, pattern=pattern_map, seed=0)
    labels = {v["label"] for v in compute_velocity_acceleration(df).values()}
    # ก่อนแก้บั๊ก #3 จะเห็นแค่ GROWTH/PEAK; หลังแก้ต้องหลากหลายชัดเจน
    assert len(labels) >= 4
