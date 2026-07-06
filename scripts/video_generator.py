"""
video_generator.py
==================
สร้าง 'วิดีโอ AI' จากสคริปต์ที่ Claude เขียน แล้วได้ mp4 แนวตั้ง 9:16 พร้อมโพสต์
ต่อท่อ: script (Claude) -> ภาพวิดีโอ AI (Google Veo) -> เสียงพากย์ไทย (Edge TTS ฟรี)
       -> ประกอบด้วย ffmpeg (ต่อคลิป + แทนเสียงด้วยพากย์ไทย + ซับไทยแบบ ASS)

ต้องการ (เฉพาะโหมดสร้างจริง):
- env GEMINI_API_KEY   (Google AI Studio — Veo มีค่าใช้จ่ายต่อคลิป!)
- env ANTHROPIC_API_KEY (ใช้เขียนสคริปต์+scene prompt; ไม่มีก็ fallback template ได้)
- ffmpeg ในเครื่อง + ฟอนต์ไทย (บน GitHub Actions: apt install ffmpeg fonts-thai-tlwg)
- pip install -r requirements-video.txt

ค่าใช้จ่าย: Veo คิดต่อวินาที ที่ 3 ฉาก x 8 วิ = ~24 วิ/คลิป ตกราวหลักสิบถึงร้อยกว่าบาทต่อคลิป
(ขึ้นกับรุ่น fast/ปกติ) — เช็คราคาปัจจุบันที่ ai.google.dev ก่อนใช้จริง

วิธีใช้:
    # ดูแผน+ประเมินก่อน ไม่เสียเงิน
    python scripts/video_generator.py --keyword "อาหารเปียกแมว" --dry-run

    # สร้างจริง
    python scripts/video_generator.py --keyword "อาหารเปียกแมว" --out out/video.mp4
"""

import os
import re
import sys
import json
import time
import shutil
import logging
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from meme_product_map import match_product
from product_catalog import match_affiliate_product
from script_generator import generate_script

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("video_generator")

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"

# ดีฟอลต์ (override ได้ใน config.json) — model id ของ Veo เปลี่ยนตามรอบ release ของ Google
# ถ้าเรียกแล้ว 404 ให้เช็คชื่อรุ่นล่าสุดที่ https://ai.google.dev/gemini-api/docs/video
DEFAULT_VEO_MODEL = "veo-3.0-fast-generate-001"
DEFAULT_ASPECT = "9:16"
DEFAULT_MAX_SCENES = 3
DEFAULT_TTS_VOICE = "th-TH-PremwadeeNeural"  # เสียงหญิงไทย (ฟรี ผ่าน edge-tts); ชาย: th-TH-NiwatNeural
SCENE_SECONDS = 8  # Veo 3 สร้างคลิปละ ~8 วินาที


def load_video_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    return {
        "model": cfg.get("video_model", DEFAULT_VEO_MODEL),
        "aspect": cfg.get("video_aspect", DEFAULT_ASPECT),
        "max_scenes": cfg.get("video_max_scenes", DEFAULT_MAX_SCENES),
        "voice": cfg.get("video_tts_voice", DEFAULT_TTS_VOICE),
    }


# ──────────────────────────────────────────────────────────
# SCENE PROMPTS (pure fallback — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def fallback_scene_prompts(keyword: str, product_name: str = None, shots: list = None,
                           max_scenes: int = DEFAULT_MAX_SCENES) -> list:
    """
    สร้าง prompt ภาษาอังกฤษให้ Veo แบบ template (ใช้เมื่อไม่มี ANTHROPIC_API_KEY)
    โครง 3 ฉากมาตรฐานของคลิปขายของ: ปัญหา -> สินค้า/วิธีใช้ -> ผลลัพธ์+CTA
    """
    subject = product_name or keyword
    base = ("Vertical 9:16 photorealistic TikTok-style product video, bright natural lighting, "
            "clean modern Thai home setting, no text overlays, no watermarks, no logos. ")
    templates = [
        base + f"Scene showing the everyday problem that '{subject}' solves — a relatable frustrated moment, close-up details.",
        base + f"Hero shot of '{subject}' being used — hands demonstrating the product, satisfying close-up of texture and results.",
        base + f"Happy result after using '{subject}' — satisfied person or pet, warm mood, product placed clearly in frame.",
    ]
    if shots:
        # ถ้ามีช็อตจากสคริปต์ Claude เอามาเสริมความจำเพาะ (ตัดให้เท่า max_scenes)
        merged = []
        for i in range(min(max_scenes, len(templates))):
            hint = shots[i] if i < len(shots) else ""
            merged.append(templates[i] + (f" Context from Thai script: {hint}" if hint else ""))
        return merged
    return templates[:max_scenes]


