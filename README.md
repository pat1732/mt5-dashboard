# 📈 MT5 Trade Logger + Dashboard

เก็บข้อมูลเทรดจาก MT5 และแสดง Dashboard บน Web

## 🏗️ Architecture

```
MT5 → Python Listener → Supabase ← Streamlit Dashboard
                         ↓
                   Telegram Alert
```

## 📦 สิ่งที่ได้

- ✅ เก็บข้อมูลเทรดอัตโนมัติจาก MT5
- ✅ Dashboard แสดงกำไร/ขาดทุน, Equity Curve, Win Rate
- ✅ Alert ไป Telegram ทุกครั้งที่เทรด
- ✅ ดูได้จากทุกที่ผ่าน Browser

## 🚀 Quick Start

### 1. ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

### 2. แก้ไข config.yaml

ใส่ Supabase URL/Key, Telegram Token, MT5 Login

### 3. รัน Listener

```bash
python mt5_listener.py
```

### 4. เปิด Dashboard

```bash
streamlit run dashboard.py
```

## 📁 Files

| File | Description |
|------|-------------|
| `config.yaml` | Configuration |
| `mt5_listener.py` | MT5 Listener + Supabase + Telegram |
| `dashboard.py` | Streamlit Dashboard |
| `requirements.txt` | Python Dependencies |
| `SETUP.md` | คู่มือตั้งค่าฉบับสมบูรณ์ |

## 🛠️ Tech Stack

- **MT5**: MetaTrader 5
- **Database**: Supabase (PostgreSQL)
- **Dashboard**: Streamlit + Plotly
- **Alert**: Telegram Bot

## 📝 License

MIT
