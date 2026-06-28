# 📊 TikTok Trend Radar

ระบบติดตามกระแส (Meme Lifecycle) อัตโนมัติ — ดึงข้อมูล Google Trends ทุก 3 ชั่วโมง
คำนวณ Velocity/Acceleration แล้วแจ้งเตือนผ่าน LINE เมื่อเจอกระแสที่กำลังพุ่งแรง

รันทั้งหมดฟรีบน **GitHub Actions** ไม่ต้องมีเซิร์ฟเวอร์ของตัวเอง

---

## 🗂️ โครงสร้างโปรเจกต์

```
tiktok-trend-radar/
├── .github/workflows/trend_radar.yml   <- ตัวสั่งให้รันอัตโนมัติทุก 3 ชม.
├── config.json                          <- รายชื่อคีย์เวิร์ดที่ต้องการติดตาม (แก้ไขได้เลย)
├── requirements.txt
├── scripts/
│   ├── trend_engine.py                  <- ดึงข้อมูล + คำนวณ velocity/acceleration
│   ├── line_notifier.py                 <- ส่งแจ้งเตือนผ่าน LINE Messaging API
│   └── run_radar.py                     <- ตัวรันหลัก (orchestrator)
└── data/
    ├── history.csv                       <- ประวัติสะสมทุกรอบ (auto-generate)
    └── latest.json                       <- สแนปช็อตล่าสุด (auto-generate)
```

---

## 🚀 ขั้นตอนติดตั้ง (ทำครั้งเดียว)

### Step 1 — สร้าง GitHub Repository

1. สร้าง repo ใหม่บน GitHub (public หรือ private ก็ได้) เช่น `tiktok-trend-radar`
2. อัปโหลดไฟล์ทั้งหมดในโฟลเดอร์นี้เข้า repo (หรือ clone แล้ว copy ไฟล์เข้าไป)

```bash
git init
git add .
git commit -m "initial commit: tiktok trend radar"
git remote add origin https://github.com/<username>/tiktok-trend-radar.git
git push -u origin main
```

### Step 2 — สร้าง LINE Official Account + Messaging API

> ⚠️ **หมายเหตุสำคัญ:** LINE Notify ปิดให้บริการไปแล้วตั้งแต่ 1 เม.ย. 2025
> ระบบนี้ใช้ **LINE Messaging API** แทน ซึ่งทำงานคล้ายกันแต่ตั้งค่าเพิ่มอีกเล็กน้อย

1. ไปที่ [LINE Developers Console](https://developers.line.biz/console/)
2. สร้าง **Provider** ใหม่ (ถ้ายังไม่มี)
3. สร้าง **Channel** แบบ "Messaging API"
4. ในหน้า Channel settings:
   - แท็บ **Messaging API** → เลื่อนหา **Channel access token (long-lived)** → กด Issue → คัดลอกค่านี้เก็บไว้
   - แท็บ **Basic settings** → จะมี QR Code ของ LINE OA ตัวเอง → **สแกนเพิ่มเพื่อนด้วย LINE ของตัวเอง**
5. หา **User ID** ของตัวเอง (ปลายทางที่จะรับข้อความ):
   - วิธีง่ายที่สุด: เปิด [LINE Official Account Manager](https://manager.line.biz/) → เลือก OA ของคุณ → Settings → Messaging API → จะเห็น User ID ของแอดมิน
   - หรือเปิด Webhook รับ event แล้วดู `userId` จาก event ที่ส่งมาเมื่อมีคนกดเพิ่มเพื่อน (ขั้นนี้ซับซ้อนกว่า ใช้วิธีแรกง่ายกว่า)

### Step 3 — เก็บ Token ไว้ใน GitHub Secrets

ใน repo → **Settings → Secrets and variables → Actions → New repository secret**

เพิ่ม 2 ค่า:
| Secret name | ค่าที่ใส่ |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | token ที่คัดลอกจาก Step 2 |
| `LINE_USER_ID` | User ID ที่หาได้จาก Step 2 |

### Step 4 — แก้ไขคีย์เวิร์ดที่ต้องการติดตาม

เปิดไฟล์ `config.json` แก้ `keyword_batches` เป็นคำที่ต้องการ (สูงสุด **5 คำต่อ batch** ตามข้อจำกัดของ Google Trends):

```json
{
  "keyword_batches": [
    ["คำที่1", "คำที่2", "คำที่3"],
    ["คำที่4", "คำที่5"]
  ],
  "momentum_alert_threshold": 1.5
}
```

`momentum_alert_threshold` คือค่าที่ใช้ตัดสินว่ากระแส "แรงพอจะแจ้งเตือน" — ปรับขึ้น/ลงได้ตามที่เหมาะกับข้อมูลจริงที่เจอ

### Step 5 — เปิดใช้งาน Actions

1. ไปที่แท็บ **Actions** ของ repo → ถ้ามีข้อความให้กด enable ก็กดยืนยัน
2. ระบบจะรันอัตโนมัติทุก 3 ชั่วโมงตามที่ตั้งไว้ใน workflow
3. ทดสอบรันด้วยตัวเองได้ทันทีโดยไปที่ **Actions → TikTok Trend Radar → Run workflow**

---

## 🧪 ทดสอบบนเครื่องตัวเองก่อน push

```bash
pip install -r requirements.txt

# โหมดจำลองข้อมูล (ไม่ยิง Google Trends จริง เหมาะกับทดสอบ logic)
python scripts/run_radar.py --mode simulate

# โหมดจริง (ดึงจาก Google Trends จริง)
python scripts/run_radar.py --mode live
```

ถ้าต้องการทดสอบการส่ง LINE บนเครื่องตัวเอง ให้ set environment variable ก่อนรัน:
```bash
export LINE_CHANNEL_ACCESS_TOKEN="your_token_here"
export LINE_USER_ID="your_user_id_here"
python scripts/run_radar.py --mode simulate
```

---

## ⚠️ ข้อจำกัดที่ควรรู้

- **Google Trends ไม่มี Official API** — `pytrends` เป็นไลบรารี unofficial ที่ scrape หน้าเว็บ ถ้า Google เปลี่ยนโครงสร้างเว็บหรือบล็อก IP ของ GitHub Actions runner อาจดึงข้อมูลไม่ได้เป็นบางครั้ง (ระบบมี retry + fallback เป็น simulate mode ไว้แล้วเพื่อไม่ให้ pipeline ล่ม)
- **จำกัด 5 คีย์เวิร์ดต่อ batch** ตามข้อจำกัดของ Google Trends compare endpoint
- **LINE Messaging API free tier** มีโควต้าข้อความฟรีต่อเดือนจำนวนหนึ่ง ควรเช็คโควต้าปัจจุบันใน LINE Developers Console ถ้าจะส่งถี่มาก
- **เวลาที่ GitHub Actions cron รันจริง** อาจคลาดเคลื่อนจากเวลาที่ตั้งไว้ไม่กี่นาทีในช่วงที่ GitHub มีโหลดสูง (เป็นเรื่องปกติของ free scheduled workflow)

## 📈 การต่อยอด

- ปรับ `momentum_alert_threshold` ตามข้อมูลจริงที่สะสมได้ใน `data/history.csv`
- เพิ่ม batch คีย์เวิร์ดได้เรื่อยๆ (แต่ยิ่งมาก ยิ่งเสี่ยงโดน rate limit จาก Google — แนะนำไม่เกิน 4-5 batch ต่อรอบ)
- เปิดไฟล์ `data/history.csv` ด้วย Excel/Google Sheets เพื่อดู pattern ย้อนหลังและ fine-tune threshold
