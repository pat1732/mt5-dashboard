"""
MT5 Auto Trading EA - EMA Crossover + RSI + MACD + News Filter
Strategy: Trend Following with Confirmation + News Protection
"""
import MetaTrader5 as mt5
import yaml
import time
import logging
import requests
from datetime import datetime, timedelta
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
ea_config = config.get('ea', {})

# Firebase initialization
firebase_db = None

def init_firebase():
    """เชื่อมต่อ Firebase Firestore"""
    global firebase_db
    try:
        import firebase_admin
        from firebase_admin import credentials
        
        firebase_config = config.get('firebase_config', {})
        service_account_path = firebase_config.get('service_account_path')
        
        if service_account_path and Path(service_account_path).exists():
            cred = credentials.Certificate(service_account_path)
            try:
                firebase_admin.get_app()
            except ValueError:
                firebase_admin.initialize_app(cred)
            
            from firebase_admin import firestore
            firebase_db = firestore.client()
            logger.info("✅ Firebase connected")
            return firebase_db
        else:
            logger.warning("⚠️ Firebase service account not found - Firebase disabled")
            return None
    except Exception as e:
        logger.warning(f"⚠️ Firebase init failed: {e}")
        return None

def save_account_info(db, account):
    """บันทึกข้อมูล Account Info ไป Firebase"""
    if not db:
        return
    
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
    if not db:
        return
    
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

def save_signal(db, action, reason, price):
    """บันทึก Signals ไป Firebase"""
    if not db:
        return
    
    try:
        doc_ref = db.collection('signals').document()
        
        data = {
            'symbol': SYMBOL,
            'action': action,
            'reason': reason,
            'price': price,
            'time': int(datetime.now().timestamp()),
            'created_at': datetime.now().isoformat()
        }
        
        doc_ref.set(data)
        logger.info(f"📡 Signal saved: {action} - {reason}")
        
    except Exception as e:
        logger.error(f"Signal save error: {e}")

# EA Settings
SYMBOL = ea_config.get('symbol', 'XAUUSD')
TIMEFRAME = ea_config.get('timeframe', 'H1')
TIMEFRAME_CONFIRM = ea_config.get('timeframe_confirm', 'M30')  # เพิ่ม M30 เป็น Confirm
LOT_SIZE = ea_config.get('lot_size', 0.01)
RISK_PERCENT = ea_config.get('risk_percent', 0.5)
MAX_LOT_SIZE = ea_config.get('max_lot_size', 0.05)  # Max lot เพื่อป้องกันความเสี่ยง
MAX_TRADES_PER_DAY = ea_config.get('max_trades_per_day', 5)

# News Filter Settings
NEWS_FILTER_ENABLED = ea_config.get('news_filter_enabled', True)
NEWS_HOURS_BEFORE = ea_config.get('news_hours_before', 1)  # ชั่วโมงก่อนข่าว
NEWS_HOURS_AFTER = ea_config.get('news_hours_after', 1)   # ชั่วโมงหลังข่าว
HIGH_IMPACT_KEYWORDS = ['FOMC', 'NFP', 'CPI', 'GDP', 'Non-Farm', 'Interest Rate', 'ECB', 'BOE', 'FED']

# Time Filter Settings (เทรดได้เฉพาะช่วง)
TRADE_START_HOUR = ea_config.get('trade_start_hour', 7)   # 7:00 UTC
TRADE_END_HOUR = ea_config.get('trade_end_hour', 19)      # 19:00 UTC

# Indicator Settings (OPTIMIZED FOR XAUUSD)
EMA_FAST = ea_config.get('ema_fast', 9)        # ใช้ 9 สำหรับ XAUUSD (เร็ว反应)
EMA_SLOW = ea_config.get('ema_slow', 21)      # ใช้ 21 สำหรับ XAUUSD
RSI_PERIOD = ea_config.get('rsi_period', 14)
RSI_BUY = ea_config.get('rsi_buy', 40)         # RSI ต่ำกว่า 40 = ซื้อ (oversold)
RSI_SELL = ea_config.get('rsi_sell', 60)        # RSI สูงกว่า 60 = ขาย (overbought)

