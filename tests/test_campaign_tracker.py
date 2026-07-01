"""เทสต์การรวมผลงาน (feedback loop / ROI)"""
import pandas as pd

import campaign_tracker as ct


def _df(rows):
    out = pd.DataFrame(rows)
    for c in ct.COLUMNS:
        if c not in out.columns:
            out[c] = 0 if c in ct.METRIC_COLS else ""
    return out[ct.COLUMNS]


def test_empty_aggregation():
    perf = ct.aggregate_performance(_df([]))
    assert perf["totals"] == {"videos": 0, "views": 0, "clicks": 0, "orders": 0, "gmv": 0.0}
    assert perf["by_keyword"] == [] and perf["by_mood"] == []


def test_totals_and_per_video():
    df = _df([
        {"keyword": "คอลลาเจน", "mood_key": "สวย", "mood_display": "สวย",
         "views": 10000, "clicks": 300, "orders": 20, "gmv": 6000},
        {"keyword": "คอลลาเจน", "mood_key": "สวย", "mood_display": "สวย",
         "views": 5000, "clicks": 100, "orders": 5, "gmv": 2000},
    ])
    perf = ct.aggregate_performance(df)
    assert perf["totals"]["videos"] == 2
    assert perf["totals"]["gmv"] == 8000.0
    kw = perf["by_keyword"][0]
    assert kw["keyword"] == "คอลลาเจน"
    assert kw["n_videos"] == 2
    assert kw["gmv_per_video"] == 4000.0
    assert kw["ctr"] == round(400 / 15000, 4)
    assert kw["cvr"] == round(25 / 400, 4)


def test_sorted_by_gmv_desc():
    df = _df([
        {"keyword": "น้อย", "mood_key": "a", "mood_display": "a", "gmv": 100, "views": 1, "clicks": 1, "orders": 1},
        {"keyword": "เยอะ", "mood_key": "b", "mood_display": "b", "gmv": 9000, "views": 1, "clicks": 1, "orders": 1},
        {"keyword": "กลาง", "mood_key": "c", "mood_display": "c", "gmv": 500, "views": 1, "clicks": 1, "orders": 1},
    ])
    order = [k["keyword"] for k in ct.aggregate_performance(df)["by_keyword"]]
    assert order == ["เยอะ", "กลาง", "น้อย"]


def test_mood_grouping_collapses_keywords():
    # คนละคีย์เวิร์ดแต่ mood เดียวกัน -> ต้องยุบเป็นกลุ่มเดียวในมุม by_mood
    df = _df([
        {"keyword": "ลิป", "mood_key": "สวย", "mood_display": "สวย", "gmv": 1000, "views": 1, "clicks": 1, "orders": 1},
        {"keyword": "เซรั่ม", "mood_key": "สวย", "mood_display": "สวย", "gmv": 3000, "views": 1, "clicks": 1, "orders": 1},
    ])
    moods = ct.aggregate_performance(df)["by_mood"]
    assert len(moods) == 1
    assert moods[0]["mood_key"] == "สวย"
    assert moods[0]["n_videos"] == 2 and moods[0]["gmv"] == 4000.0


# ── น้ำหนัก ROI ต่ออารมณ์ ──
def _perf(by_mood):
    return {"by_mood": by_mood}


def test_roi_weights_normalized_and_clamped():
    # สองอารมณ์ gmv/คลิป 8000 vs 2000 -> mean 5000 -> 1.6 และ 0.4(clamp เป็น 0.5)
    w = ct.compute_roi_weights(_perf([
        {"mood_key": "รวย", "n_videos": 5, "gmv_per_video": 8000},
        {"mood_key": "จน", "n_videos": 5, "gmv_per_video": 2000},
    ]))
    assert w["รวย"] == 1.6
    assert w["จน"] == 0.5  # 0.4 ถูก clamp ขึ้นเป็น lo=0.5


def test_roi_weights_needs_two_moods():
    assert ct.compute_roi_weights(_perf([{"mood_key": "a", "n_videos": 9, "gmv_per_video": 5000}])) == {}


def test_roi_weights_excludes_low_video_moods():
    # อารมณ์ที่คลิปน้อยกว่า min_videos ถูกตัด -> เหลือ <2 -> {}
    w = ct.compute_roi_weights(_perf([
        {"mood_key": "a", "n_videos": 5, "gmv_per_video": 5000},
        {"mood_key": "b", "n_videos": 1, "gmv_per_video": 9000},
    ]), min_videos=3)
    assert w == {}
