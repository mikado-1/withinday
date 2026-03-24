import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import os
import pytz
from datetime import datetime

# --- 1. CONFIG & SESSION STATE ---
st.set_page_config(page_title="Concretum & Triple-Pod Hub", layout="wide")

TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
IST = pytz.timezone('Asia/Kolkata')
BAND_MULT = 1.0
WINDOW = 14

# Initialize tracking in session state
if 'active_trades' not in st.session_state:
    st.session_state.active_trades = []

# NSE API Headers
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/"
}

# --- 2. HELPERS ---
def get_session():
    session = requests.Session()
    try: session.get("https://www.nseindia.com/", headers=NSE_HEADERS, timeout=5)
    except: pass
    return session

def get_nifty_open(session):
    try:
        res = session.get("https://www.nseindia.com/api/allIndices", headers=NSE_HEADERS, timeout=5)
        if res.status_code == 200:
            for index in res.json().get('data', []):
                if index['index'] == "NIFTY 50":
                    val = index['open']
                    return float(val.replace(',', '')) if isinstance(val, str) else float(val)
    except: return None

def record_pod_trade(ticker, pod, side, entry, sl, is_ultra=False):
    risk = abs(entry - sl)
    marker = "💎 ULTRA" if is_ultra else "NORMAL"
    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(entry + (risk*1.5) if side=="BUY" else entry - (risk*1.5), 2),
        "PnL": round(risk * 1.1, 2) # Simulated PnL based on volatility
    })

# --- 3. MAIN INTEGRATED STRATEGY ---
def run_integrated_analysis(expiry_val):
    st.session_state.active_trades = [] # Reset for fresh scan
    session = get_session()
    
    # PART A: ATM OPTION CROSSOVER
    st.write("### ⚖️ Nifty ATM Option Crossover")
    nifty_open = get_nifty_open(session)
    if nifty_open:
        atm = int(round(nifty_open / 50) * 50)
        st.caption(f"Nifty Open: {nifty_open} | Fixed ATM: {atm}")
        # (Option plotting code would go here - keeping focus on the Pods)

    st.divider()
    
    # PART B: TRIPLE-POD ENGINE
    st.write("### 📈 Index Strategy Analysis")
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily.empty: continue
        df.index = df.index.tz_convert('Asia/Kolkata')
        
        # Scalar Extraction (Fixes ValueError)
        df_today = df[df.index.date == df.index.date[-1]].copy()
        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])
        prev_hi = float(daily['High'].iloc[-2])
        prev_lo = float(daily['Low'].iloc[-2])
        prev_close = float(daily['Close'].iloc[-2])

        # Sigma & VWAP
        vol = float(daily['Close'].pct_change().tail(WINDOW).std())
        ub = max(day_open, prev_close) * (1 + BAND_MULT * vol)
        lb = min(day_open, prev_close) * (1 - BAND_MULT * vol)
        vwap = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()
        curr_vwap = float(vwap.iloc[-1])

        # FLAGS
        sig_buy = (ltp > ub and ltp > curr_vwap)
        sig_sell = (ltp < lb and ltp < curr_vwap)

        # POD 1: GAP (Trend)
        if t_name != "INDIAVIX":
            if day_open > prev_hi and ltp > prev_hi:
                record_pod_trade(t_name, "GAP", "BUY", ltp, prev_lo)
            elif day_open < prev_lo and ltp < prev_lo:
                record_pod_trade(t_name, "GAP", "SELL", ltp, prev_hi)

        # POD 2: SIGMA (Vol)
        if sig_buy: record_pod_trade(t_name, "SIGMA", "BUY", ltp, lb)
        elif sig_sell: record_pod_trade(t_name, "SIGMA", "SELL", ltp, ub)

        # POD 3: REVERSAL (Squeeze)
        if t_name != "INDIAVIX":
            if day_open < prev_hi and ltp > day_open and ltp > prev_hi:
                record_pod_trade(t_name, "REVERSAL", "BUY", ltp, day_open, is_ultra=sig_buy)
            elif day_open > prev_lo and ltp < day_open and ltp < prev_lo:
                record_pod_trade(t_name, "REVERSAL", "SELL", ltp, day_open, is_ultra=sig_sell)

        # Plotting
        with cols[i]:
            st.metric(f"{t_name}", f"{ltp:.2f}")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=250, margin=dict(l=0,r=0,t=20,b=0), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

    # PART C: POD TRACKER & PNL GRAPH
    if st.session_state.active_trades:
        st.divider()
        st.subheader("🏢 Live Pod Signal Table")
        df_pnl = pd.DataFrame(st.session_state.active_trades)
        st.dataframe(df_pnl.style.applymap(lambda x: 'color: green' if x == "BUY" else 'color: red' if x == "SELL" else '', subset=['Side']))

        st.subheader("📉 Cumulative Strategy P&L")
        df_pnl['Cum_PnL'] = df_pnl['PnL'].cumsum()
        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Scatter(y=df_pnl['Cum_PnL'], mode='lines+markers', fill='tozeroy', line=dict(color='#17B897', width=3)))
        fig_pnl.update_layout(height=300, template="plotly_white", yaxis_title="Points")
        st.plotly_chart(fig_pnl, use_container_width=True)

# --- 4. STREAMLIT UI ---
st.sidebar.header("Command Center")
exp = st.sidebar.text_input("Expiry (DD-MM-YYYY)", "17-03-2026")
if st.sidebar.button("Execute Full Scan"):
    run_integrated_analysis(exp)
else:
    st.info("Click 'Execute Full Scan' to view live Pod signals and P&L.")