# MACD Settings
MACD_FAST = ea_config.get('macd_fast', 12)
MACD_SLOW = ea_config.get('macd_slow', 26)
MACD_SIGNAL = ea_config.get('macd_signal', 9)

# Stochastic Settings
STOCH_K = ea_config.get('stoch_k', 14)
STOCH_D = ea_config.get('stoch_d', 3)
STOCH_SLOW = ea_config.get('stoch_slow', 3)
STOCH_BUY_THRESHOLD = ea_config.get('stoch_buy_threshold', 25)   # Stochastic < 25 = oversold
STOCH_SELL_THRESHOLD = ea_config.get('stoch_sell_threshold', 75) # Stochastic > 75 = overbought

# SL/TP Settings (REDUCED FOR XAUUSD - Points)
# XAUUSD: 1 point = $0.01, ดังนั้น 400 points = $4, 800 points = $8
SL_POINTS = ea_config.get('sl_points', 400)    # 400 points = $4 (ลดจาก 1500)
TP_POINTS = ea_config.get('tp_points', 800)    # 800 points = $8 (ลดจาก 3000)

# Trailing Stop Settings (OPTIMIZED FOR SMALLER SL/TP)
TRAILING_START_PROFIT = ea_config.get('trailing_start_profit', 5)   # เริ่มที่ $5 profit (ลดจาก 10)
TRAILING_STEP = ea_config.get('trailing_step', 2)                   # ขยับทุก $2

# ADX Settings (Trend Strength) - ปรับให้เข้มงวดขึ้น
ADX_PERIOD = ea_config.get('adx_period', 14)
ADX_TREND_THRESHOLD = ea_config.get('adx_trend_threshold', 25)      # เพิ่มจาก 20 เป็น 25

# Track daily trades
trades_today = {'date': None, 'count': 0}

def get_news_events():
    """ดึงข้อมูลข่าว forex จากเว็บฟรี"""
    try:
        # ใช้ forexfactory.com ผ่าน scraping
        url = "https://www.forexfactory.com/calendar"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        # ดึงข่าววันนี้และพรุ่งนี้
        events = []
        # สำหรับทดสอบ จะ return empty เพราะ parsing ยาก
        # ใน production อาจใช้ API จ่าย
        
        return events
    except Exception as e:
        logger.warning(f"News fetch error: {e}")
        return []

def check_news_filter():
    """ตรวจสอบว่าอยู่ช่วงข่าวสำคัญหรือไม่"""
    if not NEWS_FILTER_ENABLED:
        return False  # ถ้าปิด news filter แล้ว ไม่ต้องหยุด
    
    try:
        events = get_news_events()
        
        now = datetime.utcnow()
        
        for event in events:
            event_time = event.get('datetime')
            if event_time is None:
                continue
            
            # ตรวจช่วงก่อน/หลังข่าว
            time_before = event_time - timedelta(hours=NEWS_HOURS_BEFORE)
            time_after = event_time + timedelta(hours=NEWS_HOURS_AFTER)
            
            if time_before <= now <= time_after:
                logger.warning(f"⛔ News filter: {event.get('title')} at {event_time}")
                return True
        
        return False
        
    except Exception as e:
        logger.warning(f"News filter check error: {e}")
        return False  # ถ้าดึงข่าวไม่ได้ อนุญาตให้เทรด

def check_trading_hours():
    """ตรวจสอบว่าอยู่ในช่วงเวลาที่อนุญาตให้เทรดหรือไม่"""
    now_utc = datetime.utcnow()
    current_hour = now_utc.hour
    
    if TRADE_START_HOUR <= current_hour < TRADE_END_HOUR:
        return True
    else:
        logger.info(f"⛔ Outside trading hours: {current_hour} UTC")
        return False

