import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import pytz
from datetime import datetime, date

# --- CONFIG ---
st.set_page_config(page_title="Triple-Pod Alpha Engine", layout="wide")
BASE_PATH = "./Nifty_Data/" 
TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
IST = pytz.timezone('Asia/Kolkata')
BAND_MULT = 1.0
WINDOW = 14
LOG_FILES = {"GAP": "journal_gap.csv", "SIGMA": "journal_sigma.csv", "REVERSAL": "journal_reversal.csv"}

# --- INITIALIZE SESSION STATE ---
if 'auto_trades' not in st.session_state:
    st.session_state.auto_trades = {} 
if 'trades_completed' not in st.session_state:
    st.session_state.trades_completed = {t.replace("^", ""): [] for t in TICKERS}

# --- EXECUTION ENGINE ---
def execute_trade(ticker, side, logic, entry, sl, tsl=None, day_hi=None, day_lo=None, is_confluence=False):
    trade_id = f"{ticker}_{logic}"
    risk = max(abs(entry - sl), 20)
    
    # --- CONVICTION MARKER LOGIC ---
    conviction = "NORMAL"
    if logic == "REVERSAL":
        # Ultra High is a marker if Reversal happens while Sigma is also triggering
        conviction = "💎 ULTRA HIGH" if is_confluence else "NORMAL"

    # --- 3-STAGE EXIT TARGETS ---
    if logic == "GAP":
        t1, t2 = entry + risk if side=="BUY" else entry - risk, entry + (risk*2) if side=="BUY" else entry - (risk*2)
        t3_label = "3:20 PM Exit"
    elif logic == "REVERSAL":
        t1 = entry + (risk * 1.5) if side == "BUY" else entry - (risk * 1.5)
        t2 = entry + (risk * 2.5) if side == "BUY" else entry - (risk * 2.5)
        t3_label = f"Day {'High' if side=='BUY' else 'Low'}"
    else: # SIGMA
        t1, t2 = entry + risk if side=="BUY" else entry - risk, entry + (risk * 1.5) if side=="BUY" else entry - (risk * 1.5)
        t3_label = "3:20 PM Exit"

    st.session_state.auto_trades[trade_id] = {
        'Ticker': ticker, 'Type': side, 'Logic': logic, 'Marker': conviction,
        'Entry': round(entry, 2), 'SL': round(sl, 2), 'TSL': round(tsl, 2) if tsl else None,
        'T1': round(t1, 2), 'T2': round(t2, 2), 'T3_Target': t3_label,
        'Status': "ACTIVE", 'Time': datetime.now(IST).strftime("%H:%M")
    }
    st.session_state.trades_completed[ticker].append(logic)

# --- MAIN STRATEGY LOOP ---
def run_integrated_strategy():
    now_ist = datetime.now(IST)
    trade_window_open = (now_ist.hour >= 10)
    
    st.write(f"### 🛡️ Live Triple-Pod Monitor | {now_ist.strftime('%H:%M:%S')}")
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        df = yf.download(TICKER, period="5d", interval="1m", auto_adjust=True, progress=False)
        daily = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)
        if df.empty or daily.empty: continue
        
        df.index = df.index.tz_convert('Asia/Kolkata')
        df_today = df[df.index.date == now_ist.date()].copy()
        if df_today.empty: continue

        # Levels
        ltp = df_today['Close'].iloc[-1]
        day_open = df_today['Open'].iloc[0]
        day_hi, day_lo = df_today['High'].max(), df_today['Low'].min()
        prev_hi, prev_lo = daily['High'].iloc[-2], daily['Low'].iloc[-2]
        prev_close = daily['Close'].iloc[-2]
        
        # Sigma Calculation
        vol = daily['Close'].pct_change().tail(WINDOW).std()
        ub = max(day_open, prev_close) * (1 + BAND_MULT * vol)
        lb = min(day_open, prev_close) * (1 - BAND_MULT * vol)
        vwap = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()
        
        # Sigma Status (For Confluence)
        sigma_buy = (ltp > ub and ltp > vwap.iloc[-1])
        sigma_sell = (ltp < lb and ltp < vwap.iloc[-1])

        # --- POD 1: GAP (9:15+) ---
        if "GAP" not in st.session_state.trades_completed[t_name] and t_name != "INDIAVIX":
            if day_open < prev_lo and ltp < day_open and ltp < prev_lo:
                execute_trade(t_name, "SELL", "GAP", ltp, prev_hi, tsl=day_open)
            elif day_open > prev_hi and ltp > day_open and ltp > prev_hi:
                execute_trade(t_name, "BUY", "GAP", ltp, prev_lo, tsl=day_open)

        # --- POD 2: SIGMA (10:00+) ---
        if trade_window_open and "SIGMA" not in st.session_state.trades_completed[t_name]:
            if sigma_buy: execute_trade(t_name, "BUY", "SIGMA", ltp, lb)
            elif sigma_sell: execute_trade(t_name, "SELL", "SIGMA", ltp, ub)

        # --- POD 3: REVERSAL (10:00+) ---
        if trade_window_open and "REVERSAL" not in st.session_state.trades_completed[t_name] and t_name != "INDIAVIX":
            # REVERSAL LONG
            if day_open < prev_hi and ltp > day_open and ltp > prev_hi:
                execute_trade(t_name, "BUY", "REVERSAL", ltp, day_open, is_confluence=sigma_buy)
            # REVERSAL SHORT
            elif day_open > prev_lo and ltp < day_open and ltp < prev_lo:
                execute_trade(t_name, "SELL", "REVERSAL", ltp, day_open, is_confluence=sigma_sell)

        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            st.caption(f"Day Open: {day_open:.0f} | Prev High: {prev_hi:.0f}")

# --- DASHBOARD ---
def show_dashboard():
    st.divider()
    st.write("### 📊 Triple-Pod Trade Tracker")
    tabs = st.tabs(["🚀 Gap Logic", "⚡ Sigma Logic", "🔄 Reversal Logic"])
    for i, logic in enumerate(["GAP", "SIGMA", "REVERSAL"]):
        with tabs[i]:
            pod_trades = [v for k, v in st.session_state.auto_trades.items() if v['Logic'] == logic]
            if pod_trades:
                st.dataframe(pd.DataFrame(pod_trades), use_container_width=True)
            else:
                st.info(f"No active trades for {logic}.")

# --- APP UI ---
if st.sidebar.button("🔍 Run Full Scan"):
    run_integrated_strategy()
    show_dashboard()

if st.sidebar.button("🔴 Reset System"):
    st.session_state.auto_trades = {}
    st.session_state.trades_completed = {t.replace("^", ""): [] for t in TICKERS}
    st.rerun()
