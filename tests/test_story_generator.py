"""เทสต์โหมดนิทานการ์ตูนเด็ก (ส่วน pure — ไม่เรียก Claude/Veo จริง)"""
import json

import story_generator as sg
import youtube_uploader as yu


def _story():
    return {
        "title": "โมจิแมวน้อยหัดแบ่งปัน",
        "characters": [
            {"name": "โมจิ", "description_en": "a chubby orange tabby kitten with big round green eyes and a red scarf"},
            {"name": "ปุยฝ้าย", "description_en": "a tiny white bunny with floppy ears and a blue bow"},
        ],
        "moral": "การแบ่งปันทำให้เรามีความสุขมากขึ้น",
        "scenes": [
            {"narration": "โมจิมีปลาย่างชิ้นโต", "visual_prompt": "Moji holding a big grilled fish"},
            {"narration": "ปุยฝ้ายหิวมาก", "visual_prompt": "Puifai looking hungry under a tree"},
            {"narration": "โมจิแบ่งปลาให้เพื่อน", "visual_prompt": "Moji sharing the fish with Puifai"},
        ],
        "hashtags": ["#นิทานเด็ก", "#การ์ตูนเด็ก"],
    }


# ── prompt ──
def test_story_prompt_includes_theme_and_scene_count():
    p = sg.build_story_prompt("แมวน้อยหัดแบ่งปัน", n_scenes=5)
    assert "แมวน้อยหัดแบ่งปัน" in p
    assert "5 ฉาก" in p
    assert "JSON" in p


# ── parse ──
def test_parse_story_valid():
    assert sg.parse_story(json.dumps(_story(), ensure_ascii=False)) is not None


def test_parse_story_fenced():
    text = "จัดให้:\n```json\n" + json.dumps(_story(), ensure_ascii=False) + "\n```"
    assert sg.parse_story(text) is not None


def test_parse_story_rejects_missing_keys():
    bad = _story()
    del bad["moral"]
    assert sg.parse_story(json.dumps(bad, ensure_ascii=False)) is None


def test_parse_story_rejects_bad_scene():
    bad = _story()
    bad["scenes"] = [{"narration": "x"}]  # ขาด visual_prompt
    assert sg.parse_story(json.dumps(bad, ensure_ascii=False)) is None
    assert sg.parse_story("ขอโทษครับ") is None
    assert sg.parse_story("") is None


# ── ตัวละครคงที่ (หัวใจของโหมดนี้) ──
def test_scene_prompts_repeat_characters_in_every_scene():
    prompts = sg.story_scene_prompts(_story())
    assert len(prompts) == 3
    for p in prompts:
        assert "chubby orange tabby kitten" in p  # คำอธิบายโมจิต้องอยู่ทุกฉาก
        assert "tiny white bunny" in p            # ปุยฝ้ายด้วย
        assert "no text" in p                     # สไตล์ช่องถูกแนบ


def test_character_sheet_prompt_contains_all_characters():
    p = sg.character_sheet_prompt(_story())
    assert "โมจิ" in p and "chubby orange tabby kitten" in p
    assert "reference sheet" in p


def test_format_story_text_readable():
    text = sg.format_story_text(_story())
    assert "โมจิแมวน้อยหัดแบ่งปัน" in text
    assert "บทเรียน" in text and "การแบ่งปัน" in text


def test_generate_story_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert sg.generate_story("อะไรก็ได้") is None


# ── YouTube metadata สำหรับนิทาน ──
def test_story_metadata_title_and_no_affiliate():
    meta = yu.build_story_metadata(_story())
    assert meta["title"].endswith("#Shorts")
    assert len(meta["title"]) <= yu.MAX_TITLE
    assert "โมจิ" in meta["title"]
    assert "🛒" not in meta["description"]      # ห้ามมีลิงก์ขายของในคลิปเด็ก
    assert "affiliate" not in meta["description"]
    assert "นิทานเด็ก" in meta["tags"]


def test_story_metadata_empty_story_safe():
    meta = yu.build_story_metadata({})
    assert meta["title"].endswith("#Shorts")
    assert meta["tags"]
