"""
script_generator.py
===================
สร้าง 'สคริปต์คลิป TikTok Affiliate' อัตโนมัติด้วย Claude
เติมชิ้นส่วนที่หายไปจาก workflow: GitHub แจ้งเตือน -> [Claude คิดสคริปต์] -> CapCut -> TikTok Shop

รับ: คีย์เวิร์ด + อารมณ์ + หมวดสินค้า + เฟส (+ วันที่เหลือถ้ามี)
คืน: dict {hook, script, caption, hashtags, cta, audio_idea} หรือ None ถ้าทำไม่ได้

ต้องการ env var ANTHROPIC_API_KEY (ตั้งใน GitHub Secrets). ถ้าไม่มี -> ข้าม (ไม่ทำ pipeline ล่ม)
โมเดลปรับได้ผ่าน config `script_model` (ดีฟอลต์ claude-opus-4-8)

วิธีใช้ (สั่งเดี่ยวๆ บนเครื่องตัวเอง):
    export ANTHROPIC_API_KEY="sk-ant-..."
    python scripts/script_generator.py --keyword "คอลลาเจน"
    python scripts/script_generator.py --keyword "หม้อทอดไร้น้ำมัน" --label GROWTH
"""

import os
import re
import sys
import json
import logging
import argparse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("script_generator")

DEFAULT_MODEL = "claude-opus-4-8"
REQUIRED_KEYS = ("hook", "script", "caption", "hashtags", "cta", "audio_idea")


# ──────────────────────────────────────────────────────────
# PROMPT (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def _build_prompt(keyword, mood_display=None, products=None, label=None, days_remaining=None) -> str:
    ctx = [f"คีย์เวิร์ด/เทรนด์: {keyword}"]
    if mood_display:
        ctx.append(f"อารมณ์ของคอนเทนต์: {mood_display}")
    if products:
        ctx.append(f"สินค้าที่จะขาย (affiliate): {', '.join(products[:3])}")
    if label:
        ctx.append(f"เฟสของเทรนด์ตอนนี้: {label}")
    if days_remaining is not None:
        ctx.append(f"คาดว่าเทรนด์เหลืออีกประมาณ {days_remaining} วัน (รีบทำ)")
    context = "\n".join(f"- {c}" for c in ctx)

    return f"""คุณเป็นครีเอเตอร์ TikTok สาย affiliate มืออาชีพในไทย เขียนสคริปต์คลิปสั้น (15-30 วินาที) ที่ทำให้คนอยากซื้อสินค้าผ่านลิงก์

ข้อมูลเทรนด์รอบนี้:
{context}

เขียนสคริปต์ 1 คลิปที่:
- ฮุก 3 วินาทีแรกต้องดึงให้หยุดนิ้ว (ตั้งคำถาม/เปิดปัญหา/ผลลัพธ์ที่เห็นชัด)
- พูดถึงปัญหาที่คีย์เวิร์ดนี้แก้ แล้วเชื่อมเข้าสินค้าแบบเนียน ไม่ขายตรงจนน่ารำคาญ
- ปิดด้วย CTA ให้กดตะกร้า/ลิงก์
- ใช้ภาษาพูดแบบวัยรุ่นไทย เป็นกันเอง
- แนะนำเสียง/เพลงประกอบที่ 'ใช้เชิงพาณิชย์ได้' (Commercial Music Library ของ TikTok) หรือเสียงพูดเอง — อย่าใช้เพลงลิขสิทธิ์ทั่วไปเพราะบัญชี Shop จะโดนมิวต์

ตอบกลับเป็น JSON อย่างเดียว ไม่มีข้อความอื่น ตามรูปแบบนี้เป๊ะ:
{{
  "hook": "ประโยคเปิด 3 วินาทีแรก",
  "script": ["ช็อต/ประโยคที่ 1", "ช็อตที่ 2", "..."],
  "caption": "แคปชั่นใต้คลิป",
  "hashtags": ["#แฮชแท็ก1", "#แฮชแท็ก2", "..."],
  "cta": "ประโยคปิดเรียกให้กดซื้อ",
  "audio_idea": "แนวเพลง/เสียงประกอบที่ปลอดลิขสิทธิ์เชิงพาณิชย์"
}}"""


