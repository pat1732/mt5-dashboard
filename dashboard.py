"""
MT5 Trade Dashboard - แสดงข้อมูล Trade จาก Firebase Firestore (REST API)
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import requests

# Page Config
st.set_page_config(
    page_title="MT5 Trade Dashboard",
    page_icon="📈",
    layout="wide"
)

# Custom CSS
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .metric-value {
        font-size: 32px;
        font-weight: bold;
    }
    .metric-label {
        font-size: 14px;
        color: #666;
    }
    .profit {
        color: #00C853;
    }
    .loss {
        color: #FF1744;
    }
    </style>
    """, unsafe_allow_html=True)

@st.cache_data
def load_data():
    """โหลดข้อมูลจาก Firebase Firestore via REST API"""
    try:
        # ใช้ Firestore REST API
        project_id = "mt5-trading-a1e86"
        url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/trades"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            st.error(f"Error: {response.status_code}")
            return pd.DataFrame()
        
        data = response.json()
        
        if not data.get('documents'):
            return pd.DataFrame()
        
        trades = []
        for doc in data['documents']:
            fields = doc.get('fields', {})
            trade = {
                'symbol': fields.get('symbol', {}).get('stringValue', '-'),
                'type': fields.get('type', {}).get('stringValue', '-'),
                'volume': fields.get('volume', {}).get('doubleValue', 0),
                'open_price': fields.get('open_price', {}).get('doubleValue', 0),
                'close_price': fields.get('close_price', {}).get('doubleValue', 0),
                'profit': fields.get('profit', {}).get('doubleValue', 0),
                'open_time': fields.get('open_time', {}).get('stringValue', '-'),
                'close_time': fields.get('close_time', {}).get('stringValue', '-'),
            }
            trades.append(trade)
        
        if trades:
            df = pd.DataFrame(trades)
            
            # Parse dates
            for field in ['open_time', 'close_time']:
                if field in df.columns:
                    df[field] = pd.to_datetime(df[field], errors='coerce')
            
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return pd.DataFrame()

def calculate_metrics(df):
    """คำนวณ Metrics"""
    if df.empty:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'total_profit': 0,
            'avg_profit': 0,
            'best_trade': 0,
            'worst_trade': 0
        }
    
    # Total trades (closed only - have profit)
    closed_trades = df[df['profit'].notna() & (df['profit'] != 0)]
    metrics = {}
    
    metrics['total_trades'] = len(closed_trades)
    
    # Winning/Losing
    winning = closed_trades[closed_trades['profit'] > 0]
    losing = closed_trades[closed_trades['profit'] < 0]
    
    metrics['winning_trades'] = len(winning)
    metrics['losing_trades'] = len(losing)
    metrics['win_rate'] = (len(winning) / len(closed_trades) * 100) if len(closed_trades) > 0 else 0
    
    # Profit
    metrics['total_profit'] = closed_trades['profit'].sum() if len(closed_trades) > 0 else 0
    metrics['avg_profit'] = closed_trades['profit'].mean() if len(closed_trades) > 0 else 0
    metrics['best_trade'] = closed_trades['profit'].max() if len(closed_trades) > 0 else 0
    metrics['worst_trade'] = closed_trades['profit'].min() if len(closed_trades) > 0 else 0
    
    return metrics

def plot_equity_curve(df):
    """วาด Equity Curve"""
    closed_trades = df[df['profit'].notna() & (df['profit'] != 0)].sort_values('close_time')
    
    if closed_trades.empty:
        return None
    
    closed_trades = closed_trades.copy()
    closed_trades = closed_trades.sort_values('close_time')
    closed_trades['cumulative_profit'] = closed_trades['profit'].cumsum()
    
    fig = px.line(
        closed_trades, 
        x='close_time', 
        y='cumulative_profit',
        title='📈 Equity Curve',
        labels={'cumulative_profit': 'Profit ($)', 'close_time': 'Time'}
    )
    
    fig.update_traces(line_color='#00C853', line_width=2)
    fig.update_layout(
        paper_bgcolor='white',
        plot_bgcolor='white',
        hovermode='x unified'
    )
    
    return fig

