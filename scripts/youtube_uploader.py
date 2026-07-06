"""
youtube_uploader.py
===================
อัปโหลดวิดีโอขึ้น YouTube (เป็น Shorts อัตโนมัติเมื่อเป็นคลิปแนวตั้ง <3 นาที)
ดีฟอลต์อัปโหลดเป็น **private** — คุณตรวจใน YouTube Studio แล้วกดปล่อย public เอง
(ตรงกับข้อจำกัดของ YouTube: แอป API ที่ยังไม่ผ่าน audit จะถูกล็อกวิดีโอเป็น private อยู่แล้ว)

ต้องการ env vars:
    YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
โควต้า: การอัปโหลด 1 ครั้ง = 1600 หน่วย จากโควต้าวันละ 10,000 -> ~6 คลิป/วัน

ตั้งค่าครั้งแรก (ทำบนเครื่องตัวเอง):
1. console.cloud.google.com -> สร้างโปรเจกต์ -> เปิดใช้ "YouTube Data API v3"
2. OAuth consent screen (External, เพิ่มอีเมลตัวเองเป็น test user)
3. Credentials -> Create OAuth client ID -> Desktop app -> ได้ client_id + client_secret
4. รัน:  python scripts/youtube_uploader.py setup --client-id XXX --client-secret YYY
   -> เบราว์เซอร์เด้งให้ล็อกอินช่อง YouTube -> ได้ refresh token มาเก็บเป็น GitHub Secret

วิธีใช้:
    python scripts/youtube_uploader.py upload --file out/video.mp4            # อ่าน meta จาก video.json ข้างๆ
    python scripts/youtube_uploader.py upload --file v.mp4 --title "..." --description "..."
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("youtube_uploader")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
MAX_TITLE = 100  # ลิมิตของ YouTube


# ──────────────────────────────────────────────────────────
# METADATA (pure — เทสต์ได้)
# ──────────────────────────────────────────────────────────
def build_metadata(keyword: str, script: dict = None, affiliate_product: dict = None) -> dict:
    """สร้าง title/description/tags จากสคริปต์ + สินค้า (ใส่ลิงก์ affiliate + คำเปิดเผยตามกติกา)"""
    script = script or {}
    hook = (script.get("hook") or "").strip()
    title = (hook[: MAX_TITLE - 8] + " #Shorts") if hook else f"{keyword} #Shorts"

    lines = []
    caption = (script.get("caption") or "").strip()
    if caption:
        lines.append(caption)
    if affiliate_product:
        name = affiliate_product.get("product_name", "")
        link = (affiliate_product.get("affiliate_link") or "").strip()
        if link:
            lines.append(f"🛒 สั่งซื้อ {name}: {link}")
    hashtags = [h.strip() for h in script.get("hashtags", []) if h and h.strip()]
    if hashtags:
        lines.append(" ".join(hashtags))
    # เปิดเผยว่าเป็นลิงก์ affiliate (นโยบายความโปร่งใส + ลดความเสี่ยงโดนรายงาน)
    lines.append("คลิปนี้มีลิงก์แนะนำสินค้า (affiliate) ผู้จัดทำอาจได้รับค่าคอมมิชชั่นจากการสั่งซื้อ")

    tags = [h.lstrip("#") for h in hashtags][:15]
    if keyword not in tags:
        tags.insert(0, keyword)
    return {"title": title, "description": "\n\n".join(lines), "tags": tags[:15]}


def build_story_metadata(story: dict) -> dict:
    """metadata สำหรับนิทานการ์ตูนเด็ก — ไม่มีลิงก์ขายของ เน้นชื่อเรื่อง+บทเรียน"""
    story = story or {}
    title = (story.get("title") or "นิทานการ์ตูนเด็ก").strip()
    title = title[: MAX_TITLE - 8] + " #Shorts"

    lines = []
    moral = (story.get("moral") or "").strip()
    if moral:
        lines.append(f"นิทานสอนใจ: {moral}")
    hashtags = [h.strip() for h in story.get("hashtags", []) if h and h.strip()]
    if hashtags:
        lines.append(" ".join(hashtags))

    tags = [h.lstrip("#") for h in hashtags][:15] or ["นิทานเด็ก", "การ์ตูนเด็ก"]
    return {"title": title, "description": "\n\n".join(lines), "tags": tags[:15]}


# ──────────────────────────────────────────────────────────
# GOOGLE API (lazy import — โมดูลนี้ import ได้แม้ไม่มีไลบรารี)
# ──────────────────────────────────────────────────────────
def get_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    cid = os.environ.get("YT_CLIENT_ID")
    csec = os.environ.get("YT_CLIENT_SECRET")
    rtok = os.environ.get("YT_REFRESH_TOKEN")
    if not (cid and csec and rtok):
        raise RuntimeError("ไม่พบ YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN — รันคำสั่ง setup ก่อน")
    creds = Credentials(
        None, refresh_token=rtok, client_id=cid, client_secret=csec,
        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(file_path: Path, meta: dict, privacy: str = "private",
                 made_for_kids: bool = False) -> str:
    """อัปโหลดแบบ resumable คืน videoId (made_for_kids=True สำหรับคอนเทนต์เด็ก ตามกฎ COPPA)"""
    from googleapiclient.http import MediaFileUpload

    service = get_service()
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": "1" if made_for_kids else "22",  # Film & Animation / People & Blogs
            "defaultLanguage": "th",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)},
    }
    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"อัปโหลด {int(status.progress() * 100)}%")
    vid = response["id"]
    logger.info(f"อัปโหลดสำเร็จ (สถานะ {privacy}): https://studio.youtube.com/video/{vid}/edit")
    return vid


# ──────────────────────────────────────────────────────────
# COMMANDS
# ──────────────────────────────────────────────────────────
def cmd_setup(args):
    """OAuth ครั้งแรกบนเครื่องตัวเอง -> พิมพ์ refresh token ไว้ใส่ GitHub Secrets"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        SCOPES,
    )
    creds = flow.run_local_server(port=0, prompt="consent")
    print("\n=== เก็บค่าเหล่านี้เป็น GitHub Secrets ===")
    print(f"YT_CLIENT_ID={args.client_id}")
    print(f"YT_CLIENT_SECRET={args.client_secret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


def cmd_upload(args):
    file_path = Path(args.file)
    if not file_path.exists():
        logger.error(f"ไม่พบไฟล์ {file_path}")
        sys.exit(1)

    made_for_kids = args.made_for_kids
    if args.title:
        meta = {"title": args.title[:MAX_TITLE], "description": args.description or "", "tags": []}
    else:
        # อ่าน metadata จากไฟล์ .json ที่ video_generator สร้างคู่กันไว้
        meta_path = file_path.with_suffix(".json")
        if not meta_path.exists():
            logger.error(f"ไม่พบ {meta_path.name} และไม่ได้ส่ง --title มา")
            sys.exit(1)
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("story"):
            # โหมดนิทาน: ไม่มีลิงก์ขายของ + ติ๊ก Made for Kids อัตโนมัติ
            meta = build_story_metadata(data["story"])
            made_for_kids = made_for_kids or bool(data.get("made_for_kids", True))
        else:
            meta = build_metadata(data.get("keyword", ""), data.get("script"), data.get("affiliate_product"))

    vid = upload_video(file_path, meta, privacy=args.privacy, made_for_kids=made_for_kids)
    print(vid)


def main():
    ap = argparse.ArgumentParser(description="อัปโหลดวิดีโอขึ้น YouTube (ดีฟอลต์ private)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="ทำ OAuth ครั้งแรก -> ได้ refresh token")
    p_setup.add_argument("--client-id", required=True)
    p_setup.add_argument("--client-secret", required=True)
    p_setup.set_defaults(func=cmd_setup)

    p_up = sub.add_parser("upload", help="อัปโหลดวิดีโอ")
    p_up.add_argument("--file", required=True)
    p_up.add_argument("--title", default=None)
    p_up.add_argument("--description", default="")
    p_up.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p_up.add_argument("--made-for-kids", action="store_true",
                      help="ติ๊ก 'สร้างมาเพื่อเด็ก' (บังคับตามกฎ COPPA สำหรับคอนเทนต์เด็ก)")
    p_up.set_defaults(func=cmd_upload)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
