import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import pytz
from datetime import datetime

# --- 1. ESSENTIAL CONFIG & IMPORTS ---
st.set_page_config(page_title="Concretum Hub", layout="wide")

TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
IST = pytz.timezone('Asia/Kolkata')

if 'trade_log' not in st.session_state:
    st.session_state.trade_log = []

# --- 2. DATA & STRATEGY ENGINE ---
def run_full_analysis():
    # Clear local session log for fresh scan
    st.session_state.trade_log = [] 
    
    cols = st.columns(len(TICKERS))
    
    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        
        # Fetch Data
        df = yf.download(TICKER, period="5d", interval="1m", auto_adjust=True, progress=False)
        daily = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)
        
        if df.empty or daily.empty: continue
        df.index = df.index.tz_convert('Asia/Kolkata')
        
        # Get Last Session Data
        last_date = df.index.date[-1]
        df_today = df[df.index.date == last_date].copy()
        
        # Levels
        ltp = df_today['Close'].iloc[-1]
        day_open = df_today['Open'].iloc[0]
        prev_hi, prev_lo = daily['High'].iloc[-2], daily['Low'].iloc[-2]
        prev_close = daily['Close'].iloc[-2]
        
        # Sigma & VWAP
        vol = daily['Close'].pct_change().tail(14).std()
        ub = max(day_open, prev_close) * (1 + 1.0 * vol)
        lb = min(day_open, prev_close) * (1 - 1.0 * vol)
        vwap = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()
        curr_vwap = vwap.iloc[-1]

        # --- POD LOGIC ---
        # Pod 1: GAP
        if t_name != "INDIAVIX":
            if day_open > prev_hi and ltp > prev_hi:
                record_trade(t_name, "GAP", "BUY", ltp, prev_lo)
            elif day_open < prev_lo and ltp < prev_lo:
                record_trade(t_name, "GAP", "SELL", ltp, prev_hi)

        # Pod 2: SIGMA
        sig_buy = (ltp > ub and ltp > curr_vwap)
        sig_sell = (ltp < lb and ltp < curr_vwap)
        if sig_buy: record_trade(t_name, "SIGMA", "BUY", ltp, lb)
        elif sig_sell: record_trade(t_name, "SIGMA", "SELL", ltp, ub)

        # Pod 3: REVERSAL
        if t_name != "INDIAVIX":
            # Reversal Long
            if day_open < prev_hi and ltp > day_open and ltp > prev_hi:
                record_trade(t_name, "REVERSAL", "BUY", ltp, day_open, is_ultra=sig_buy)
            # Reversal Short
            elif day_open > prev_lo and ltp < day_open and ltp < prev_lo:
                record_trade(t_name, "REVERSAL", "SELL", ltp, day_open, is_ultra=sig_sell)

        # --- OUTPUT: Price Charts ---
        with cols[i]:
            st.metric(f"{t_name}", f"{ltp:.2f}")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=250, margin=dict(l=0,r=0,t=30,b=0), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

def record_trade(ticker, pod, side, entry, sl, is_ultra=False):
    risk = abs(entry - sl)
    marker = "💎 ULTRA" if is_ultra else "NORMAL"
    
    # Calculate Points Profit (PnL) based on LTP vs Entry
    # Since we are scanning last session, we assume exit at day end or targets
    st.session_state.trade_log.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(entry + (risk*1.5) if side=="BUY" else entry - (risk*1.5), 2),
        "PnL": round((risk * 1.2), 2) # Simulated PnL for visual testing
    })

# --- 3. UI LAYOUT ---
st.title("🚀 Triple-Pod Command Center")

if st.sidebar.button("🔍 Run Live Session Scan"):
    run_full_analysis()

# --- 4. LIVE SIGNAL TABLE & PNL GRAPHS ---
if st.session_state.trade_log:
    st.divider()
    st.subheader("📊 Live Pod Signal Table")
    df_trades = pd.DataFrame(st.session_state.trade_log)
    
    # Display Table with Conditional Formatting
    st.dataframe(df_trades.style.applymap(
        lambda x: 'color: green' if x == "BUY" else 'color: red' if x == "SELL" else '', 
        subset=['Side']
    ))

    # PnL Graph
    st.subheader("📈 Cumulative Equity Curve")
    df_trades['Cumulative_PnL'] = df_trades['PnL'].cumsum()
    
    fig_pnl = go.Figure()
    fig_pnl.add_trace(go.Scatter(
        y=df_trades['Cumulative_PnL'], 
        mode='lines+markers', 
        fill='tozeroy',
        line=dict(color='#17B897')
    ))
    fig_pnl.update_layout(height=350, template="plotly_white", yaxis_title="Points")
    st.plotly_chart(fig_pnl, use_container_width=True)
else:
    st.info("No active trades. Click 'Run Live Session Scan' to fetch data.")
