"""เทสต์การจับคู่ คีย์เวิร์ด -> อารมณ์ -> หมวดสินค้า"""
from meme_product_map import match_product


def test_match_beauty_keyword():
    res = match_product("เซรั่มหน้าใส")
    assert res["mood_key"] == "สวย_แต่งหน้า"
    assert res["products"]  # มีคำแนะนำสินค้า


def test_match_cleaning_keyword():
    res = match_product("ที่ดูดฝุ่นไร้สาย")
    assert res["mood_key"] == "ไลฟ์สไตล์_ทำความสะอาด"


def test_unmatched_keyword_uses_default():
    res = match_product("xyzzy123ไม่มีในตาราง")
    assert res["mood_key"] == "default"
    assert res["products"]


def test_match_returns_required_shape():
    res = match_product("คอลลาเจน")
    for key in ("mood_key", "mood_display", "products"):
        assert key in res
    assert isinstance(res["products"], list)
