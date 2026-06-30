"""เทสต์ logic กันแจ้งเตือนซ้ำ (alert de-dup cooldown)"""
from datetime import datetime, timezone, timedelta

import run_radar


def _alert(kw):
    return {"keyword": kw, "momentum_score": 2.0, "current_score": 80,
            "label": "GROWTH", "label_display": "x", "product_suggestion": None}


def test_new_keyword_passes():
    now = datetime(2026, 6, 30, tzinfo=timezone.utc)
    fresh = run_radar.filter_recent_alerts([_alert("ใหม่")], state={}, cooldown_hours=12, now=now)
    assert [a["keyword"] for a in fresh] == ["ใหม่"]


def test_recent_keyword_is_filtered():
    now = datetime(2026, 6, 30, 12, tzinfo=timezone.utc)
    state = {"เก่า": (now - timedelta(hours=2)).isoformat()}  # เพิ่งเตือน 2 ชม.ที่แล้ว
    fresh = run_radar.filter_recent_alerts([_alert("เก่า")], state, cooldown_hours=12, now=now)
    assert fresh == []  # ยังอยู่ใน cooldown -> ตัดทิ้ง


def test_old_keyword_passes_again():
    now = datetime(2026, 6, 30, 12, tzinfo=timezone.utc)
    state = {"เก่า": (now - timedelta(hours=20)).isoformat()}  # เตือนไปนานเกิน cooldown
    fresh = run_radar.filter_recent_alerts([_alert("เก่า")], state, cooldown_hours=12, now=now)
    assert [a["keyword"] for a in fresh] == ["เก่า"]


def test_malformed_timestamp_passes():
    now = datetime(2026, 6, 30, tzinfo=timezone.utc)
    state = {"พัง": "not-a-timestamp"}
    fresh = run_radar.filter_recent_alerts([_alert("พัง")], state, cooldown_hours=12, now=now)
    assert [a["keyword"] for a in fresh] == ["พัง"]
