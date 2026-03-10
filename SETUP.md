# MT5 Trade Logger - Firebase Setup Guide

## 📋 Prerequisites

1. **MT5 Account** - บัญชี MT5 ที่ใช้เทรด
2. **Firebase Account** - สมัครฟรีที่ https://console.firebase.google.com
3. **Telegram Account** - สำหรับรับ Alert

---

## 🚀 Step 1: ตั้งค่า Firebase

### 1.1 สร้าง Firebase Project

1. ไปที่ https://console.firebase.google.com
2. คลิก **Add project**
3. กรอกชื่อ Project: `mt5-trading` (หรือชื่ออื่น)
4. ปิด Google Analytics (ไม่จำเป็น)
5. คลิก **Create project** รอประมาณ 1 นาที

### 1.2 เปิดใช้งาน Firestore

1. ใน Firebase Console ไปที่ **Build** → **Firestore Database**
2. คลิก **Create database**
3. เลือก **Start in test mode** (อนุญาตให้อ่านเขียนได้เลย สำหรับ dev)
4. เลือก Region: `asia-southeast1` (Singapore)
5. คลิก **Done**

### 1.3 รับ Service Account Key

1. ไปที่ **Project Settings** (รูปเฟือง)
2. เลือก **Service Accounts**
3. คลิก **Generate new private key**
4. จะดาวน์โหลดไฟล์ `.json` มา → ตั้งชื่อเป็น `serviceAccountKey.json`
5. **เก็บไฟล์นี้ไว้ในโฟลเดอร์โปรเจค** (mt5-trade-logger/)

---

## 📱 Step 2: ตั้งค่า Telegram Bot

### 2.1 สร้าง Bot

1. เปิด Telegram และค้นหา **@BotFather**
2. ส่งคำสั่ง `/newbot`
3. ตั้งชื่อ Bot (เช่น `MT5TradeAlert`)
4. ตั้ง Username (ลงท้ายด้วย `bot`, เช่น `mt5_trade_alert_bot`)
5. รับ **Bot Token** ที่ได้มา

### 2.2 หา Chat ID

1. เปิด Bot ที่สร้าง
2. ส่งคำสั่ง `/start`
3. ไปที่ `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. หา `chat` → `id` คือ Chat ID ของคุณ

---

## 💻 Step 3: ตั้งค่า Local Computer

### 3.1 ติดตั้ง Python

```bash
# ตรวจสอบ Python
python --version
```

ถ้ายังไม่มี ดาวน์โหลดที่ https://python.org

### 3.2 ติดตั้ง Dependencies

```bash
cd mt5-trade-logger
pip install -r requirements.txt
```

### 3.3 ใส่ Service Account Key

1. ย้ายไฟล์ `serviceAccountKey.json` ที่ดาวน์โหลดมา ไปไว้ในโฟลเดอร์ `mt5-trade-logger/`

### 3.4 แก้ไข config.yaml

เปิด `config.yaml` และใส่ค่าต่างๆ:

```yaml
firebase_config:
  service_account_path: "serviceAccountKey.json"

telegram_bot_token: "YOUR_BOT_TOKEN"
telegram_chat_id: "YOUR_CHAT_ID"

mt5_login: 12345678
mt5_password: "YOUR_MT5_PASSWORD"
mt5_server: "YourBroker-Server"

check_interval: 5
symbols: ["XAUUSD", "EURUSD"]
```

### 3.5 รัน Listener

```bash
python mt5_listener.py
```

ถ้าขึ้นแบบนี้ = สำเร็จ:
```
✅ Firebase Connected
✅ MT5 Connected: 12345678
🚀 Starting MT5 Trade Logger with Firebase...
```

---

## ☁️ Step 4: Deploy Dashboard ขึ้น Cloud

### 4.1 Upload โค้ดขึ้น GitHub

1. สร้าง GitHub Repository ใหม่
2. Push โค้ดทั้งหมด (รวม `serviceAccountKey.json` ใน .gitignore!)
3. **ห้าม push ไฟล์ `serviceAccountKey.json`** ให้ใส่ใน .gitignore

### 4.2 Deploy บน Streamlit Cloud

1. ไปที่ https://share.streamlit.io
2. Login ด้วย GitHub
3. คลิก **New app**
4. เลือก Repository, Branch, Main file path: `dashboard.py`
5. **สำคัญ**: ใน Settings → Secrets ให้ใส่ Firebase credentials:

```toml
# ใส่ content ของ serviceAccountKey.json
[secrets]
firebase = '{"type": "service_account", "project_id": "...", ...}'
```

6. คลิก **Deploy**

---

## ✅ ทดสอบ

1. **Listener**: รัน `python mt5_listener.py` ทิ้งไว้
2. **เทรด**: เปิด MT5 แล้วเทรดจริง
3. **Firebase**: ไปที่ Firestore Console จะเห็น Collection `trades`
4. **Telegram**: จะได้รับ Alert ทันที
5. **Dashboard**: เข้า URL ของ Streamlit จะเห็นข้อมูล

---

## 🔧 Troubleshooting

### Firebase เชื่อมไม่ได้
- ตรวจสอบ `serviceAccountKey.json` ถูกต้องหรือไม่
- ตรวจสอบว่า Firestore Database ถูกสร้างแล้ว

### MT5 เชื่อมไม่ได้
- ตรวจสอบ Login, Password, Server ถูกต้องหรือไม่

### Dashboard ไม่แสดงข้อมูล
- ตรวจสอบ Secrets ใน Streamlit Cloud
- ตรวจสอบ Firestore ว่ามีข้อมูลหรือไม่

---

## 📞 ติดต่อ

ถ้ามีปัญหา ส่งข้อความมาถามได้เลยค่ะ! 🚀
