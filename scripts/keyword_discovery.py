"""
keyword_discovery.py
====================
ค้นหา "คีย์เวิร์ดใหม่ที่กำลังมา" โดยอัตโนมัติ เพื่อแก้จุดอ่อนที่ระบบเดิม
จับได้แค่คำที่ตั้งไว้ล่วงหน้าใน config

2 วิธี:
1. trending_searches  -> ดึงคำค้นหาที่ฮิตรายวันของไทย (ภาพรวมทั้งประเทศ)
2. suggestions        -> ขยายจากคีย์เวิร์ดที่ติดตามอยู่ หาคำใกล้เคียงที่คนค้น

ผลลัพธ์ = รายการ "คำที่น่าสนใจ" ไว้เสนอให้คนตัดสินใจเพิ่มเข้า config เอง
(ไม่เพิ่มอัตโนมัติ เพราะคำฮิตรายวันส่วนใหญ่เป็นข่าว/ดารา ไม่เกี่ยวสินค้า
คนต้องคัดกรองเองว่าคำไหนเอามาทำ affiliate ได้)
"""

import time
import logging

logger = logging.getLogger("keyword_discovery")


def get_trending_searches(geo: str = "thailand", limit: int = 20) -> list:
    """
    ดึงคำค้นหาฮิตรายวันของไทยจาก Google Trends
    คืนเป็น list ของคำ (string)

    หมายเหตุ: geo ของ method นี้ใช้ชื่อประเทศเต็มตัวพิมพ์เล็ก เช่น "thailand"
    ไม่ใช่รหัส 2 ตัวอักษร "TH" แบบ method อื่น
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.error("ยังไม่ได้ติดตั้ง pytrends")
        return []

    try:
        pytrends = TrendReq(hl="th-TH", tz=420)
        df = pytrends.trending_searches(pn=geo)
        if df is None or df.empty:
            logger.warning("ไม่มีข้อมูล trending searches")
            return []
        # df เป็น DataFrame คอลัมน์เดียว แปลงเป็น list
        words = df[0].tolist()[:limit]
        return [str(w) for w in words]
    except Exception as e:
        logger.warning(f"ดึง trending searches ไม่สำเร็จ: {e}")
        return []


def get_related_suggestions(keyword: str, limit: int = 5) -> list:
    """
    ขยายจากคีย์เวิร์ดที่มี -> หาคำใกล้เคียงที่ Google แนะนำ
    เช่น "คอลลาเจน" -> ["คอลลาเจนยี่ห้อไหนดี", "คอลลาเจนเปปไทด์", ...]
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return []

    try:
        pytrends = TrendReq(hl="th-TH", tz=420)
        suggestions = pytrends.suggestions(keyword=keyword)
        # suggestions คืน list ของ dict ที่มี key 'title'
        titles = [s.get("title", "") for s in suggestions if s.get("title")]
        # ตัดตัวที่ซ้ำกับคำตั้งต้นออก
        titles = [t for t in titles if t.lower() != keyword.lower()]
        return titles[:limit]
    except Exception as e:
        logger.warning(f"ดึง suggestions ของ '{keyword}' ไม่สำเร็จ: {e}")
        return []


def discover_keywords(existing_keywords: list, sleep_between: float = 2.0) -> dict:
    """
    รวมผลการค้นหาคำใหม่ทั้ง 2 วิธี

    existing_keywords = คำที่ติดตามอยู่แล้ว (เอาไว้คัดออก ไม่เสนอซ้ำ)

    คืน dict:
    {
      "trending_today": [...],          # คำฮิตรายวันของไทย (ทั้งหมด ไม่กรอง)
      "related": {"คอลลาเจน": [...], ...}  # คำใกล้เคียงจากคำที่มี
    }
    """
    existing_lower = {k.lower() for k in existing_keywords}

    # 1. คำฮิตรายวัน
    trending = get_trending_searches()
    # คัดคำที่ติดตามอยู่แล้วออก
    trending_new = [w for w in trending if w.lower() not in existing_lower]

    time.sleep(sleep_between)

    # 2. คำใกล้เคียงจากคีย์เวิร์ดที่มี (เอาแค่ 3 คำแรกกัน rate limit)
    related = {}
    for kw in existing_keywords[:3]:
        sug = get_related_suggestions(kw)
        sug_new = [s for s in sug if s.lower() not in existing_lower]
        if sug_new:
            related[kw] = sug_new
        time.sleep(sleep_between)

    return {
        "trending_today": trending_new,
        "related": related,
    }