def plot_profit_by_symbol(df):
    """แสดงกำไรแยกตาม Symbol"""
    closed_trades = df[df['profit'].notna() & (df['profit'] != 0)]
    
    if closed_trades.empty:
        return None
    
    symbol_profit = closed_trades.groupby('symbol')['profit'].sum().reset_index()
    
    fig = px.bar(
        symbol_profit,
        x='symbol',
        y='profit',
        title='💰 Profit by Symbol',
        color='profit',
        color_continuous_scale=['#FF1744', '#00C853']
    )
    
    fig.update_layout(
        paper_bgcolor='white',
        plot_bgcolor='white'
    )
    
    return fig

def plot_win_lose_pie(df):
    """แสดง Win/Lose Pie Chart"""
    closed_trades = df[df['profit'].notna() & (df['profit'] != 0)]
    
    if closed_trades.empty:
        return None
    
    wins = len(closed_trades[closed_trades['profit'] > 0])
    losses = len(closed_trades[closed_trades['profit'] < 0])
    
    if wins + losses == 0:
        return None
    
    fig = px.pie(
        values=[wins, losses],
        names=['Win', 'Loss'],
        title='🎯 Win Rate',
        color=['#00C853', '#FF1744'],
        hole=0.4
    )
    
    return fig

# Main App
st.title("📈 MT5 Trade Dashboard")

# Load Data
df = load_data()

if df.empty:
    st.warning("⚠️ ไม่มีข้อมูลการเทรด!")
    st.info("EA จะเก็บข้อมูลเมื่อมีการเทรดค่ะ")
    st.stop()

# Calculate Metrics
metrics = calculate_metrics(df)

# Display Metrics
st.markdown("## 📊 Overview")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Trades", metrics['total_trades'])

with col2:
    profit_color = "normal" if metrics['total_profit'] >= 0 else "inverse"
    st.metric("Total Profit", f"${metrics['total_profit']:.2f}", delta_color=profit_color)

with col3:
    st.metric("Win Rate", f"{metrics['win_rate']:.1f}%")

with col4:
    st.metric("Avg Profit/Trade", f"${metrics['avg_profit']:.2f}")

# Charts
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    equity_fig = plot_equity_curve(df)
    if equity_fig:
        st.plotly_chart(equity_fig, use_container_width=True)
    else:
        st.info("No closed trades yet")

with col2:
    pie_fig = plot_win_lose_pie(df)
    if pie_fig:
        st.plotly_chart(pie_fig, use_container_width=True)

# Profit by Symbol
symbol_fig = plot_profit_by_symbol(df)
if symbol_fig:
    st.plotly_chart(symbol_fig, use_container_width=True)

# Trade History
st.markdown("---")
st.markdown("## 📋 Trade History")

# Filter options
col1, col2 = st.columns(2)

with col1:
    if 'symbol' in df.columns:
        symbol_filter = st.selectbox(
            "Filter by Symbol",
            ['All'] + list(df['symbol'].unique())
        )
    else:
        symbol_filter = 'All'

with col2:
    if 'type' in df.columns:
        type_filter = st.selectbox(
            "Filter by Type", 
            ['All', 'BUY', 'SELL', 'CLOSE']
        )
    else:
        type_filter = 'All'

# Apply filters
filtered_df = df.copy()

if symbol_filter != 'All' and 'symbol' in df.columns:
    filtered_df = filtered_df[filtered_df['symbol'] == symbol_filter]

if type_filter != 'All' and 'type' in df.columns:
    filtered_df = filtered_df[filtered_df['type'] == type_filter]

# Display table
if not filtered_df.empty:
    display_cols = ['symbol', 'type', 'volume', 'open_price', 'close_price', 'profit', 'open_time', 'close_time']
    display_cols = [c for c in display_cols if c in filtered_df.columns]
    
    display_df = filtered_df[display_cols].copy()
    
    # Format for display
    if 'profit' in display_df.columns:
        display_df['profit'] = display_df['profit'].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "-"
        )
    if 'open_price' in display_df.columns:
        display_df['open_price'] = display_df['open_price'].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "-")
    if 'close_price' in display_df.columns:
        display_df['close_price'] = display_df['close_price'].apply(lambda x: f"{x:.5f}" if pd.notna(x) else "-")
    if 'volume' in display_df.columns:
        display_df['volume'] = display_df['volume'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
    
    st.dataframe(display_df, use_container_width=True)
else:
    st.info("No trades match the filters")

# Footer
st.markdown("---")
st.markdown(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