def get_adx(symbol, period=14):
    """Calculate ADX (Average Directional Index)"""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None:
        return None
    
    import pandas as pd
    df = pd.DataFrame(rates)
    
    # Calculate True Range
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    
    # Calculate +DM and -DM
    df['plus_dm'] = df['high'].diff()
    df['minus_dm'] = -df['low'].diff()
    
    df['plus_dm'] = df['plus_dm'].apply(lambda x: x if x > 0 else 0)
    df['minus_dm'] = df['minus_dm'].apply(lambda x: x if x > 0 else 0)
    
    # Smooth
    df['tr_smooth'] = df['tr'].rolling(window=period).mean()
    df['plus_dm_smooth'] = df['plus_dm'].rolling(window=period).mean()
    df['minus_dm_smooth'] = df['minus_dm'].rolling(window=period).mean()
    
    # Calculate +DI and -DI
    df['plus_di'] = (df['plus_dm_smooth'] / df['tr_smooth']) * 100
    df['minus_di'] = (df['minus_dm_smooth'] / df['tr_smooth']) * 100
    
    # Calculate DX
    df['dx'] = abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']) * 100
    
    # Calculate ADX
    adx = df['dx'].rolling(window=period).mean()
    
    return {
        'adx': adx.iloc[-1],
        'plus_di': df['plus_di'].iloc[-1],
        'minus_di': df['minus_di'].iloc[-1]
    }

def get_ma(symbol, period, ma_type='EMA', num=1):
    """Get Moving Average"""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None:
        return None
    
    import pandas as pd
    df = pd.DataFrame(rates)
    
    if ma_type == 'EMA':
        df['ma'] = df['close'].ewm(span=period, adjust=False).mean()
    else:
        df['ma'] = df['close'].rolling(window=period).mean()
    
    return df['ma'].iloc[-num]

def get_rsi(symbol, period=14, num=1, timeframe='H1'):
    """Get RSI"""
    tf = mt5.TIMEFRAME_H1 if timeframe == 'H1' else mt5.TIMEFRAME_M30
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 100)
    if rates is None:
        return None
    
    import pandas as pd
    df = pd.DataFrame(rates)
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.iloc[-num]

def get_stochastic(symbol, k_period=14, d_period=3, slow_k=3, num=1):
    """Get Stochastic Oscillator"""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None:
        return None, None
    
    import pandas as pd
    df = pd.DataFrame(rates)
    
    # Calculate %K
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    
    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
    
    # Apply slow K (smooth)
    stoch_k = stoch_k.rolling(window=slow_k).mean()
    
    # Calculate %D (signal line)
    stoch_d = stoch_k.rolling(window=d_period).mean()
    
    return stoch_k.iloc[-num], stoch_d.iloc[-num]

def get_macd(symbol, fast=12, slow=26, signal=9):
    """Get MACD"""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None:
        return None, None, None
    
    import pandas as pd
    df = pd.DataFrame(rates)
    
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

def get_account_info():
    """Get Account Info"""
    account = mt5.account_info()
    return account

def calculate_lot_size():
    """Calculate Lot Size based on Risk % with Max Lot Cap"""
    account = get_account_info()
    if account is None:
        logger.warning("⚠️ Cannot get account info, using default lot")
        return LOT_SIZE
    
    balance = account.balance
    risk_amount = balance * (RISK_PERCENT / 100)
    
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        logger.warning("⚠️ Cannot get symbol info, using default lot")
        return LOT_SIZE
    
    # Use SL_POINTS for lot calculation (1500 points = 15 USD for XAUUSD)
    pip_value = symbol_info.point * 10
    lot_size = risk_amount / (SL_POINTS * pip_value * 10)
    lot_size = round(lot_size, 2)
    
    # Apply constraints: min 0.01, max MAX_LOT_SIZE
    lot_size = max(lot_size, 0.01)
    lot_size = min(lot_size, MAX_LOT_SIZE)
    
    logger.info(f"💰 Balance: ${balance:.2f} | Risk: {RISK_PERCENT}% = ${risk_amount:.2f} | Calculated Lot: {lot_size} (Max: {MAX_LOT_SIZE})")
    
    return lot_size

