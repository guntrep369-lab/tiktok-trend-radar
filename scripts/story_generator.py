"""
story_generator.py
==================
เขียน 'บทนิทานการ์ตูนเด็ก' ด้วย Claude สำหรับทำวิดีโอ YouTube แบบมีสตอรี่
(คนละโหมดกับ script_generator ที่เขียนบทขายของ — อันนี้เน้นเรียกวิว/สร้างช่อง)

หัวใจของแนวนี้คือ 'ตัวละครคงที่' — ระบบจึงบังคับให้ทุกฉากแนบคำอธิบายหน้าตาตัวละคร
(ภาษาอังกฤษ) ชุดเดียวกันลงใน visual prompt เสมอ เพื่อให้ Veo/Flow วาดตัวละคร
หน้าเดิมทุกฉาก (ถ้าใช้ Flow แนะนำสร้างภาพ character sheet แล้วใช้เป็น ingredient ด้วย)

โครงบทที่ได้ (JSON):
{
  "title": "ชื่อตอนภาษาไทย",
  "characters": [{"name": "...", "description_en": "คำอธิบายภาพตัวละคร (อังกฤษ)"}],
  "moral": "บทเรียนของเรื่อง",
  "scenes": [{"narration": "เสียงเล่าภาษาไทย", "visual_prompt": "ภาพฉาก (อังกฤษ)"}],
  "hashtags": ["#นิทานเด็ก", ...]
}

วิธีใช้:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python scripts/story_generator.py --theme "แมวน้อยขี้เกียจ เรียนรู้การแบ่งปัน" --scenes 5
    # ได้ out/story.json + prompt สำหรับวางใน Flow ทีละฉาก

ต่อยอด: python scripts/video_generator.py --keyword "นิทาน" --story-file out/story.json ...
"""

import os
import re
import sys
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("story_generator")

DEFAULT_MODEL = "claude-opus-4-8"
REQUIRED_KEYS = ("title", "characters", "moral", "scenes", "hashtags")

# สไตล์ภาพกลางของช่อง — ใช้ซ้ำทุกฉากทุกตอน ให้ทั้งช่องดูเป็นเรื่องเดียวกัน
DEFAULT_STYLE = (
    "3D animated cartoon for children, bright vibrant colors, soft rounded shapes, "
    "big expressive eyes, warm cinematic lighting, smooth animation, "
    "no text, no watermark, no logos"
)


# ──────────────────────────────────────────────────────────
# PROMPT (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def build_story_prompt(theme: str, n_scenes: int = 5) -> str:
    return f"""คุณเป็นนักเขียนบทการ์ตูนเด็กมืออาชีพ เขียนนิทานสั้นสำหรับวิดีโอ YouTube (~{n_scenes * 8} วินาที)

ธีม: {theme}

กติกา:
- ตัวละครหลักไม่เกิน 2 ตัว ตั้งชื่อไทยจำง่าย และเขียน description_en เป็นคำอธิบายภาพละเอียด
  (สี ขนาด เสื้อผ้า ลักษณะเด่น) เพื่อให้ AI วาดหน้าเดิมทุกฉาก
- แบ่งเป็น {n_scenes} ฉากพอดี โครงเรื่อง: เปิดปมเร็วในฉากแรก -> พยายาม/ผิดพลาด -> คลี่คลาย + บทเรียน
- narration = เสียงเล่านิทานภาษาไทย อบอุ่น ประโยคสั้น เด็กเล็กฟังรู้เรื่อง (ฉากละ 1-2 ประโยค)
- visual_prompt = ภาพของฉากเป็นภาษาอังกฤษ บรรยายฉากและการกระทำ และต้องเรียกชื่อตัวละครพร้อม
  คำอธิบายเต็มจาก description_en ทุกครั้งที่ตัวละครปรากฏ (ห้ามย่อ) ห้ามมีตัวหนังสือในภาพ
- เนื้อหาปลอดภัยสำหรับเด็กเล็ก 100% ไม่มีความรุนแรง/ความน่ากลัว
- moral = บทเรียน 1 ประโยค

ตอบเป็น JSON อย่างเดียว ตามรูปแบบนี้เป๊ะ:
{{
  "title": "ชื่อตอนภาษาไทย",
  "characters": [{{"name": "...", "description_en": "..."}}],
  "moral": "...",
  "scenes": [{{"narration": "...", "visual_prompt": "..."}}],
  "hashtags": ["#นิทานเด็ก", "#การ์ตูนเด็ก", "..."]
}}"""


