"""เทสต์ส่วน pure ของ script_generator (prompt/parse/render) — ไม่แตะ Claude API"""
import json

import script_generator as sg


def test_prompt_includes_context():
    p = sg._build_prompt("คอลลาเจน", mood_display="💄 สวย", products=["คอลลาเจนเปปไทด์"],
                         label="GROWTH", days_remaining=2.5)
    assert "คอลลาเจน" in p
    assert "💄 สวย" in p
    assert "GROWTH" in p
    assert "2.5" in p
    assert "JSON" in p  # ต้องสั่งให้ตอบเป็น JSON


def _valid_script():
    return {
        "hook": "หยุดก่อน!",
        "script": ["ช็อต 1", "ช็อต 2"],
        "caption": "แคปชั่น",
        "hashtags": ["#a", "#b"],
        "cta": "กดตะกร้าเลย",
        "audio_idea": "เพลงจาก Commercial Music Library",
    }


def test_parse_plain_json():
    text = json.dumps(_valid_script(), ensure_ascii=False)
    assert sg._parse_response(text) == _valid_script()


def test_parse_fenced_json():
    text = "นี่คือสคริปต์:\n```json\n" + json.dumps(_valid_script(), ensure_ascii=False) + "\n```\nจบ"
    assert sg._parse_response(text) is not None


def test_parse_json_with_surrounding_prose():
    text = "ได้เลยครับ " + json.dumps(_valid_script(), ensure_ascii=False) + " หวังว่าจะชอบ"
    assert sg._parse_response(text) is not None


def test_parse_rejects_missing_keys():
    assert sg._parse_response('{"hook": "x"}') is None


def test_parse_rejects_garbage():
    assert sg._parse_response("ขอโทษครับ ผมทำไม่ได้") is None
    assert sg._parse_response("") is None
    assert sg._parse_response(None) is None


def test_format_script_text():
    out = sg.format_script_text("คอลลาเจน", _valid_script())
    assert "คอลลาเจน" in out
    assert "หยุดก่อน!" in out
    assert "กดตะกร้าเลย" in out
    assert "ช็อต 1" in out


def test_generate_script_without_api_key(monkeypatch):
    # ไม่มี key -> ต้องคืน None อย่างนุ่มนวล ไม่ throw
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert sg.generate_script("คอลลาเจน") is None
