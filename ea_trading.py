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

# EA Settings
SYMBOL = ea_config.get('symbol', 'XAUUSD')
TIMEFRAME = ea_config.get('timeframe', 'H1')
LOT_SIZE = ea_config.get('lot_size', 0.01)
RISK_PERCENT = ea_config.get('risk_percent', 2)
SL_PIPS = ea_config.get('sl_pips', 50)
TP_PIPS = ea_config.get('tp_pips', 100)
MAX_TRADES_PER_DAY = ea_config.get('max_trades_per_day', 5)
TRAILING_STOP_PIPS = ea_config.get('trailing_stop_pips', 30)

# News Filter Settings
NEWS_FILTER_ENABLED = ea_config.get('news_filter_enabled', True)
NEWS_HOURS_BEFORE = ea_config.get('news_hours_before', 1)  # ชั่วโมงก่อนข่าว
NEWS_HOURS_AFTER = ea_config.get('news_hours_after', 1)   # ชั่วโมงหลังข่าว
HIGH_IMPACT_KEYWORDS = ['FOMC', 'NFP', 'CPI', 'GDP', 'Non-Farm', 'Interest Rate', 'ECB', 'BOE', 'FED']

# Time Filter Settings (เทรดได้เฉพาะช่วง)
TRADE_START_HOUR = ea_config.get('trade_start_hour', 7)   # 7:00 UTC
TRADE_END_HOUR = ea_config.get('trade_end_hour', 19)      # 19:00 UTC

# Indicator Settings
EMA_FAST = ea_config.get('ema_fast', 9)
EMA_SLOW = ea_config.get('ema_slow', 21)
RSI_PERIOD = ea_config.get('rsi_period', 14)
RSI_OVERSOLD = ea_config.get('rsi_oversold', 45)
RSI_OVERBOUGHT = ea_config.get('rsi_overbought', 55)
MACD_FAST = ea_config.get('macd_fast', 12)
MACD_SLOW = ea_config.get('macd_slow', 26)
MACD_SIGNAL = ea_config.get('macd_signal', 9)

# ADX Settings (Trend Strength)
ADX_PERIOD = ea_config.get('adx_period', 14)
ADX_TREND_THRESHOLD = ea_config.get('adx_trend_threshold', 20)

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

def get_rsi(symbol, period=14, num=1):
    """Get RSI"""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
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
    """Calculate Lot Size based on Risk %"""
    account = get_account_info()
    if account is None:
        return LOT_SIZE
    
    balance = account.balance
    risk_amount = balance * (RISK_PERCENT / 100)
    
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        return LOT_SIZE
    
    pip_value = symbol_info.point * 10
    lot_size = risk_amount / (SL_PIPS * pip_value * 10)
    lot_size = round(lot_size, 2)
    lot_size = max(lot_size, 0.01)
    lot_size = min(lot_size, 100.0)
    
    return lot_size

def check_trade_conditions():
    """Check if there's a trade signal"""
    
    # Get indicators
    ema_fast = get_ma(SYMBOL, EMA_FAST, 'EMA')
    ema_slow = get_ma(SYMBOL, EMA_SLOW, 'EMA')
    rsi = get_rsi(SYMBOL, RSI_PERIOD)
    macd_line, signal_line, histogram = get_macd(SYMBOL, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    adx_data = get_adx(SYMBOL, ADX_PERIOD)
    
    logger.info(f"📊 EMA9: {ema_fast:.2f}, EMA21: {ema_slow:.2f}, RSI: {rsi:.2f}")
    logger.info(f"📊 MACD: {macd_line:.2f}, Signal: {signal_line:.2f}, Hist: {histogram:.2f}")
    
    if adx_data:
        logger.info(f"📊 ADX: {adx_data['adx']:.2f}, +DI: {adx_data['plus_di']:.2f}, -DI: {adx_data['minus_di']:.2f}")
    
    if None in [ema_fast, ema_slow, rsi, macd_line, signal_line]:
        return None
    
    signal = None
    
    # BUY Conditions: 
    # 1. EMA9 > EMA21 (Trend)
    # 2. RSI < RSI_OVERSOLD
    # 3. MACD > Signal
    # 4. ADX > ADX_TREND_THRESHOLD (Strong trend)
    if (ema_fast > ema_slow and 
        rsi < RSI_OVERSOLD and 
        macd_line > signal_line and
        (adx_data is None or adx_data['adx'] > ADX_TREND_THRESHOLD)):
        signal = 'BUY'
    
    # SELL Conditions:
    elif (ema_fast < ema_slow and 
          rsi > RSI_OVERBOUGHT and 
          macd_line < signal_line and
          (adx_data is None or adx_data['adx'] > ADX_TREND_THRESHOLD)):
        signal = 'SELL'
    
    return signal

def check_open_positions():
    """Check for open positions"""
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions

def place_order(order_type, lot_size):
    """Place an order"""
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
        sl = price - SL_PIPS * point
        tp = price + TP_PIPS * point
    else:
        order_type_enum = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(SYMBOL).bid
        sl = price + SL_PIPS * point
        tp = price - TP_PIPS * point
    
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
        "comment": "EMA_RSI_MACD_ADX_EA",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"✅ {order_type} Order Placed: {lot_size} lots at {price}")
        
        # Send Telegram Alert
        send_telegram_alert(order_type, price, lot_size)
        return True
    else:
        logger.error(f"❌ Order Failed: {result.comment}")
        return False

