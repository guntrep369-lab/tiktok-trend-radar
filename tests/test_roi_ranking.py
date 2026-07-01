"""เทสต์การถ่วง ranking ด้วยน้ำหนัก ROI ใน run_radar"""
import run_radar as rr


def test_apply_weights_scales_momentum():
    items = [
        {"momentum_score": 2.0, "product_suggestion": {"mood_key": "รวย"}},
        {"momentum_score": 3.0, "product_suggestion": {"mood_key": "จน"}},
    ]
    rr.apply_roi_weights(items, {"รวย": 1.5, "จน": 0.5})
    assert items[0]["roi_weight"] == 1.5
    assert items[0]["ranking_score"] == 3.0    # 2.0 * 1.5
    assert items[1]["ranking_score"] == 1.5    # 3.0 * 0.5
    # อารมณ์ที่ ROI ดีแซงขึ้นมาแม้ momentum ต่ำกว่า
    assert items[0]["ranking_score"] > items[1]["ranking_score"]


def test_apply_weights_defaults_to_one():
    items = [{"momentum_score": 2.0, "product_suggestion": {"mood_key": "ไม่มีในน้ำหนัก"}}]
    rr.apply_roi_weights(items, {"อื่น": 1.5})
    assert items[0]["roi_weight"] == 1.0
    assert items[0]["ranking_score"] == 2.0


def test_apply_empty_weights_is_passthrough():
    items = [{"momentum_score": 2.5, "product_suggestion": {"mood_key": "x"}}]
    rr.apply_roi_weights(items, {})
    assert items[0]["ranking_score"] == 2.5
    assert items[0]["roi_weight"] == 1.0


def test_load_roi_weights_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(rr, "ROI_WEIGHTS_JSON", tmp_path / "nope.json")
    assert rr.load_roi_weights() == {}