# ──────────────────────────────────────────────────────────
# PARSE (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def parse_story(text) -> dict:
    """ดึง JSON นิทานจากคำตอบ (ทน code fence/ข้อความล้อม) — คืน None ถ้าโครงไม่ครบ"""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fence.group(1) if fence else text
    if not fence:
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            return None
        raw = raw[s:e + 1]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not all(k in data for k in REQUIRED_KEYS):
        return None
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return None
    for sc in scenes:
        if not isinstance(sc, dict) or "narration" not in sc or "visual_prompt" not in sc:
            return None
    return data


# ──────────────────────────────────────────────────────────
# SCENE PROMPTS ตัวละครคงที่ (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def character_block(story: dict) -> str:
    """รวมคำอธิบายตัวละครเป็นบล็อกเดียว ใช้แนบทุกฉาก"""
    parts = []
    for c in story.get("characters", []):
        name = c.get("name", "")
        desc = c.get("description_en", "")
        if desc:
            parts.append(f"{name}: {desc}" if name else desc)
    return " | ".join(parts)


def story_scene_prompts(story: dict, style: str = DEFAULT_STYLE) -> list:
    """
    ประกอบ visual prompt สุดท้ายต่อฉาก = สไตล์ช่อง + ตัวละคร (ชุดเดิมทุกฉาก) + ภาพฉาก
    ใช้ได้ทั้งวางใน Flow ทีละฉาก และส่งเข้า Veo API
    """
    chars = character_block(story)
    prompts = []
    for sc in story.get("scenes", []):
        prompt = f"{style}. "
        if chars:
            prompt += f"Recurring characters (keep EXACTLY consistent in every scene): {chars}. "
        prompt += f"Scene: {sc.get('visual_prompt', '')}"
        prompts.append(prompt)
    return prompts


def character_sheet_prompt(story: dict, style: str = DEFAULT_STYLE) -> str:
    """prompt สำหรับสร้างภาพ 'character sheet' ไว้ใช้เป็น ingredient ใน Flow"""
    chars = character_block(story)
    return (f"{style}. Character reference sheet on plain light background, full body, "
            f"front view, T-pose relaxed, showing: {chars}")


def format_story_text(story: dict) -> str:
    """แปลงเป็นข้อความอ่านง่าย (ไว้ print / เซฟ .txt)"""
    lines = [f"🎬 นิทาน: {story.get('title', '')}", ""]
    lines.append("ตัวละคร:")
    for c in story.get("characters", []):
        lines.append(f"  - {c.get('name', '')}: {c.get('description_en', '')}")
    lines.append("")
    for i, sc in enumerate(story.get("scenes", []), 1):
        lines.append(f"ฉาก {i}: {sc.get('narration', '')}")
    lines += ["", f"บทเรียน: {story.get('moral', '')}",
              f"แฮชแท็ก: {' '.join(story.get('hashtags', []))}"]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# GENERATION (เรียก Claude — best-effort)
# ──────────────────────────────────────────────────────────
def generate_story(theme: str, n_scenes: int = 5, model: str = None, max_tokens: int = 3000) -> dict:
    """เขียนนิทานด้วย Claude คืน dict หรือ None (ไม่มี key/SDK/parse พัง -> None)"""
    try:
        import anthropic
    except ImportError:
        logger.warning("ยังไม่ได้ติดตั้ง anthropic -> สร้างนิทานไม่ได้")
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ไม่พบ ANTHROPIC_API_KEY -> สร้างนิทานไม่ได้")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": build_story_prompt(theme, n_scenes)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.warning(f"เรียก Claude ไม่สำเร็จ ({e})")
        return None
    story = parse_story(text)
    if story is None:
        logger.warning("อ่านนิทานจากคำตอบไม่ได้")
    return story


def main():
    ap = argparse.ArgumentParser(description="เขียนบทนิทานการ์ตูนเด็กด้วย Claude")
    ap.add_argument("--theme", required=True, help='เช่น "แมวน้อยขี้เกียจ เรียนรู้การแบ่งปัน"')
    ap.add_argument("--scenes", type=int, default=5)
    ap.add_argument("--out", default="out/story.json")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    story = generate_story(args.theme, args.scenes, args.model)
    if story is None:
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print(format_story_text(story))
    print("\n=== Character sheet prompt (สร้างภาพอ้างอิง ไว้ใช้เป็น ingredient ใน Flow) ===")
    print(character_sheet_prompt(story))
    print("\n=== Scene prompts (วางใน Flow ทีละฉาก หรือใช้ต่อกับ video_generator) ===")
    for i, p in enumerate(story_scene_prompts(story), 1):
        print(f"\n[ฉาก {i}]\n{p}")
    print(f"\nบันทึกบทไว้ที่ {out_path} — ทำวิดีโอต่อ:")
    print(f'  python scripts/video_generator.py --keyword "นิทาน" --story-file {out_path} --out out/story.mp4')


if __name__ == "__main__":
    main()
