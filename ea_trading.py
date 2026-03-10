"""
MT5 Auto Trading EA - EMA Crossover + RSI + MACD
Strategy: Trend Following with Confirmation
"""
import MetaTrader5 as mt5
import yaml
import time
import logging
from datetime import datetime

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
RISK_PERCENT = ea_config.get('risk_percent', 2)  # % of account
SL_PIPS = ea_config.get('sl_pips', 50)
TP_PIPS = ea_config.get('tp_pips', 100)  # R:R = 1:2
MAX_TRADES_PER_DAY = ea_config.get('max_trades_per_day', 5)
TRAILING_STOP_PIPS = ea_config.get('trailing_stop_pips', 30)

# Indicator Settings
EMA_FAST = ea_config.get('ema_fast', 9)
EMA_SLOW = ea_config.get('ema_slow', 21)
RSI_PERIOD = ea_config.get('rsi_period', 14)
MACD_FAST = ea_config.get('macd_fast', 12)
MACD_SLOW = ea_config.get('macd_slow', 26)
MACD_SIGNAL = ea_config.get('macd_signal', 9)

# Track daily trades
trades_today = {'date': None, 'count': 0}

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
    
    # Get symbol info for pip value
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        return LOT_SIZE
    
    pip_value = symbol_info.point * 10
    
    # Calculate lot size
    lot_size = risk_amount / (SL_PIPS * pip_value * 10)
    
    # Round to 2 decimal places and within limits
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
    
    logger.info(f"EMA9: {ema_fast}, EMA21: {ema_slow}, RSI: {rsi}")
    logger.info(f"MACD: {macd_line}, Signal: {signal_line}, Hist: {histogram}")
    
    if None in [ema_fast, ema_slow, rsi, macd_line, signal_line]:
        return None
    
    signal = None
    
    # BUY Conditions: EMA9 > EMA21 + RSI < 30 + MACD cross up
    if (ema_fast > ema_slow and 
        rsi < 35 and 
        macd_line > signal_line):
        signal = 'BUY'
    
    # SELL Conditions: EMA9 < EMA21 + RSI > 70 + MACD cross down
    elif (ema_fast < ema_slow and 
          rsi > 65 and 
          macd_line < signal_line):
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
    
    # Activate symbol
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
        "comment": "EMA_RSI_MACD_EA",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"✅ {order_type} Order Placed: {lot_size} lots at {price}")
        return True
    else:
        logger.error(f"❌ Order Failed: {result.comment}")
        return False

def check_trailing_stop():
    """Check and update trailing stop for open positions"""
    positions = check_open_positions()
    
    if positions is None or len(positions) == 0:
        return
    
    symbol_info = mt5.symbol_info(SYMBOL)
    point = symbol_info.point
    
    for pos in positions:
        pos_type = 'BUY' if pos.type == 0 else 'SELL'
        current_price = pos.price_open
        current_sl = pos.sl
        
        if pos_type == 'BUY':
            # Check if price moved enough for trailing
            tick = mt5.symbol_info_tick(SYMBOL)
            new_sl = tick.bid - TRAILING_STOP_PIPS * point
            
            if new_sl > current_sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"✅ Trailing Stop Updated: {pos.ticket}")
                    
        else:  # SELL
            tick = mt5.symbol_info_tick(SYMBOL)
            new_sl = tick.ask + TRAILING_STOP_PIPS * point
            
            if new_sl < current_sl:
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
    logger.info(f"🚀 Starting EA: EMA+RSI+MACD on {SYMBOL}")
    
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
    logger.info(f"✅ MT5 Connected: {account_info.login} | Balance: ${account_info.balance}")
    
    # Main loop
    check_interval = ea_config.get('check_interval', 60)  # Check every 60 seconds
    
    try:
        while True:
            reset_daily_trades()
            
            # Check for trailing stop first
            check_trailing_stop()
            
            # Check if max trades reached
            if trades_today['count'] >= MAX_TRADES_PER_DAY:
                logger.info(f"⏸️ Max trades ({MAX_TRADES_PER_DAY}) reached today")
                time.sleep(check_interval)
                continue
            
            # Check for open positions
            positions = check_open_positions()
            
            if positions and len(positions) > 0:
                logger.info(f"📊 Position already open: {len(positions)}")
                time.sleep(check_interval)
                continue
            
            # Check trade conditions
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
