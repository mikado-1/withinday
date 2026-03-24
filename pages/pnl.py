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
    st.session_state.active_trades = [] # Reset for fresh full-day scan
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        # Fetching enough data to ensure we have the full current day and previous day
        df = yf.download(TICKER, period="5d", interval="1m", auto_adjust=True, progress=False)
        daily_full = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily_full.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(daily_full.columns, pd.MultiIndex): daily_full.columns = daily_full.columns.get_level_values(0)

        df.index = df.index.tz_convert('Asia/Kolkata')
        today_date = df.index.date[-1]
        df_today = df[df.index.date == today_date].copy()
        
        # --- PREV DAY LEVELS (POD 3 & REVERSAL) ---
        completed_days = daily_full[daily_full.index.date < today_date]
        if completed_days.empty: continue
        prev_hi = float(completed_days.iloc[-1]['High'])
        prev_lo = float(completed_days.iloc[-1]['Low'])
        prev_close = float(completed_days.iloc[-1]['Close'])

        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])

        # Sigma & VWAP Calculation
        vol = float(completed_days['Close'].pct_change().tail(WINDOW).std())
        ub = float(max(day_open, prev_close) * (1 + BAND_MULT * vol))
        lb = float(min(day_open, prev_close) * (1 - BAND_MULT * vol))
        df_today['vwap'] = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()

        # Vectorized Scan Arrays
        close_vals = df_today['Close'].values
        high_vals = df_today['High'].values
        low_vals = df_today['Low'].values
        vwap_vals = df_today['vwap'].values
        
        # --- POD SCANS (Checking entire day's history) ---
        
        # 1. Sigma Pod History
        s_buy_mask = (close_vals > ub) & (close_vals > vwap_vals)
        s_sell_mask = (close_vals < lb) & (close_vals < vwap_vals)
        
        sigma_dir = None
        if s_buy_mask.any():
            idx = np.where(s_buy_mask)[0][0]
            add_trade(t_name, "SIGMA", "BUY", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_dir = "BUY"
        elif s_sell_mask.any():
            idx = np.where(s_sell_mask)[0][0]
            add_trade(t_name, "SIGMA", "SELL", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_dir = "SELL"

        # 2. Reversal Pod History (The Trap)
        if t_name != "INDIAVIX":
            r_buy_mask = (day_open < prev_hi) & (high_vals >= prev_hi)
            r_sell_mask = (day_open > prev_lo) & (low_vals <= prev_lo)
            
            if r_buy_mask.any():
                idx = np.where(r_buy_mask)[0][0]
                marker = "💎 ULTRA" if sigma_dir == "BUY" else "NORMAL"
                add_trade(t_name, "REVERSAL", "BUY", df_today.iloc[idx], ub, lb, marker, df_today, ltp, sl_ovr=day_open)
            elif r_sell_mask.any():
                idx = np.where(r_sell_mask)[0][0]
                marker = "💎 ULTRA" if sigma_dir == "SELL" else "NORMAL"
                add_trade(t_name, "REVERSAL", "SELL", df_today.iloc[idx], ub, lb, marker, df_today, ltp, sl_ovr=day_open)

        # --- CHARTING ---
        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            p_color = "green" if ltp >= day_open else "red"
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color=p_color, width=2)))
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['vwap'], name="VWAP", line=dict(color='blue', width=1, dash='dot')))
            fig.add_hline(y=ub, line_color="green", line_dash="dash", opacity=0.3)
            fig.add_hline(y=lb, line_color="red", line_dash="dash", opacity=0.3)
            fig.add_hline(y=prev_hi, line_color="orange", line_dash="dot", annotation_text="PH")
            fig.add_hline(y=prev_lo, line_color="orange", line_dash="dot", annotation_text="PL")
            fig.update_layout(height=230, margin=dict(l=0,r=0,t=10,b=10), template="plotly_white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, row, ub, lb, marker, df_today, ltp, sl_ovr=None):
    # Standard add_trade logic with Entry Time, LTP, T1, T2, T3, SL
    entry = float(row['Close'])
    entry_time = row.name.strftime('%H:%M')
    sl = float(sl_ovr) if sl_ovr else (lb if side == "BUY" else ub)
    
    risk = abs(entry - sl)
    capped_risk = min(risk, entry * 0.006)
    mult = 1 if side == "BUY" else -1
    t1, t2, t3 = entry + (capped_risk * 1.5 * mult), entry + (capped_risk * 2.5 * mult), entry + (capped_risk * 4.0 * mult)
    
    # Check what happened AFTER the entry trigger
    df_after = df_today[df_today.index >= row.name]
    h_since, l_since = df_after['High'].max(), df_after['Low'].min()

    status = "Active"
    pnl_val = (float(ltp) - entry) * mult

    if (side == "BUY" and l_since <= sl) or (side == "SELL" and h_since >= sl): 
        status = "❌ SL HIT"; pnl_val = -risk
    elif (side == "BUY" and h_since >= t3) or (side == "SELL" and l_since <= t3): 
        status = "💰 T3 HIT"; pnl_val = abs(t3 - entry)
    elif (side == "BUY" and h_since >= t2) or (side == "SELL" and l_since <= t2): 
        status = "✅ T2 HIT"; pnl_val = abs(t2 - entry)
    elif (side == "BUY" and h_since >= t1) or (side == "SELL" and l_since <= t1): 
        status = "🎯 T1 HIT"; pnl_val = abs(t1 - entry)

    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Time": entry_time, "Side": side, "Marker": marker,
        "LTP": round(ltp, 2), "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(t1, 2), "T2": round(t2, 2), "T3": round(t3, 2),
        "Status": status, "Live PnL": round(pnl_val, 2)
    })

# --- 3. UI ---
if st.sidebar.button("🚀 Run Full Day Scan"):
    run_integrated_analysis()

if st.session_state.active_trades:
    df_res = pd.DataFrame(st.session_state.active_trades)
    st.divider()
    st.metric("Total Points", f"{df_res['Live PnL'].sum():,.2f}")
    st.dataframe(df_res.style.applymap(
        lambda x: 'background-color: #ff4b4b; color: white' if 'SL' in str(x) else 'background-color: #09ab3b; color: white' if 'HIT' in str(x) else '', 
        subset=['Status']
    ).format(precision=2))
