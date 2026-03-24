import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import pytz

# --- 1. CONFIG ---
st.set_page_config(page_title="Alpha Pod Dashboard", layout="wide")
TICKERS = ["^INDIAVIX", "^NSEI", "^NSEBANK"]
IST = pytz.timezone('Asia/Kolkata')
BAND_MULT = 1.0
WINDOW = 14

if 'active_trades' not in st.session_state:
    st.session_state.active_trades = []

# --- 2. CORE ENGINE ---
def run_integrated_analysis():
    st.session_state.active_trades = [] 
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        
        # Download and Clean Columns immediately
        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily.empty: continue
        
        # FIX: Flatten Multi-Index columns if they exist
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(daily.columns, pd.MultiIndex): daily.columns = daily.columns.get_level_values(0)

        df.index = df.index.tz_convert('Asia/Kolkata')
        df_today = df[df.index.date == df.index.date[-1]].copy()
        
        # Scalar Levels
        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])
        prev_hi = float(daily['High'].iloc[-2])
        prev_lo = float(daily['Low'].iloc[-2])
        prev_close = float(daily['Close'].iloc[-2])

        # Sigma & VWAP (Calculated as 1D Series)
        vol = float(daily['Close'].pct_change().tail(WINDOW).std())
        ub = float(max(day_open, prev_close) * (1 + BAND_MULT * vol))
        lb = float(min(day_open, prev_close) * (1 - BAND_MULT * vol))
        
        # Ensure VWAP is a 1D Series
        pv = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum()
        v = df_today['Volume'].replace(0,1).cumsum()
        df_today['vwap'] = pv / v

        # --- POD TRIGGERS (Using .values to avoid alignment errors) ---
        close_vals = df_today['Close'].values
        vwap_vals = df_today['vwap'].values
        
        # 1. SIGMA POD
        s_buy_mask = (close_vals > ub) & (close_vals > vwap_vals)
        s_sell_mask = (close_vals < lb) & (close_vals < vwap_vals)
        
        sigma_hit = None
        if s_buy_mask.any():
            idx = np.where(s_buy_mask)[0][0]
            add_trade(t_name, "SIGMA", "BUY", df_today.iloc[idx], ub, lb, "NORMAL", df_today)
            sigma_hit = "BUY"
        elif s_sell_mask.any():
            idx = np.where(s_sell_mask)[0][0]
            add_trade(t_name, "SIGMA", "SELL", df_today.iloc[idx], ub, lb, "NORMAL", df_today)
            sigma_hit = "SELL"

        # 2. REVERSAL POD
        if t_name != "INDIAVIX":
            r_buy_mask = (day_open < prev_hi) & (close_vals > prev_hi) & (close_vals > day_open)
            r_sell_mask = (day_open > prev_lo) & (close_vals < prev_lo) & (close_vals < day_open)
            
            if r_buy_mask.any():
                idx = np.where(r_buy_mask)[0][0]
                marker = "💎 ULTRA" if sigma_hit == "BUY" else "NORMAL"
                add_trade(t_name, "REVERSAL", "BUY", df_today.iloc[idx], ub, lb, marker, df_today, sl_override=day_open)
            elif r_sell_mask.any():
                idx = np.where(r_sell_mask)[0][0]
                marker = "💎 ULTRA" if sigma_hit == "SELL" else "NORMAL"
                add_trade(t_name, "REVERSAL", "SELL", df_today.iloc[idx], ub, lb, marker, df_today, sl_override=day_open)

        # 3. GAP POD
        if t_name != "INDIAVIX":
            if day_open > prev_hi and ltp > prev_hi:
                add_trade(t_name, "GAP", "BUY", df_today.iloc[-1], ub, lb, "NORMAL", df_today, sl_override=prev_lo)
            elif day_open < prev_lo and ltp < prev_lo:
                add_trade(t_name, "GAP", "SELL", df_today.iloc[-1], ub, lb, "NORMAL", df_today, sl_override=prev_hi)

        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            fig = go.Figure(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, trigger_row, ub, lb, marker, df_today, sl_override=None):
    if any(t['Ticker'] == ticker and t['Pod'] == pod for t in st.session_state.active_trades): return
    
    entry = float(trigger_row['Close'])
    trigger_time = trigger_row.name
    sl = float(sl_override) if sl_override is not None else (lb if side == "BUY" else ub)
    risk = max(abs(entry - sl), 1.0)
    mult = 1 if side == "BUY" else -1
    
    t1, t2, t3 = entry + (risk * 1.5 * mult), entry + (risk * 2.5 * mult), entry + (risk * 4.0 * mult)
    
    # Analyze all prices AFTER trigger
    df_after = df_today[df_today.index >= trigger_time]
    high_since = df_after['High'].max()
    low_since = df_after['Low'].min()

    # Status Logic (Session-Wide)
    status = "Active"
    if (side == "BUY" and low_since <= sl) or (side == "SELL" and high_since >= sl): status = "❌ SL HIT"
    elif (side == "BUY" and high_since >= t3) or (side == "SELL" and low_since <= t3): status = "💰 T3 HIT"
    elif (side == "BUY" and high_since >= t2) or (side == "SELL" and low_since <= t2): status = "✅ T2 HIT"
    elif (side == "BUY" and high_since >= t1) or (side == "SELL" and low_since <= t1): status = "🎯 T1 HIT"

    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(t1, 2), "T2": round(t2, 2), "T3": round(t3, 2),
        "Status": status, "PnL": round((df_today['Close'].iloc[-1] - entry) * mult, 2)
    })

# --- UI ---
if st.sidebar.button("🔍 Run Session Analysis"):
    run_integrated_analysis()

if st.session_state.active_trades:
    st.divider()
    st.subheader("🏢 Session-Wide Target Tracker")
    df_results = pd.DataFrame(st.session_state.active_trades)
    
    def color_status(val):
        color = 'red' if 'SL' in val else 'green' if 'HIT' in val else 'orange'
        return f'background-color: {color}; color: white'

    st.dataframe(df_results.style.applymap(color_status, subset=['Status']).format(precision=2))
