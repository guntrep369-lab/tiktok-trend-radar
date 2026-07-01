"""
product_catalog.py
==================
ยกระดับจาก 'หมวดสินค้ากว้างๆ' (meme_product_map) เป็น 'สินค้า TikTok Shop ตัวจริง'
พร้อมลิงก์ affiliate + %คอมมิชชั่น เพื่อตอบว่า "ขายตัวไหน ลิงก์อะไร ได้คอมเท่าไหร่"

ทำไมต้องเป็นแคตตาล็อกที่คนคุมเอง:
TikTok Shop ไม่มี public API ให้ดึงลิงก์ affiliate ของครีเอเตอร์รายคน — ลิงก์ต้องไปสร้าง
เองใน affiliate center ดังนั้นไฟล์ data/product_catalog.json คือ 'สมุดสินค้า' ที่คุณคัดเอง
(คีย์เวิร์ด/อารมณ์ -> สินค้าจริง + ลิงก์ + คอม)

โครงสร้าง data/product_catalog.json:
{
  "products": [
    {
      "product_name": "ชื่อสินค้า",
      "affiliate_link": "https://vt.tiktok.com/....",
      "commission_pct": 15,           # optional
      "price": 390,                    # optional
      "match": {"keywords": ["คอลลาเจน"], "moods": ["สวย_แต่งหน้า"]},
      "notes": "..."                   # optional
    }
  ]
}

ถ้าไม่มีไฟล์/ไม่มีสินค้าที่ตรง -> คืน None แล้ว pipeline จะ fallback ไปใช้หมวดกว้างเดิม
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("product_catalog")

CATALOG_PATH = Path(__file__).parent.parent / "data" / "product_catalog.json"


def load_catalog(path: Path = CATALOG_PATH) -> list:
    """อ่านแคตตาล็อกสินค้า (คืน [] ถ้าไม่มีไฟล์/อ่านไม่ได้)"""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"อ่าน product_catalog.json ไม่ได้ ({e}) -> ข้าม")
        return []
    if isinstance(data, dict):
        return data.get("products", [])
    return data if isinstance(data, list) else []


def match_affiliate_product(keyword: str, mood_key: str = None, catalog: list = None) -> dict:
    """
    หา 'สินค้าตัวจริง' ในแคตตาล็อกที่ตรงกับคีย์เวิร์ดมากสุด
    ลำดับความสำคัญ: match คีย์เวิร์ด (นับจำนวน hit) > match อารมณ์ (mood_key)
    คืน dict สินค้า หรือ None ถ้าไม่เจอ
    """
    if catalog is None:
        catalog = load_catalog()
    if not catalog:
        return None

    kw = keyword.lower()

    # 1) จับคู่ด้วยคีย์เวิร์ด (ชนะเสมอถ้ามี) — นับว่าคำใน match.keywords โผล่ในคีย์เวิร์ดกี่คำ
    best, best_score = None, 0
    for p in catalog:
        keys = [k.lower() for k in p.get("match", {}).get("keywords", []) if k]
        score = sum(1 for k in keys if k in kw or kw in k)
        if score > best_score:
            best_score, best = score, p
    if best is not None:
        return best

    # 2) fallback: จับคู่ด้วยอารมณ์ (mood_key) — เอาตัวแรกที่ตรง
    if mood_key:
        for p in catalog:
            if mood_key in p.get("match", {}).get("moods", []):
                return p
    return None