def check_trade_conditions():
    """Check trade signal - OPTIMIZED STRATEGY FOR XAUUSD
    
    Strategy: EMA(9,21) + RSI + Stochastic + ADX (Strong Trend Required)
    - EMA Cross = Primary Trend Direction
    - RSI = Overbought/Oversold (Buy <40, Sell >60)
    - Stochastic = Momentum Confirmation (Buy <25, Sell >75)
    - ADX > 25 = Strong Trend Required (เพิ่มความเข้มงวด)
    - MACD = Additional Confirmation
    
    เข้าเมื่อ: EMA Cross + (RSI หรือ Stochastic) + ADX > 25
    """
    
    # Get indicators from H1 (main timeframe)
    ema_fast = get_ma(SYMBOL, EMA_FAST, 'EMA')
    ema_slow = get_ma(SYMBOL, EMA_SLOW, 'EMA')
    rsi = get_rsi(SYMBOL, RSI_PERIOD)
    macd_line, signal_line, histogram = get_macd(SYMBOL, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    adx_data = get_adx(SYMBOL, ADX_PERIOD)
    stoch_k, stoch_d = get_stochastic(SYMBOL, STOCH_K, STOCH_D, STOCH_SLOW)
    
    logger.info(f"📊 EMA{EMA_FAST}: {ema_fast:.2f}, EMA{EMA_SLOW}: {ema_slow:.2f}, RSI: {rsi:.2f}")
    logger.info(f"📊 Stochastic: %K={stoch_k:.2f}, %D={stoch_d:.2f}")
    logger.info(f"📊 MACD: {macd_line:.2f}, Signal: {signal_line:.2f}, Hist: {histogram:.2f}")
    
    if adx_data:
        logger.info(f"📊 ADX: {adx_data['adx']:.2f}, +DI: {adx_data['plus_di']:.2f}, -DI: {adx_data['minus_di']:.2f}")
    
    if None in [ema_fast, ema_slow, rsi, stoch_k, stoch_d]:
        return None
    
    signal = None
    
    # ========== BUY Conditions (STRICT) ==========
    # 1. EMA9 > EMA21 (Trend Up) - REQUIRED
    # 2. RSI < 40 (Oversold) - REQUIRED
    # 3. Stochastic < 25 (Oversold) OR Stochastic %K > %D (Bullish Cross) - REQUIRED
    # 4. ADX > 25 (Strong Trend) - REQUIRED
    # 5. MACD > Signal OR Histogram > 0 - Optional
    
    ema_bullish = ema_fast > ema_slow
    rsi_buy = rsi < RSI_BUY  # < 40
    stoch_oversold = stoch_k < STOCH_BUY_THRESHOLD  # < 25
    stoch_bullish_cross = stoch_k > stoch_d  # K above D = bullish
    macd_bullish = (macd_line > signal_line) or (histogram > 0)
    
    # ADX must show strong trend
    strong_trend = adx_data['adx'] > ADX_TREND_THRESHOLD if adx_data else False
    
    # BUY: EMA Cross UP + RSI Buy + (Stochastic Oversold OR Bullish Cross) + ADX > 25
    if ema_bullish and rsi_buy and (stoch_oversold or stoch_bullish_cross) and strong_trend:
        macd_confirm = "✅" if macd_bullish else "⚠️"
        logger.info(f"🟢 STRONG BUY: EMA{EMA_FAST}>{EMA_SLOW}, RSI={rsi:.2f}<{RSI_BUY}, Stoch={stoch_k:.2f}, ADX={adx_data['adx']:.2f}>25 | MACD {macd_confirm}")
        signal = 'BUY'
    
    # ========== SELL Conditions (STRICT) ==========
    # 1. EMA9 < EMA21 (Trend Down) - REQUIRED
    # 2. RSI > 60 (Overbought) - REQUIRED
    # 3. Stochastic > 75 (Overbought) OR Stochastic %K < %D (Bearish Cross) - REQUIRED
    # 4. ADX > 25 (Strong Trend) - REQUIRED
    # 5. MACD < Signal OR Histogram < 0 - Optional
    
    ema_bearish = ema_fast < ema_slow
    rsi_sell = rsi > RSI_SELL  # > 60
    stoch_overbought = stoch_k > STOCH_SELL_THRESHOLD  # > 75
    stoch_bearish_cross = stoch_k < stoch_d  # K below D = bearish
    macd_bearish = (macd_line < signal_line) or (histogram < 0)
    
    # SELL: EMA Cross DOWN + RSI Sell + (Stochastic Overbought OR Bearish Cross) + ADX > 25
    if ema_bearish and rsi_sell and (stoch_overbought or stoch_bearish_cross) and strong_trend:
        macd_confirm = "✅" if macd_bearish else "⚠️"
        logger.info(f"🔴 STRONG SELL: EMA{EMA_FAST}<{EMA_SLOW}, RSI={rsi:.2f}>{RSI_SELL}, Stoch={stoch_k:.2f}, ADX={adx_data['adx']:.2f}>25 | MACD {macd_confirm}")
        signal = 'SELL'
    
    # Log reason if no signal
    if signal is None:
        reasons = []
        if not ema_bullish and not ema_bearish:
            reasons.append("EMA ไม่ Cross")
        if not rsi_buy and not rsi_sell:
            reasons.append("RSI ไม่อยู่ในโซน")
        if not stoch_oversold and not stoch_overbought and not stoch_bullish_cross and not stoch_bearish_cross:
            reasons.append("Stochastic ไม่ยืนยัน")
        if not strong_trend:
            reasons.append(f"ADX={adx_data['adx']:.2f}<25 (Trend ไม่แรง)")
        
        logger.info(f"⏸️ No Signal: {' | '.join(reasons)}")
    
    return signal

def check_open_positions():
    """Check for open positions"""
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions

def place_order(order_type, lot_size):
    """Place an order - OPTIMIZED: SL=400 points, TP=800 points for XAUUSD"""
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        logger.error(f"Symbol {SYMBOL} not found")
        return False
    
    if not symbol_info.visible:
        if not mt5.symbol_select(SYMBOL, True):
            logger.error(f"Cannot select {SYMBOL}")
            return False
    
    point = symbol_info.point
    
    if order_type == 'BUY':
        order_type_enum = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(SYMBOL).ask
        sl = price - SL_POINTS * point    # 400 points = $4 for XAUUSD
        tp = price + TP_POINTS * point     # 800 points = $8 for XAUUSD
    else:
        order_type_enum = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(SYMBOL).bid
        sl = price + SL_POINTS * point     # 400 points = $4 for XAUUSD
        tp = price - TP_POINTS * point     # 800 points = $8 for XAUUSD
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot_size,
        "type": order_type_enum,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 234000,
        "comment": "EMA20_50_RSI_Stoch_EA",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"✅ {order_type} Order Placed: {lot_size} lots at {price}")
        logger.info(f"   📍 SL: {sl:.2f} ({SL_POINTS} points), TP: {tp:.2f} ({TP_POINTS} points)")
        
        # Send Telegram Alert
        send_telegram_alert(order_type, price, lot_size, sl, tp)
        return True
    else:
        logger.error(f"❌ Order Failed: {result.comment}")
        return False

