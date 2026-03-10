"""
MT5 Trade Logger - เก็บข้อมูลเทรดจาก MT5 ไป Firebase + Telegram Alert
"""
import MetaTrader5 as mt5
import yaml
import logging
import time
import json
from datetime import datetime
from pathlib import Path

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load Config
def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

config = load_config()

# Initialize Firebase
def init_firebase():
    """เชื่อมต่อ Firebase Firestore"""
    import firebase_admin
    from firebase_admin import credentials
    
    firebase_config = config.get('firebase_config', {})
    
    # วิธีที่ 1: ใช้ Service Account JSON file
    service_account_path = firebase_config.get('service_account_path')
    
    if service_account_path and Path(service_account_path).exists():
        cred = credentials.Certificate(service_account_path)
    else:
        # วิธีที่ 2: สราง credentials จาก config
        cred_dict = {
            "type": "service_account",
            "project_id": firebase_config.get('project_id'),
            "private_key_id": "dummy",  # ถ้าใช้วิธีนี้ ต้องใส่ real key
            "private_key": "-----BEGIN PRIVATE KEY-----\nDUMMY\n-----END PRIVATE KEY-----\n",
            "client_email": f"{firebase_config.get('project_id')}@appspot.gserviceaccount.com",
            "client_id": "dummy",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        # สำหรับ simple setup ใช้วิธีนี้จะไม่ work แนะนำใช้วิธีที่ 1
        logger.warning("Using dummy credentials - please set service_account_path!")
        return None
    
    # Initialize Firebase app
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(cred)
    
    from firebase_admin import firestore
    db = firestore.client()
    return db

# Track open deals
open_deals = {}

def send_telegram_alert(trade_info):
    """ส่ง Telegram Alert"""
    import requests
    
    message = f"🔔 *Trade Alert*\n\n"
    message += f"📊 *{trade_info['symbol']}*\n"
    message += f"📈 Type: {trade_info['type']}\n"
    message += f"📦 Volume: {trade_info['volume']}\n"
    message += f"💰 Price: {trade_info['price']}\n"
    
    if 'profit' in trade_info:
        message += f"💵 Profit: ${trade_info['profit']:.2f}\n"
    
    message += f"⏰ Time: {trade_info['time']}"
    
    url = f"https://api.telegram.org/bot{config['telegram_bot_token']}/sendMessage"
    data = {
        'chat_id': config['telegram_chat_id'],
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        requests.post(url, json=data)
    except Exception as e:
        logger.error(f"Telegram Error: {e}")

def save_to_firebase(trade_info, db):
    """บันทึกข้อมูลไป Firebase Firestore"""
    
    try:
        # Collection: 'trades'
        # Document: ticket number
        doc_ref = db.collection('trades').document(str(trade_info['ticket']))
        
        data = {
            'ticket': trade_info['ticket'],
            'symbol': trade_info['symbol'],
            'type': trade_info['type'],
            'volume': trade_info['volume'],
            'open_price': trade_info.get('open_price'),
            'open_time': trade_info.get('open_time'),
            'close_price': trade_info.get('close_price'),
            'close_time': trade_info.get('close_time'),
            'profit': trade_info.get('profit'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Set document (upsert)
        doc_ref.set(data, merge=True)
        
        logger.info(f"✅ Saved to Firebase: {trade_info['symbol']} {trade_info['type']}")
        
        # Send Telegram Alert
        send_telegram_alert(trade_info)
        
    except Exception as e:
        logger.error(f"Firebase Error: {e}")

def process_deals(db):
    """ตรวจสอบ Deals ที่เปิด/ปิด"""
    if not mt5.initialize():
        logger.error(f"MT5 Initialize failed: {mt5.last_error()}")
        return
    
    # Get all deals from history
    from datetime import datetime, timedelta
    
    # Get deals from last 7 days
    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)
    
    deals = mt5.history_deals_get(from_date, to_date)
    
    if deals is None or len(deals) == 0:
        return
    
    for deal in deals:
        ticket = deal.ticket
        
        # Filter by symbols if specified
        if config.get('symbols') and deal.symbol not in config['symbols']:
            continue
        
        # Check if deal is in open positions or history
        # Deal with position_id = 0 means it's a deal entry/exit
        
        # Get position info
        positions = mt5.positions_get(ticket=ticket)
        
        if len(positions) == 0:
            # Position is closed - this is a CLOSE event
            # Get the open deal info from Firestore
            try:
                doc_ref = db.collection('trades').document(str(ticket))
                doc = doc_ref.get()
                
                if doc.exists:
                    open_data = doc.to_dict()
                    
                    # Prepare close info
                    close_info = {
                        'ticket': ticket,
                        'symbol': deal.symbol,
                        'type': 'CLOSE',
                        'volume': deal.volume,
                        'price': deal.price,
                        'close_price': deal.price,
                        'close_time': datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                        'profit': deal.profit,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    # Update in Firebase
                    save_to_firebase(close_info, db)
                    
            except Exception as e:
                logger.error(f"Error processing close: {e}")
        else:
            # Position is open - this is an OPEN event
            # Check if already saved
            try:
                doc_ref = db.collection('trades').document(str(ticket))
                doc = doc_ref.get()
                
                if not doc.exists:
                    # New position - save it
                    open_info = {
                        'ticket': ticket,
                        'symbol': deal.symbol,
                        'type': 'BUY' if deal.type == 0 else 'SELL',
                        'volume': deal.volume,
                        'open_price': deal.price,
                        'open_time': datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S'),
                        'price': deal.price,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    save_to_firebase(open_info, db)
                    
            except Exception as e:
                logger.error(f"Error processing open: {e}")

def main():
    """Main loop"""
    logger.info("🚀 Starting MT5 Trade Logger with Firebase...")
    
    # Initialize Firebase
    db = init_firebase()
    if db is None:
        logger.error("❌ Firebase initialization failed!")
        return
    
    logger.info("✅ Firebase Connected")
    
    # Initialize MT5
    mt5_config = config.get('mt5', {})
    
    if not mt5.initialize(
        login=mt5_config.get('login'),
        password=mt5_config.get('password'),
        server=mt5_config.get('server')
    ):
        logger.error(f"MT5 Initialize failed: {mt5.last_error()}")
        return
    
    account_info = mt5.account_info()
    logger.info(f"✅ MT5 Connected: {account_info.login}")
    
    # Main loop
    check_interval = config.get('check_interval', 5)
    
    try:
        while True:
            process_deals(db)
            time.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("🛑 Stopping MT5 Trade Logger...")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
