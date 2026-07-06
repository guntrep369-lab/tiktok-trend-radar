"""เทสต์ส่วน pure ของสายการผลิตวิดีโอ (ไม่เรียก Veo/TTS/YouTube จริง)"""
import video_generator as vg
import youtube_uploader as yu


def _script():
    return {
        "hook": "แมวเมินอาหาร 3 ยี่ห้อ จนเจอตัวนี้",
        "script": ["ช็อตปัญหา", "ช็อตสินค้า", "ช็อตผลลัพธ์"],
        "caption": "ทาสแมวต้องลอง",
        "hashtags": ["#ทาสแมว", "#อาหารเปียกแมว"],
        "cta": "กดตะกร้าเหลืองเลย",
        "audio_idea": "เพลง cute จาก CML",
    }


# ── scene prompts (fallback template) ──
def test_fallback_prompts_count_and_language():
    ps = vg.fallback_scene_prompts("อาหารเปียกแมว", max_scenes=3)
    assert len(ps) == 3
    for p in ps:
        assert "9:16" in p and "no text overlays" in p  # แนวตั้ง + ห้ามตัวหนังสือ


def test_fallback_prompts_include_product_and_shots():
    ps = vg.fallback_scene_prompts("อาหารเปียกแมว", product_name="Wet Cat Food X",
                                   shots=["แมววิ่งมา"], max_scenes=2)
    assert len(ps) == 2
    assert "Wet Cat Food X" in ps[0]
    assert "แมววิ่งมา" in ps[0]  # ช็อตแรกถูกแนบเป็น context


def test_build_scene_prompts_without_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ps = vg.build_scene_prompts("คอลลาเจน", _script(), max_scenes=3)
    assert len(ps) == 3


# ── voiceover text ──
def test_voiceover_text_joins_hook_shots_cta():
    text = vg.voiceover_text_from_script(_script())
    assert text.startswith("แมวเมิน")
    assert "กดตะกร้าเหลืองเลย" in text
    assert "ช็อตสินค้า" in text


# ── ASS subtitles ──
def test_ass_subtitles_structure_and_timing():
    ass = vg.build_ass_subtitles(["สั้น", "บรรทัดนี้ยาวกว่ามากๆๆๆๆๆๆๆๆ"], total_seconds=10.0)
    assert "[Script Info]" in ass and "PlayResY: 1920" in ass
    events = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(events) == 2
    assert "สั้น" in events[0]
    # บรรทัดสุดท้ายต้องจบไม่เกินความยาววิดีโอ
    assert "0:00:10.00" in events[-1]


def test_ass_subtitles_empty_lines_safe():
    ass = vg.build_ass_subtitles([], total_seconds=10.0)
    assert "Dialogue:" not in ass
    ass2 = vg.build_ass_subtitles(["x"], total_seconds=0)
    assert "Dialogue:" not in ass2


def test_ass_time_format():
    assert vg._ass_time(0) == "0:00:00.00"
    assert vg._ass_time(75.5) == "0:01:15.50"


# ── YouTube metadata ──
def test_metadata_title_has_shorts_and_within_limit():
    meta = yu.build_metadata("อาหารเปียกแมว", _script())
    assert meta["title"].endswith("#Shorts")
    assert len(meta["title"]) <= yu.MAX_TITLE


def test_metadata_includes_affiliate_link_and_disclosure():
    apd = {"product_name": "Wet Food X", "affiliate_link": "https://vt.tiktok.com/abc/"}
    meta = yu.build_metadata("อาหารเปียกแมว", _script(), apd)
    assert "https://vt.tiktok.com/abc/" in meta["description"]
    assert "affiliate" in meta["description"]  # คำเปิดเผย
    assert "ทาสแมว" in meta["tags"]


def test_metadata_without_script_falls_back_to_keyword():
    meta = yu.build_metadata("อาหารเปียกแมว")
    assert "อาหารเปียกแมว" in meta["title"]
    assert meta["tags"][0] == "อาหารเปียกแมว"


def test_metadata_skips_empty_affiliate_link():
    apd = {"product_name": "X", "affiliate_link": ""}  # ช่องว่างจาก scaffold
    meta = yu.build_metadata("k", _script(), apd)
    assert "🛒" not in meta["description"]  # ไม่มีบรรทัดลิงก์สินค้า (disclosure ยังอยู่ได้)