def send_telegram_alert(order_type, price, lot_size, sl=None, tp=None):
    """Send Telegram Alert"""
    try:
        import requests
        
        # Read from root level (not telegram: section)
        bot_token = config.get('telegram_bot_token')
        chat_id = config.get('telegram_chat_id')
        
        if not bot_token or not chat_id:
            logger.warning("⚠️ Telegram config missing - bot_token or chat_id not found")
            logger.warning(f"   config keys: {list(config.keys())}")
            return
        
        message = f"🔔 *Trade Executed!*\n\n"
        message += f"📊 *{SYMBOL}*\n"
        message += f"📈 Type: *{order_type}*\n"
        message += f"📦 Volume: {lot_size}\n"
        message += f"💰 Price: {price}\n"
        if sl and tp:
            message += f"🛡️ SL: {sl:.2f}\n"
            message += f"🎯 TP: {tp:.2f}\n"
        message += f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        requests.post(url, json=data)
    except Exception as e:
        logger.error(f"Telegram Error: {e}")

def check_trailing_stop():
    """Check and update trailing stop for open positions - NEW: Start at 10 USD profit"""
    positions = check_open_positions()
    
    if positions is None or len(positions) == 0:
        return
    
    symbol_info = mt5.symbol_info(SYMBOL)
    point = symbol_info.point
    
    for pos in positions:
        pos_type = 'BUY' if pos.type == 0 else 'SELL'
        
        # Calculate current profit in USD
        profit = pos.profit
        
        # Only activate trailing stop when profit >= TRAILING_START_PROFIT (10 USD)
        if profit < TRAILING_START_PROFIT:
            continue
        
        # Calculate new SL based on profit
        # Move SL by TRAILING_STEP (5 USD) from current SL
        if pos_type == 'BUY':
            tick = mt5.symbol_info_tick(SYMBOL)
            
            # Calculate how many points to move SL
            # For XAUUSD: 1 point = $0.01, so 500 points = $5
            trailing_points = int(TRAILING_STEP / (point * 10))  # Convert USD to points
            new_sl = pos.sl + trailing_points * point
            
            # Also ensure new SL is above entry
            if new_sl > pos.sl and new_sl < tick.bid - 100 * point:  # Keep at least 100 points buffer
                new_sl = tick.bid - 100 * point  # Minimal SL trail
            
            if new_sl > pos.sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"✅ Trailing Stop Updated: {pos.ticket} | Profit: ${profit:.2f} | New SL: {new_sl:.2f}")
                    
        else:  # SELL
            tick = mt5.symbol_info_tick(SYMBOL)
            
            trailing_points = int(TRAILING_STEP / (point * 10))
            new_sl = pos.sl - trailing_points * point
            
            if new_sl < pos.sl and new_sl > tick.ask + 100 * point:
                new_sl = tick.ask + 100 * point
            
            if new_sl < pos.sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"✅ Trailing Stop Updated: {pos.ticket} | Profit: ${profit:.2f} | New SL: {new_sl:.2f}")