# ──────────────────────────────────────────────────────────
# RESPONSE PARSING (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def _parse_response(text) -> dict:
    """ดึง JSON ออกจากคำตอบ (รองรับทั้งแบบมี code fence และไม่มี) — คืน None ถ้าพัง"""
    if not text:
        return None
    # ตัด code fence ```json ... ``` ถ้ามี
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    # เผื่อมีข้อความนำ/ตาม -> คว้าตั้งแต่ { แรกถึง } สุดท้าย
    if not fence:
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e == -1 or e < s:
            return None
        raw = raw[s:e + 1]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in REQUIRED_KEYS):
        return None
    return data


# ──────────────────────────────────────────────────────────
# RENDER (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def format_script_text(kw: str, script: dict) -> str:
    """แปลง dict สคริปต์เป็นข้อความอ่านง่าย (สำหรับ print / เก็บ / ย่อลง LINE)"""
    lines = [f"🎬 สคริปต์: {kw}", f"🪝 ฮุก: {script.get('hook', '')}", "", "📋 สคริปต์:"]
    for i, shot in enumerate(script.get("script", []), 1):
        lines.append(f"   {i}. {shot}")
    lines += [
        "",
        f"✍️ แคปชั่น: {script.get('caption', '')}",
        f"🏷️ แฮชแท็ก: {' '.join(script.get('hashtags', []))}",
        f"🛒 CTA: {script.get('cta', '')}",
        f"🎵 เสียง: {script.get('audio_idea', '')}",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# GENERATION (เรียก Claude API — best-effort)
# ──────────────────────────────────────────────────────────
def generate_script(keyword, mood_display=None, products=None, label=None,
                    days_remaining=None, model=None, max_tokens=1500):
    """
    สร้างสคริปต์ 1 คลิปจากคีย์เวิร์ด คืน dict หรือ None
    (None เมื่อ: ไม่มี anthropic / ไม่มี API key / เรียกไม่สำเร็จ / parse ไม่ได้)
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("ยังไม่ได้ติดตั้ง anthropic (pip install anthropic) -> ข้ามการสร้างสคริปต์")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ไม่พบ ANTHROPIC_API_KEY -> ข้ามการสร้างสคริปต์ (ตั้งใน GitHub Secrets เพื่อเปิดใช้)")
        return None

    model = model or DEFAULT_MODEL
    prompt = _build_prompt(keyword, mood_display, products, label, days_remaining)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.warning(f"เรียก Claude ไม่สำเร็จ ({e}) -> ข้ามการสร้างสคริปต์")
        return None

    script = _parse_response(text)
    if script is None:
        logger.warning(f"อ่านสคริปต์จากคำตอบไม่ได้สำหรับ '{keyword}' -> ข้าม")
    return script


def main():
    ap = argparse.ArgumentParser(description="สร้างสคริปต์คลิป TikTok Affiliate ด้วย Claude")
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--mood", default=None, help="อารมณ์ (mood display)")
    ap.add_argument("--label", default=None, help="เฟสของเทรนด์ เช่น GROWTH/PEAK")
    ap.add_argument("--model", default=None, help=f"โมเดล (ดีฟอลต์ {DEFAULT_MODEL})")
    args = ap.parse_args()

    # ถ้าไม่ได้ระบุ mood/products ให้เดาจาก meme_product_map
    products = None
    mood = args.mood
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from meme_product_map import match_product
        prod = match_product(args.keyword)
        products = prod.get("products")
        mood = mood or prod.get("mood_display")
    except Exception:
        pass

    script = generate_script(args.keyword, mood_display=mood, products=products,
                             label=args.label, model=args.model)
    if script is None:
        logger.info("(ไม่ได้สคริปต์ — ตรวจ ANTHROPIC_API_KEY / การติดตั้ง anthropic)")
        sys.exit(1)
    print(format_script_text(args.keyword, script))


if __name__ == "__main__":
    main()