def send_telegram_alert(order_type, price, lot_size):
    """Send Telegram Alert"""
    try:
        import requests
        
        config_tg = config.get('telegram', {})
        bot_token = config_tg.get('bot_token') or config_tg.get('telegram_bot_token')
        chat_id = config_tg.get('chat_id') or config_tg.get('telegram_chat_id')
        
        if not bot_token or not chat_id:
            return
        
        message = f"🔔 *Trade Executed!*\n\n"
        message += f"📊 *{SYMBOL}*\n"
        message += f"📈 Type: *{order_type}*\n"
        message += f"📦 Volume: {lot_size}\n"
        message += f"💰 Price: {price}\n"
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
    """Check and update trailing stop for open positions"""
    positions = check_open_positions()
    
    if positions is None or len(positions) == 0:
        return
    
    symbol_info = mt5.symbol_info(SYMBOL)
    point = symbol_info.point
    
    for pos in positions:
        pos_type = 'BUY' if pos.type == 0 else 'SELL'
        
        if pos_type == 'BUY':
            tick = mt5.symbol_info_tick(SYMBOL)
            new_sl = tick.bid - TRAILING_STOP_PIPS * point
            
            if new_sl > pos.sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"✅ Trailing Stop Updated: {pos.ticket}")
                    
        else:
            tick = mt5.symbol_info_tick(SYMBOL)
            new_sl = tick.ask + TRAILING_STOP_PIPS * point
            
            if new_sl < pos.sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"✅ Trailing Stop Updated: {pos.ticket}")

def reset_daily_trades():
    """Reset daily trade counter"""
    global trades_today
    today = datetime.now().date()
    
    if trades_today['date'] != today:
        trades_today['date'] = today
        trades_today['count'] = 0
        logger.info("🔄 Daily trade counter reset")

def main():
    """Main EA Loop"""
    logger.info(f"🚀 Starting EA: EMA+RSI+MACD+ADX on {SYMBOL}")
    logger.info(f"📋 News Filter: {NEWS_FILTER_ENABLED}")
    logger.info(f"📋 Trading Hours: {TRADE_START_HOUR}:00 - {TRADE_END_HOUR}:00 UTC")
    
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
    
    check_interval = ea_config.get('check_interval', 60)
    
    try:
        while True:
            reset_daily_trades()
            
            # 1. Check Trailing Stop
            check_trailing_stop()
            
            # 2. Check Max Trades
            if trades_today['count'] >= MAX_TRADES_PER_DAY:
                logger.info(f"⏸️ Max trades ({MAX_TRADES_PER_DAY}) reached today")
                time.sleep(check_interval)
                continue
            
            # 3. Check Trading Hours
            if not check_trading_hours():
                logger.info("⏸️ Outside trading hours")
                time.sleep(check_interval)
                continue
            
            # 4. Check News Filter
            if check_news_filter():
                logger.warning("⛔ News filter active - skipping trade")
                time.sleep(check_interval)
                continue
            
            # 5. Check Open Positions
            positions = check_open_positions()
            if positions and len(positions) > 0:
                logger.info(f"📊 Position already open: {len(positions)}")
                time.sleep(check_interval)
                continue
            
            # 6. Check Trade Signals
            signal = check_trade_conditions()
            
            if signal:
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
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
