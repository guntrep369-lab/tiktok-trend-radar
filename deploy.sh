#!/bin/bash
set -e

# ============================================================
# Deploy Script: TikTok Trend Radar -> GitHub
# ============================================================
# วิธีใช้:
#   1. แตกไฟล์ tiktok-trend-radar.zip ก่อน (ถ้ายังไม่แตก)
#   2. cd เข้าไปในโฟลเดอร์ tiktok-trend-radar
#   3. copy ไฟล์ deploy.sh นี้ไปไว้ในโฟลเดอร์เดียวกัน (ระดับเดียวกับ config.json)
#   4. รัน: bash deploy.sh
#
# สิ่งที่สคริปต์นี้จะทำ:
#   - เช็คว่า login gh แล้วหรือยัง
#   - สร้าง git repo ในเครื่อง + commit ไฟล์ทั้งหมด
#   - สร้าง GitHub repository แบบ Private ผ่าน gh CLI
#   - Push โค้ดขึ้น GitHub
#   - ตั้งค่า GitHub Secrets (LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID)
#     โดยจะถามให้คุณพิมพ์ค่าตอนรัน (ไม่ฝังไว้ในไฟล์นี้ เพื่อความปลอดภัย)
# ============================================================

REPO_NAME="tiktok-trend-radar"

echo "🔍 เช็คว่า gh CLI login แล้วหรือยัง..."
if ! gh auth status &>/dev/null; then
    echo "❌ ยังไม่ได้ login gh CLI"
    echo "   กรุณารัน: gh auth login"
    echo "   แล้วค่อยรันสคริปต์นี้ใหม่"
    exit 1
fi
echo "✅ gh CLI login เรียบร้อย"
echo ""

# ── ตรวจว่ากำลังอยู่ในโฟลเดอร์โปรเจกต์ถูกต้อง ──
if [ ! -f "config.json" ] || [ ! -d "scripts" ]; then
    echo "❌ ไม่พบ config.json หรือโฟลเดอร์ scripts/"
    echo "   กรุณา cd เข้าไปในโฟลเดอร์ tiktok-trend-radar ก่อนรันสคริปต์นี้"
    exit 1
fi

# ── Step 1: Init git repo (ถ้ายังไม่มี) ──
if [ ! -d ".git" ]; then
    echo "📦 กำลังสร้าง git repository ในเครื่อง..."
    git init -b main
    git add .
    git commit -m "initial commit: tiktok trend radar"
    echo "✅ สร้าง git repo ในเครื่องเรียบร้อย"
else
    echo "ℹ️  พบ git repo อยู่แล้วในโฟลเดอร์นี้ -> ข้ามขั้นตอน init"
fi
echo ""

# ── Step 2: สร้าง GitHub repo (private) + push ──
echo "🚀 กำลังสร้าง GitHub repository (private) ชื่อ: $REPO_NAME ..."
if gh repo view "$REPO_NAME" &>/dev/null; then
    echo "ℹ️  พบ repo ชื่อ $REPO_NAME อยู่แล้วบน GitHub ของคุณ -> ข้ามการสร้างใหม่ จะ push เข้า repo เดิม"
    REPO_FULL_NAME=$(gh repo view "$REPO_NAME" --json nameWithOwner -q .nameWithOwner)
    git remote remove origin 2>/dev/null || true
    git remote add origin "https://github.com/${REPO_FULL_NAME}.git"
else
    gh repo create "$REPO_NAME" --private --source=. --remote=origin
    echo "✅ สร้าง GitHub repository เรียบร้อย (private)"
fi
echo ""

echo "⬆️  กำลัง push โค้ดขึ้น GitHub..."
git push -u origin main
echo "✅ push โค้ดเรียบร้อย"
echo ""

# ── Step 3: ตั้งค่า GitHub Secrets ──
echo "🔐 ตอนนี้จะตั้งค่า LINE Secrets"
echo "   (ค่าที่พิมพ์จะไม่ถูกบันทึกไว้ในไฟล์นี้ และจะไม่แสดงผลซ้ำบนหน้าจอ)"
echo ""

read -rsp "วาง LINE_CHANNEL_ACCESS_TOKEN แล้วกด Enter: " LINE_TOKEN
echo ""
read -rsp "วาง LINE_USER_ID แล้วกด Enter: " LINE_UID
echo ""

if [ -z "$LINE_TOKEN" ] || [ -z "$LINE_UID" ]; then
    echo "⚠️  ไม่ได้ใส่ค่าใดค่าหนึ่ง -> ข้ามการตั้ง secret (ไปตั้งทีหลังได้ผ่านหน้าเว็บ Settings > Secrets)"
else
    gh secret set LINE_CHANNEL_ACCESS_TOKEN --body "$LINE_TOKEN"
    gh secret set LINE_USER_ID --body "$LINE_UID"
    echo "✅ ตั้งค่า GitHub Secrets เรียบร้อยทั้ง 2 ตัว"
fi

# ล้างค่าออกจาก memory ของ shell session
unset LINE_TOKEN
unset LINE_UID

echo ""
echo "============================================================"
echo "🎉 เสร็จสมบูรณ์!"
echo "============================================================"
REPO_URL=$(gh repo view "$REPO_NAME" --json url -q .url)
echo "📍 Repo: $REPO_URL"
echo ""
echo "ขั้นต่อไป:"
echo "  1. เปิด $REPO_URL/actions"
echo "  2. คลิก workflow ชื่อ 'TikTok Trend Radar'"
echo "  3. กดปุ่ม 'Run workflow' เพื่อทดสอบรันครั้งแรกแบบ manual"
echo "  4. ถ้าผ่าน ระบบจะรันอัตโนมัติทุก 3 ชั่วโมงตามที่ตั้งไว้"
echo "============================================================"
