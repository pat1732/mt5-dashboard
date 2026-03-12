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

def save_account_info(db, account):
    """บันทึกข้อมูล Account Info ไป Firebase"""
    try:
        doc_ref = db.collection('bot_status').document('status')
        
        # Get current start_time if exists
        existing = doc_ref.get()
        start_time = None
        if existing.exists:
            start_time = existing.to_dict().get('start_time')
        
        # Use first login time as start_time (for uptime calculation)
        if start_time is None:
            start_time = int(datetime.now().timestamp())
        
        # Calculate equity = balance + profit (floating)
        equity = account.balance + account.profit
        margin = account.margin
        free_margin = account.margin_free
        
        data = {
            'balance': account.balance,
            'equity': equity,
            'floating_pl': account.profit,
            'margin': margin,
            'free_margin': free_margin,
            'ea_running': True,
            'start_time': start_time,
            'login': account.login,
            'server': account.server,
            'updated_at': datetime.now().isoformat()
        }
        
        doc_ref.set(data, merge=True)
        logger.debug(f"💰 Account info saved: Balance=${account.balance}, Equity=${equity}")
        
    except Exception as e:
        logger.error(f"Account info save error: {e}")

def save_positions(db, positions):
    """บันทึก Open Positions ไป Firebase"""
    try:
        # Clear old positions first
        positions_ref = db.collection('positions')
        old_positions = positions_ref.get()
        for doc in old_positions:
            doc.reference.delete()
        
        # Save current positions
        for pos in positions:
            doc_ref = positions_ref.document(str(pos.ticket))
            data = {
                'ticket': pos.ticket,
                'symbol': pos.symbol,
                'type': 'BUY' if pos.type == 0 else 'SELL',
                'volume': pos.volume,
                'open_price': pos.price_open,
                'current_price': pos.price_current,
                'profit': pos.profit,
                'open_time': datetime.fromtimestamp(pos.time).strftime('%Y-%m-%d %H:%M:%S'),
                'open_time_ts': pos.time,
                'sl': pos.sl,
                'tp': pos.tp,
            }
            doc_ref.set(data, merge=True)
        
        logger.debug(f"📋 Positions saved: {len(positions)} open positions")
        
    except Exception as e:
        logger.error(f"Positions save error: {e}")

def save_signals(db, signal_data):
    """บันทึก Signals ไป Firebase"""
    try:
        doc_ref = db.collection('signals').document()
        
        data = {
            'symbol': signal_data.get('symbol', 'XAUUSD'),
            'action': signal_data.get('action'),
            'reason': signal_data.get('reason', ''),
            'price': signal_data.get('price'),
            'time': int(datetime.now().timestamp()),
            'created_at': datetime.now().isoformat()
        }
        
        doc_ref.set(data)
        logger.info(f"📡 Signal saved: {signal_data.get('action')} - {signal_data.get('reason')}")
        
    except Exception as e:
        logger.error(f"Signal save error: {e}")

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
    
    # Track last account info update for efficiency
    last_account_update = 0
    last_positions_update = 0
    
    try:
        while True:
            current_time = time.time()
            
            # Process deals (trades)
            process_deals(db)
            
            # Update account info every 10 seconds
            if current_time - last_account_update >= 10:
                account = mt5.account_info()
                if account:
                    save_account_info(db, account)
                last_account_update = current_time
            
            # Update positions every 5 seconds
            if current_time - last_positions_update >= 5:
                positions = mt5.positions_get()
                if positions:
                    save_positions(db, positions)
                else:
                    # Clear positions if none
                    try:
                        positions_ref = db.collection('positions')
                        old_positions = positions_ref.get()
                        for doc in old_positions:
                            doc.reference.delete()
                    except:
                        pass
                last_positions_update = current_time
            
            time.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("🛑 Stopping MT5 Trade Logger...")
        
        # Set EA as stopped before exit
        try:
            doc_ref = db.collection('bot_status').document('status')
            doc_ref.set({'ea_running': False, 'updated_at': datetime.now().isoformat()}, merge=True)
            logger.info("✅ EA marked as stopped in Firebase")
        except:
            pass
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
