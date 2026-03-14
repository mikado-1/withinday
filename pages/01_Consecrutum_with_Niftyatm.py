import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import requests
import os
import pytz
from datetime import datetime

# --- CONFIG ---
# Note: st.set_page_config is only needed here if running as a standalone app. 
# If this is inside the /pages folder, the main app's config takes priority.

# Use a relative path that works on Linux/Streamlit Cloud
BASE_PATH = "Nifty_Data" 
TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
BAND_MULT = 1.0
WINDOW = 14
IST = pytz.timezone('Asia/Kolkata')

# NSE API Headers
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest"
}

# --- NSE HELPERS ---
@st.cache_resource
def get_session():
    session = requests.Session()
    try: 
        session.get("https://www.nseindia.com/", headers=NSE_HEADERS, timeout=10)
    except: 
        pass
    return session

def get_nifty_open_price(session):
    url = "https://www.nseindia.com/api/allIndices"
    try:
        res = session.get(url, headers=NSE_HEADERS, timeout=10)
        if res.status_code == 200:
            indices = res.json().get('data', [])
            for index in indices:
                if index['index'] == "NIFTY 50":
                    val = index['open']
                    return float(str(val).replace(',', ''))
    except Exception as e:
        st.error(f"NSE Data Error: {e}")
        return None

def fetch_normalized_option(symbol, session):
    url = f"https://www.nseindia.com/api/chart-databyindex?index={symbol}"
    try:
        res = session.get(url, headers=NSE_HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json().get("grapthData", [])
            if not data: return None
            df = pd.DataFrame(data, columns=["ts", "price"])
            # Fix for Streamlit Cloud Linux Timezones
            df["time"] = pd.to_datetime(df["ts"], unit='ms').dt.tz_localize('UTC').dt.tz_convert(IST)
            df["time"] = df["time"].dt.tz_localize(None) 
            df["normalized"] = df["price"] - df["price"].iloc[0]
            return df
    except: 
        return None

def run_strategy(expiry_val):
    summary_list = []
    session = get_session()
    
    # Ensure directory exists on the cloud server
    if not os.path.exists(BASE_PATH):
        os.makedirs(BASE_PATH, exist_ok=True)

    # --- PART 1: ATM OPTION CROSSOVER ---
    st.write("### ⚖️ Nifty ATM Option Crossover")
    open_price = get_nifty_open_price(session)
    if open_price:
        fixed_atm = int(round(open_price / 50) * 50)
        st.caption(f"Nifty Open: {open_price} | Fixed ATM: {fixed_atm}")
        
        # Formatting symbols for NSE API
        expiry_str = expiry_val.replace("-", "").upper() # Adjust based on expected NSE format
        ce_sym = f"OPTIDXNIFTY{expiry_val}CE{float(fixed_atm):.2f}"
        pe_sym = f"OPTIDXNIFTY{expiry_val}PE{float(fixed_atm):.2f}"
        
        df_ce = fetch_normalized_option(ce_sym, session)
        df_pe = fetch_normalized_option(pe_sym, session)
        
        if df_ce is not None and df_pe is not None:
            fig_opt = go.Figure()
            fig_opt.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_opt.add_trace(go.Scatter(x=df_ce["time"], y=df_ce["normalized"], name="CE", line=dict(color='#4c4ccf', width=2)))
            fig_opt.add_trace(go.Scatter(x=df_pe["time"], y=df_pe["normalized"], name="PE", line=dict(color='#00bfff', width=2)))
            fig_opt.update_layout(height=350, plot_bgcolor='white', hovermode="x unified")
            st.plotly_chart(fig_opt, use_container_width=True)
    st.divider()

    # --- PART 2: CONCRETUM LOGIC ---
    st.write("### 📈 Index Strategy Analysis")
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        # Fetching data using yfinance
        df = yf.download(TICKER, period="5d", interval="1m", auto_adjust=True, progress=False)
        daily_data = yf.download(TICKER, period="1y", interval="1d", auto_adjust=True, progress=False)
        
        if df.empty or daily_data.empty: 
            st.warning(f"No data for {TICKER}")
            continue
            
        # Clean multi-index columns if they exist
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df.index = df.index.tz_convert(IST)
        daily_data['returns'] = daily_data['Close'].pct_change()
        dma_20 = daily_data['Close'].rolling(window=20).mean().iloc[-1]

        # Calculation logic
        df['day'] = df.index.date
        df['day_open'] = df.groupby('day')['Open'].transform('first')
        df['move_open'] = (df['Close'] / df['day_open'] - 1).abs()
        
        trade_date_ist = df.index[-1].date()
        df_today = df[df['day'] == trade_date_ist].copy()
        
        # Using Plotly for better cloud rendering instead of Matplotlib if preferred
        with cols[i]:
            st.subheader(TICKER.replace("^", ""))
            # Create a simple sparkline/plot
            st.line_chart(df_today['Close'])
            
            last_row = df_today.iloc[-1]
            status = "Bullish" if last_row['Close'] > dma_20 else "Bearish"
            st.metric("Price", f"{last_row['Close']:.2f}", f"{status}")

# --- STREAMLIT UI ---
st.sidebar.header("Controls")
expiry_input = st.sidebar.text_input("Option Expiry (DD-MMM-YYYY)", "26Mar2026")

if st.sidebar.button("Fetch & Calculate"):
    run_strategy(expiry_input)
else:
    st.info("👈 Set the Expiry and click 'Fetch & Calculate' to run.")
