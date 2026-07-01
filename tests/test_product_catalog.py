"""เทสต์การจับคู่คีย์เวิร์ด -> สินค้าตัวจริงในแคตตาล็อก"""
import product_catalog as pc


CATALOG = [
    {"product_name": "คอลลาเจนเปปไทด์", "affiliate_link": "https://x/1", "commission_pct": 15,
     "match": {"keywords": ["คอลลาเจน", "วิตามินผิว"], "moods": ["สวย_แต่งหน้า"]}},
    {"product_name": "หม้อทอดไร้น้ำมัน", "affiliate_link": "https://x/2", "commission_pct": 8,
     "match": {"keywords": ["หม้อทอด"], "moods": ["ไลฟ์สไตล์_ทำความสะอาด"]}},
    {"product_name": "สินค้าอารมณ์เดียว", "affiliate_link": "https://x/3",
     "match": {"keywords": [], "moods": ["ออกกำลัง_สุขภาพ"]}},
]


def test_keyword_match_wins():
    m = pc.match_affiliate_product("คอลลาเจนเปปไทด์ยี่ห้อดัง", catalog=CATALOG)
    assert m is not None and m["product_name"] == "คอลลาเจนเปปไทด์"


def test_keyword_substring_both_directions():
    # คีย์เวิร์ดสั้นกว่าคำใน catalog ก็ควรจับได้
    assert pc.match_affiliate_product("หม้อทอด", catalog=CATALOG)["product_name"] == "หม้อทอดไร้น้ำมัน"


def test_mood_fallback_when_no_keyword():
    # ไม่มีคีย์เวิร์ดตรง แต่ mood ตรง -> คืนสินค้าตาม mood
    m = pc.match_affiliate_product("วิ่งมาราธอน", mood_key="ออกกำลัง_สุขภาพ", catalog=CATALOG)
    assert m is not None and m["product_name"] == "สินค้าอารมณ์เดียว"


def test_no_match_returns_none():
    assert pc.match_affiliate_product("อะไรก็ไม่รู้", catalog=CATALOG) is None
    assert pc.match_affiliate_product("อะไรก็ไม่รู้", mood_key="ไม่มี", catalog=CATALOG) is None


def test_empty_catalog_returns_none():
    assert pc.match_affiliate_product("คอลลาเจน", catalog=[]) is None


def test_missing_file_load_returns_empty(tmp_path):
    assert pc.load_catalog(tmp_path / "nope.json") == []


def test_load_real_starter_catalog():
    # ไฟล์ starter ในโปรเจกต์ต้องอ่านได้และมีโครงสร้างถูกต้อง
    cat = pc.load_catalog()
    assert isinstance(cat, list)
    for p in cat:
        assert "product_name" in p and "match" in p