def build_scene_prompts(keyword: str, script: dict, product_name: str = None,
                        max_scenes: int = DEFAULT_MAX_SCENES) -> list:
    """แปลงช็อตในสคริปต์เป็น Veo prompt ภาษาอังกฤษ (ใช้ Claude ถ้ามี key, ไม่มีก็ template)"""
    shots = (script or {}).get("script", [])
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback_scene_prompts(keyword, product_name, shots, max_scenes)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=[{"role": "user", "content": (
                f"Convert this Thai TikTok script for '{keyword}'"
                + (f" (product: {product_name})" if product_name else "")
                + f" into exactly {max_scenes} English text-to-video prompts for Google Veo.\n"
                f"Script shots: {json.dumps(shots, ensure_ascii=False)}\n\n"
                "Rules: each prompt is one paragraph, photorealistic vertical 9:16 product/lifestyle scene, "
                "no on-screen text, no watermarks, no brand logos, no speech. "
                "Respond ONLY with a JSON array of strings, nothing else."
            )}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        m = re.search(r"\[.*\]", text, re.DOTALL)
        prompts = json.loads(m.group(0)) if m else None
        if isinstance(prompts, list) and prompts:
            return [str(p) for p in prompts[:max_scenes]]
    except Exception as e:
        logger.warning(f"สร้าง scene prompt ด้วย Claude ไม่สำเร็จ ({e}) -> ใช้ template")
    return fallback_scene_prompts(keyword, product_name, shots, max_scenes)


# ──────────────────────────────────────────────────────────
# VEO (มีค่าใช้จ่าย — เรียกเฉพาะตอนสร้างจริง)
# ──────────────────────────────────────────────────────────
def generate_clips_veo(prompts: list, model: str, aspect: str, work_dir: Path) -> list:
    """เรียก Google Veo สร้างคลิปทีละฉาก คืน list ของ path (throw ถ้าไม่มี key/SDK)"""
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("ไม่พบ GEMINI_API_KEY — ตั้งค่าก่อนสร้างวิดีโอจริง (มีค่าใช้จ่ายต่อคลิป)")
    from google import genai
    from google.genai import types

    client = genai.Client()
    paths = []
    for i, prompt in enumerate(prompts, start=1):
        logger.info(f"[Veo] สร้างฉาก {i}/{len(prompts)} ...")
        op = client.models.generate_videos(
            model=model,
            prompt=prompt,
            config=types.GenerateVideosConfig(aspect_ratio=aspect, number_of_videos=1),
        )
        while not op.done:
            time.sleep(10)
            op = client.operations.get(op)
        vids = getattr(op.response, "generated_videos", None) or []
        if not vids:
            raise RuntimeError(f"Veo ไม่คืนวิดีโอสำหรับฉาก {i} (อาจโดน safety filter) — prompt: {prompt[:80]}")
        video = vids[0].video
        path = work_dir / f"scene_{i}.mp4"
        try:
            client.files.download(file=video)
            video.save(str(path))
        except Exception:
            # SDK บางเวอร์ชันให้ bytes ตรงๆ
            data = getattr(video, "video_bytes", None)
            if not data:
                raise
            path.write_bytes(data)
        logger.info(f"[Veo] ได้ {path.name}")
        paths.append(path)
    return paths


# ──────────────────────────────────────────────────────────
# TTS เสียงพากย์ไทย (ฟรี)
# ──────────────────────────────────────────────────────────
def voiceover_text_from_script(script: dict) -> str:
    """รวมข้อความพากย์: hook -> ช็อต -> CTA (pure — เทสต์ได้)"""
    parts = [script.get("hook", "")]
    parts += [s for s in script.get("script", [])]
    parts.append(script.get("cta", ""))
    return " ".join(p.strip() for p in parts if p and p.strip())


def tts_voiceover(text: str, voice: str, out_path: Path):
    import asyncio
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, voice).save(str(out_path))

    asyncio.run(_run())
    logger.info(f"[TTS] เสียงพากย์ -> {out_path.name}")


# ──────────────────────────────────────────────────────────
# ซับไตเติล ASS (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_subtitles(lines: list, total_seconds: float, font: str = "Loma") -> str:
    """
    สร้างไฟล์ซับ .ass: แบ่งเวลาตามความยาวข้อความ (บรรทัดยาวได้เวลามาก)
    ใช้ libass เผาซับลงวิดีโอ — รองรับสระ/วรรณยุกต์ไทยถูกต้องกว่า drawtext
    """
    lines = [l.strip() for l in (lines or []) if l and l.strip()]
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        f"Style: Default,{font},64,&H00FFFFFF,&H00000000,&H80000000,1,3,1,2,60,60,260\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
    )
    if not lines or total_seconds <= 0:
        return header
    total_chars = sum(len(l) for l in lines) or 1
    events, t = [], 0.0
    for l in lines:
        dur = max(1.2, total_seconds * (len(l) / total_chars))
        end = min(t + dur, total_seconds)
        events.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(end)},Default,{l}")
        t = end
    return header + "\n".join(events) + "\n"


