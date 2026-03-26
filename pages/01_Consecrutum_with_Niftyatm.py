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
st.set_page_config(page_title="Concretum & ATM Strategy", layout="wide")

BASE_PATH = "./Nifty_Data/" 
TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
BAND_MULT = 1.0
WINDOW = 14
IST = pytz.timezone('Asia/Kolkata')

# NSE API Headers
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.nseindia.com/get-quotes/derivatives?symbol=NIFTY",
    "X-Requested-With": "XMLHttpRequest"
}

# --- NSE HELPERS ---
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
                    return float(val.replace(',', '')) if isinstance(val, str) else float(val)
    except: 
        return None

def fetch_normalized_option(symbol, session):
    url = f"https://www.nseindia.com/api/chart-databyindex?index={symbol}"
    try:
        res = session.get(url, headers=NSE_HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json().get("grapthData", [])
            if not data: return None
            df = pd.DataFrame(data, columns=["ts", "price"])
            
            # TIMEZONE NAIVE FIX: 
            # 1. Convert timestamp to UTC-based datetime
            # 2. Add 5.5 hours manually to reach IST
            # 3. Strip timezone info (.tz_localize(None)) so Plotly doesn't shift it
            df["time"] = pd.to_datetime(df["ts"], unit='ms') + pd.Timedelta(hours=5, minutes=30)
            df["time"] = df["time"].dt.tz_localize(None) 
            
            df["normalized"] = df["price"] - df["price"].iloc[0]
            return df
    except: 
        return None

def run_strategy(expiry_val):
    summary_list = []
    session = get_session()
    
    summary_path = os.path.join(BASE_PATH, 'Daily_Summaries')
    os.makedirs(summary_path, exist_ok=True)

    # --- PART 1: ATM OPTION CROSSOVER (SMALL HEIGHT + FIXED TIME) ---
    st.write("### ⚖️ Nifty ATM Option Crossover")
    open_price = get_nifty_open_price(session)
    if open_price:
        fixed_atm = int(round(open_price / 50) * 50)
        st.caption(f"Nifty Open: {open_price} | Fixed ATM: {fixed_atm}")
        
        ce_sym = f"OPTIDXNIFTY{expiry_val}CE{float(fixed_atm):.2f}"
        pe_sym = f"OPTIDXNIFTY{expiry_val}PE{float(fixed_atm):.2f}"
        
        df_ce = fetch_normalized_option(ce_sym, session)
        df_pe = fetch_normalized_option(pe_sym, session)
        
        if df_ce is not None and df_pe is not None:
            fig_opt = go.Figure()
            fig_opt.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_opt.add_trace(go.Scatter(x=df_ce["time"], y=df_pe["normalized"], name="PE", line=dict(color='#4c4ccf', width=2)))
            fig_opt.add_trace(go.Scatter(x=df_pe["time"], y=df_ce["normalized"], name="CE", line=dict(color='#00bfff', width=2)))
            fig_opt.update_layout(
                height=300, 
                margin=dict(l=10, r=10, t=10, b=10), 
                plot_bgcolor='white', 
                hovermode="x unified",
                xaxis=dict(tickformat="%H:%M", type='date')
            )
            st.plotly_chart(fig_opt, use_container_width=True)
    st.divider()

    # --- PART 2: CONCRETUM LOGIC (SIDE-BY-SIDE COLUMNS) ---
    st.write("### 📈 Index Strategy Analysis")
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        folder_name = TICKER.replace("^", "")
        ticker_path = os.path.join(BASE_PATH, folder_name)
        os.makedirs(ticker_path, exist_ok=True)

        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily_data = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True, progress=False)
        
        if df.empty or daily_data.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(daily_data.columns, pd.MultiIndex): daily_data.columns = daily_data.columns.get_level_values(0)

        df.index = df.index.tz_convert('Asia/Kolkata')

        daily_data['returns'] = daily_data['Close'].pct_change()
        dma_20 = daily_data['Close'].rolling(window=20).mean().iloc[-1]
        vol_20d = daily_data['returns'].tail(20).std() * np.sqrt(252)

        df['day'] = df.index.date
        df['day_open'] = df.groupby('day')['Open'].transform('first')
        df['move_open'] = (df['Close'] / df['day_open'] - 1).abs()
        df['minute_of_day'] = (df.index.hour * 60 + df.index.minute) - (9 * 60 + 15)

        minute_groups = df.groupby('minute_of_day')
        df['sigma_open'] = minute_groups['move_open'].transform(lambda x: x.rolling(window=WINDOW, min_periods=1).mean().shift(1))

        trade_date_ist = df.index[-1].date()
        df_today = df[df['day'] == trade_date_ist].copy()
        df_today['sigma_open'] = df_today['sigma_open'].fillna(daily_data['returns'].tail(20).std())

        prev_close = float(daily_data['Close'].iloc[-2]) if daily_data.index[-1].date() >= trade_date_ist else float(daily_data['Close'].iloc[-1])

        df_today['ub'] = np.maximum(df_today['day_open'], prev_close) * (1 + BAND_MULT * df_today['sigma_open'])
        df_today['lb'] = np.minimum(df_today['day_open'], prev_close) * (1 - BAND_MULT * df_today['sigma_open'])

        safe_vol = df_today['Volume'].replace(0, 1)
        tp = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
        df_today['vwap'] = (tp * safe_vol).cumsum() / safe_vol.cumsum()

        df_today['signal_val'] = 0
        df_today.loc[(df_today['Close'] > df_today['ub']) & (df_today['Close'] > df_today['vwap']), 'signal_val'] = 1
        df_today.loc[(df_today['Close'] < df_today['lb']) & (df_today['Close'] < df_today['vwap']), 'signal_val'] = -1

        with cols[i]:
            fig, ax = plt.subplots(figsize=(5, 4))
            ax.plot(df_today.index, df_today['Close'], label='Price', color='black', linewidth=1)
            ax.plot(df_today.index, df_today['vwap'], label='VWAP', color='blue', linestyle='--', linewidth=0.8)
            ax.plot(df_today.index, df_today['ub'], color='green', alpha=0.3)
            ax.plot(df_today.index, df_today['lb'], color='red', alpha=0.3)
            ax.fill_between(df_today.index, df_today['ub'], df_today['Close'], where=(df_today['signal_val']==1), color='green', alpha=0.1)
            ax.fill_between(df_today.index, df_today['lb'], df_today['Close'], where=(df_today['signal_val']==-1), color='red', alpha=0.1)
            ax.set_title(f"{TICKER}", fontsize=10)
            ax.tick_params(labelsize=8)
            plt.xticks(rotation=45)
            st.pyplot(fig)
            plt.close(fig)

        last_row = df_today.iloc[-1]
        sig_text = "BUY" if last_row['signal_val'] == 1 else "SELL" if last_row['signal_val'] == -1 else "NEUTRAL"
        if TICKER == "^INDIAVIX": sig_text = "SELL" if last_row['signal_val'] == 1 else "BUY" if last_row['signal_val'] == -1 else "NEUTRAL"

        summary_list.append({
            'Ticker': folder_name, 'Price': round(last_row['Close'], 2),
            'Trend': "Bull" if last_row['Close'] > dma_20 else "Bear",
            'Signal': sig_text
        })

    # --- SUMMARY TABLE ---
    if summary_list:
        summary_df = pd.DataFrame(summary_list)
        fig_tbl, ax_tbl = plt.subplots(figsize=(10, 2))
        ax_tbl.axis('off')
        tbl = ax_tbl.table(cellText=summary_df.values, colLabels=summary_df.columns, cellLoc='center', loc='center')
        tbl.scale(1, 1.3)
        st.write("### Market Summary Table")
        st.pyplot(fig_tbl)
        plt.close(fig_tbl)

# --- STREAMLIT UI ---
st.sidebar.header("Controls")
expiry_input = st.sidebar.text_input("Option Expiry (DD-MM-YYYY)", "30-03-2026")
if st.sidebar.button("Fetch & Calculate"):
    run_strategy(expiry_input)
else:
    st.info("Set the Expiry and click 'Fetch & Calculate' to run.")