def reset_daily_trades():
    """Reset daily trade counter"""
    global trades_today
    today = datetime.now().date()
    
    if trades_today['date'] != today:
        trades_today['date'] = today
        trades_today['count'] = 0
        logger.info("🔄 Daily trade counter reset")

def main():
    """Main EA Loop - OPTIMIZED STRATEGY FOR XAUUSD
    
    Strategy: EMA(9,21) + RSI + Stochastic + ADX(>25)
    """
    logger.info(f"🚀 Starting OPTIMIZED EA for XAUUSD: EMA({EMA_FAST},{EMA_SLOW}) + RSI + Stochastic + ADX")
    logger.info(f"📋 BUY: EMA{EMA_FAST} > EMA{EMA_SLOW} + RSI < {RSI_BUY} + Stoch < {STOCH_BUY_THRESHOLD} + ADX > {ADX_TREND_THRESHOLD}")
    logger.info(f"📋 SELL: EMA{EMA_FAST} < EMA{EMA_SLOW} + RSI > {RSI_SELL} + Stoch > {STOCH_SELL_THRESHOLD} + ADX > {ADX_TREND_THRESHOLD}")
    logger.info(f"📋 SL: {SL_POINTS} points (${SL_POINTS/100}), TP: {TP_POINTS} points (${TP_POINTS/100})")
    logger.info(f"📋 Trailing Stop: Start at ${TRAILING_START_PROFIT}, Step: ${TRAILING_STEP}")
    logger.info(f"📋 Trading Hours: {TRADE_START_HOUR}:00 - {TRADE_END_HOUR}:00 UTC")
    
    # Initialize Firebase
    db = init_firebase()
    
    mt5_config = config.get('mt5', {})
    
    if not mt5.initialize(
        login=mt5_config.get('login'),
        password=mt5_config.get('password'),
        server=mt5_config.get('server')
    ):
        logger.error(f"MT5 Initialize failed: {mt5.last_error()}")
        return
    
    account_info = mt5.account_info()
    logger.info(f"✅ MT5 Connected: {account_info.login} | Balance: ${account_info.balance}")
    
    # Save initial account info
    if db:
        save_account_info(db, account_info)
    
    check_interval = ea_config.get('check_interval', 60)
    
    # Track last update times
    last_account_update = 0
    last_positions_update = 0
    
    try:
        while True:
            current_time = time.time()
            reset_daily_trades()
            
            # 1. Check Trailing Stop
            check_trailing_stop()
            
            # 2. Update account info to Firebase every 10 seconds
            if db and (current_time - last_account_update) >= 10:
                account = mt5.account_info()
                if account:
                    save_account_info(db, account)
                last_account_update = current_time
            
            # 3. Update positions to Firebase every 5 seconds
            if db and (current_time - last_positions_update) >= 5:
                positions = check_open_positions()
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
            
            # 4. Check Max Trades
            if trades_today['count'] >= MAX_TRADES_PER_DAY:
                logger.info(f"⏸️ Max trades ({MAX_TRADES_PER_DAY}) reached today")
                time.sleep(check_interval)
                continue
            
            # 5. Check Trading Hours
            if not check_trading_hours():
                logger.info("⏸️ Outside trading hours")
                time.sleep(check_interval)
                continue
            
            # 6. Check News Filter
            if check_news_filter():
                logger.warning("⛔ News filter active - skipping trade")
                time.sleep(check_interval)
                continue
            
            # 7. Check Open Positions
            positions = check_open_positions()
            if positions and len(positions) > 0:
                logger.info(f"📊 Position already open: {len(positions)}")
                time.sleep(check_interval)
                continue
            
            # 8. Check Trade Signals
            signal = check_trade_conditions()
            
            if signal:
                # Save signal to Firebase
                if db:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    price = tick.ask if signal == 'BUY' else tick.bid
                    reason = f"EMA{EMA_FAST}/{EMA_SLOW} + RSI + Stochastic"
                    save_signal(db, signal, reason, price)
                
                lot_size = calculate_lot_size()
                logger.info(f"📈 Signal: {signal} | Lot: {lot_size}")
                
                if place_order(signal, lot_size):
                    trades_today['count'] += 1
                    logger.info(f"📊 Trades today: {trades_today['count']}/{MAX_TRADES_PER_DAY}")
            else:
                logger.info("⏸️ No signal")
            
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        logger.info("🛑 EA Stopped")
        
        # Mark EA as stopped in Firebase
        if db:
            try:
                doc_ref = db.collection('bot_status').document('status')
                doc_ref.set({'ea_running': False, 'updated_at': datetime.now().isoformat()}, merge=True)
                logger.info("✅ EA marked as stopped in Firebase")
            except:
                pass
    finally:
        mt5.shutdown()
        mt5.shutdown()

if __name__ == "__main__":
    main()
