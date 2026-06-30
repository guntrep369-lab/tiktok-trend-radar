"""
line_notifier.py
================
ส่งข้อความแจ้งเตือนผ่าน LINE Messaging API (แทน LINE Notify ที่ปิดบริการไปแล้วตั้งแต่ 1 เม.ย. 2025)

วิธีตั้งค่า (ทำครั้งเดียว):
1. ไปที่ https://developers.line.biz/console/ -> สร้าง Provider + Channel แบบ "Messaging API"
2. ในหน้า Channel -> แท็บ "Messaging API" -> เลื่อนลงไปออก "Channel access token (long-lived)"
   -> คัดลอกค่านี้ไปเก็บเป็น GitHub Secret ชื่อ LINE_CHANNEL_ACCESS_TOKEN
3. หา "User ID" ของตัวเอง:
   - เพิ่มเพื่อน LINE OA ของตัวเอง (QR code อยู่ในหน้า Channel เดียวกัน)
   - เปิด Webhook (หรือใช้ LINE Official Account Manager -> Settings -> ดู Basic ID)
   - วิธีง่ายสุด: ใช้ LINE Official Account Manager -> เมนู "Settings" -> "Messaging API" -> ดู your user id
     หรือสมัครรับ Webhook event แล้วดู userId จาก event ที่ส่งมาเมื่อเรากดเพิ่มเพื่อน
   -> เก็บเป็น GitHub Secret ชื่อ LINE_USER_ID
4. (Free tier ส่งข้อความได้จำนวนหนึ่งต่อเดือนแบบไม่มีค่าใช้จ่าย ตรวจสอบโควต้าปัจจุบันได้ใน LINE Developers Console)
"""

import os
import logging
import requests

logger = logging.getLogger("line_notifier")

LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"


def send_line_message(message: str) -> bool:
    """
    ส่งข้อความ text ผ่าน LINE Messaging API (Push Message)
    ต้องการ env vars: LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

    คืนค่า True ถ้าส่งสำเร็จ, False ถ้าไม่สำเร็จ (ไม่ throw exception
    เพื่อไม่ให้ทั้ง pipeline ล่มแค่เพราะแจ้งเตือนไม่ได้)
    """
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not token or not user_id:
        logger.warning(
            "ไม่พบ LINE_CHANNEL_ACCESS_TOKEN หรือ LINE_USER_ID ใน environment "
            "-> ข้ามการแจ้งเตือน (ตั้งค่าใน GitHub Secrets เพื่อเปิดใช้งาน)"
        )
        return False

    # LINE Messaging API จำกัดความยาวข้อความ text ที่ 5000 ตัวอักษรต่อ message object
    if len(message) > 4900:
        message = message[:4880] + "\n... (ตัดข้อความ เนื่องจากยาวเกินลิมิต)"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }

    try:
        resp = requests.post(LINE_PUSH_API, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("ส่ง LINE message สำเร็จ")
            return True
        else:
            logger.error(f"LINE API ตอบกลับ status {resp.status_code}: {resp.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"ส่ง LINE message ล้มเหลว: {e}")
        return False


def format_alert_message(alerts: list, suggestions: dict = None) -> str:
    """
    แปลงลิสต์ของ trend ที่ momentum สูง ให้เป็นข้อความสำหรับส่งใน LINE
    alerts = [{"keyword": ..., "momentum_score": ..., "label": ..., "current_score": ...}, ...]
    suggestions = ผลจาก keyword discovery (optional) ไว้แนบท้ายเป็น "คำใหม่น่าจับตา"
    """
    if not alerts:
        return ""

    lines = ["🔥 TikTok Trend Radar — พบกระแสน่าจับตา!", ""]
    for a in alerts:
        lines.append(f"🔑 {a['keyword']}")
        lines.append(f"   {a['label_display']}")
        lines.append(f"   Score: {a['current_score']} | Momentum: {a['momentum_score']}")
        # พยากรณ์อายุที่เหลือ (โชว์เฉพาะเมื่อ fit ผ่าน)
        dr = a.get("days_remaining")
        if dr is not None:
            lines.append(f"   ⏳ คาดว่าเหลืออีก ~{dr:.1f} วัน ก่อนกระแสตก")
        # แนบหมวดสินค้าที่ควรขาย (จาก Meme-Product Matching)
        if a.get("product_suggestion"):
            ps = a["product_suggestion"]
            lines.append(f"   🛒 อารมณ์: {ps['mood_display']}")
            lines.append(f"   💰 ขายคู่กับ: {ps['products'][0]}")
            if len(ps["products"]) > 1:
                lines.append(f"      (หรือ: {ps['products'][1]})")
        lines.append("")

    lines.append("⏰ จังหวะทอง! รีบทำคอนเทนต์ภายใน 3 ชม. ก่อนกระแสหาย")

    # แนบ "คำใหม่น่าจับตา" จาก keyword discovery (โชว์แค่ 5 คำแรกกันข้อความยาว)
    trending_new = (suggestions or {}).get("trending_today", [])
    if trending_new:
        lines.append("")
        lines.append("🔎 คำใหม่มาแรงวันนี้ (พิจารณาเพิ่มเข้า config):")
        for w in trending_new[:5]:
            lines.append(f"   • {w}")

    return "\n".join(lines)