# ──────────────────────────────────────────────────────────
# FFMPEG ประกอบร่าง
# ──────────────────────────────────────────────────────────
def _run_ffmpeg(args: list):
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + args
    subprocess.run(cmd, check=True)


def assemble_video(clips: list, voice_path: Path, ass_path: Path, out_path: Path, work_dir: Path):
    """ต่อคลิป -> เผาซับ -> แทนเสียงด้วยพากย์ไทย (ทิ้งเสียงจาก Veo เพื่อคุมคุณภาพ)"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ไม่พบ ffmpeg — ติดตั้งก่อน (บน Actions: apt-get install -y ffmpeg fonts-thai-tlwg)")

    # 1) normalize ทุกคลิปเป็น 1080x1920 30fps ไร้เสียง
    norm_paths = []
    for i, clip in enumerate(clips, start=1):
        norm = work_dir / f"norm_{i}.mp4"
        _run_ffmpeg([
            "-i", str(clip),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", str(norm),
        ])
        norm_paths.append(norm)

    # 2) ต่อคลิปด้วย concat demuxer
    list_file = work_dir / "concat.txt"
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in norm_paths), encoding="utf-8")
    concat = work_dir / "concat.mp4"
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(concat)])

    # 3) เผาซับ + ใส่เสียงพากย์ (จบที่สั้นกว่า กันภาพ/เสียงยาวไม่เท่ากัน)
    ass_arg = str(ass_path.as_posix()).replace(":", r"\:")  # กัน drive letter บน Windows
    _run_ffmpeg([
        "-i", str(concat), "-i", str(voice_path),
        "-vf", f"ass='{ass_arg}'",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-shortest", str(out_path),
    ])
    logger.info(f"[ffmpeg] วิดีโอพร้อม -> {out_path}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="สร้างวิดีโอ AI (Veo) จากสคริปต์ Claude")
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--out", default="out/video.mp4")
    ap.add_argument("--script-file", default=None, help="JSON สคริปต์ (ถ้าไม่ใส่ จะให้ Claude เขียนใหม่)")
    ap.add_argument("--dry-run", action="store_true", help="โชว์แผน+prompt โดยไม่เรียก Veo (ไม่เสียเงิน)")
    args = ap.parse_args()

    cfg = load_video_config()
    out_path = Path(args.out)
    work_dir = out_path.parent / "work"

    # 1) สคริปต์
    ps = match_product(args.keyword)
    ap_prod = match_affiliate_product(args.keyword, ps.get("mood_key"))
    product_name = ap_prod["product_name"] if ap_prod else None
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as f:
            script = json.load(f)
    else:
        script = generate_script(args.keyword, mood_display=ps.get("mood_display"),
                                 products=[product_name] if product_name else ps.get("products"))
    if not script:
        logger.error("ไม่มีสคริปต์ (ตั้ง ANTHROPIC_API_KEY หรือส่ง --script-file)")
        sys.exit(1)

    # 2) scene prompts
    prompts = build_scene_prompts(args.keyword, script, product_name, cfg["max_scenes"])
    est_seconds = len(prompts) * SCENE_SECONDS
    logger.info(f"\nแผนวิดีโอ: {len(prompts)} ฉาก x ~{SCENE_SECONDS} วิ = ~{est_seconds} วิ | รุ่น {cfg['model']}")
    for i, p in enumerate(prompts, 1):
        logger.info(f"  ฉาก {i}: {p[:110]}...")
    if args.dry_run:
        logger.info("\n(--dry-run: จบแค่นี้ ไม่เรียก Veo ไม่เสียเงิน)")
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 3) Veo + TTS + ประกอบ
    clips = generate_clips_veo(prompts, cfg["model"], cfg["aspect"], work_dir)
    voice_path = work_dir / "voice.mp3"
    tts_voiceover(voiceover_text_from_script(script), cfg["voice"], voice_path)

    total = sum(probe_duration(c) for c in clips)
    sub_lines = [script.get("hook", "")] + list(script.get("script", [])) + [script.get("cta", "")]
    ass_path = work_dir / "subs.ass"
    ass_path.write_text(build_ass_subtitles(sub_lines, total), encoding="utf-8")

    assemble_video(clips, voice_path, ass_path, out_path, work_dir)

    # เก็บ metadata ไว้ให้ตัวอัปโหลดใช้
    meta_path = out_path.with_suffix(".json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"keyword": args.keyword, "script": script,
                   "affiliate_product": ap_prod, "video": str(out_path)}, f, ensure_ascii=False, indent=2)
    logger.info(f"เสร็จ: {out_path} (+ {meta_path.name} สำหรับอัปโหลด)")


if __name__ == "__main__":
    main()
