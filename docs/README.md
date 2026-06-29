# 📊 Dashboard — วิธีเปิดใช้งานบน GitHub Pages

Dashboard หน้าเว็บที่โชว์ผล Trend Radar แบบเรียลไทม์ ฟรี 100% โฮสต์บน GitHub Pages

## หน้าตา
- การ์ดคีย์เวิร์ดสีตามเฟส (เขียว=พุ่ง, เหลือง=พีค, แดง=ดับ, ฟ้า=เกิด, เทา=นิ่ง)
- แถบสรุปจำนวนแต่ละเฟส + ปุ่มกรอง
- velocity/acceleration + หมวดสินค้าที่ควรขายของแต่ละคำ
- อัปเดตอัตโนมัติทุก 3 ชม. ตามรอบที่ระบบรัน

---

## วิธีเปิดใช้งาน (ทำครั้งเดียว)

### Step 1 — push โค้ดที่มี docs/ ขึ้น GitHub แล้ว
(ไฟล์ dashboard อยู่ในโฟลเดอร์ `docs/` เรียบร้อย)

### Step 2 — เปิด GitHub Pages
1. เข้า repo บน GitHub → แท็บ **Settings**
2. เมนูซ้าย → **Pages**
3. หัวข้อ **Build and deployment** → **Source** เลือก **Deploy from a branch**
4. **Branch** เลือก `main` → โฟลเดอร์เลือก **`/docs`** → กด **Save**
5. รอ 1-2 นาที GitHub จะ build ให้ แล้วโชว์ลิงก์ด้านบนว่า
   `Your site is live at https://<username>.github.io/tiktok-trend-radar/`

### Step 3 — เปิดดู
เข้าลิงก์ที่ได้ → เห็น dashboard ทันที

> ครั้งแรกถ้ายังไม่มีข้อมูล จะขึ้น "ยังไม่มีข้อมูล" — ให้รอ workflow รอบถัดไป
> หรือสั่ง `gh workflow run "TikTok Trend Radar"` แล้ว `git pull` ให้ไฟล์ `docs/latest.json` มาอยู่ใน repo

---

## ข้อมูลอัปเดตยังไง

ทุกครั้งที่ระบบ radar รัน (ทุก 3 ชม.) มันจะ:
1. เขียนผลลง `docs/latest.json`
2. workflow commit ไฟล์นี้กลับเข้า repo อัตโนมัติ
3. GitHub Pages เสิร์ฟไฟล์ใหม่ → dashboard อัปเดตเอง

dashboard ยังรีเฟรชตัวเองทุก 5 นาทีในเบราว์เซอร์ (เผื่อมีข้อมูลใหม่)

---

## ปรับแต่ง

- **สี/ธีม**: แก้ตัวแปร CSS ใน `docs/index.html` ส่วน `:root { ... }`
- **ความถี่รีเฟรช**: แก้บรรทัดท้ายสุด `setInterval(load, 5 * 60 * 1000)` (หน่วยมิลลิวินาที)

---

## ⚠️ หมายเหตุ
- ถ้า repo เป็น **private** GitHub Pages จะใช้ได้เฉพาะ GitHub Pro/Team ขึ้นไป
  (ถ้าใช้ฟรีและ repo เป็น private ต้องเปลี่ยน repo เป็น public ก่อนถึงจะเปิด Pages ได้)
- ลิงก์ dashboard จะเป็นสาธารณะ ใครมีลิงก์ก็เข้าดูได้ (แต่เดาลิงก์ยาก) — อย่าใส่ข้อมูลลับใน dashboard
