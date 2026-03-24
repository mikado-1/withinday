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

# Initialize session state for persistent tracking
if 'active_trades' not in st.session_state:
    st.session_state.active_trades = []

# --- 2. CORE ENGINE ---
def run_integrated_analysis(reset_history=False):
    if reset_history:
        st.session_state.active_trades = []
    
    # We use a temporary list to avoid duplicates during a single scan
    current_scan_results = []
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily_full = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily_full.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(daily_full.columns, pd.MultiIndex): daily_full.columns = daily_full.columns.get_level_values(0)

        df.index = df.index.tz_convert('Asia/Kolkata')
        today_date = df.index.date[-1]
        df_today = df[df.index.date == today_date].copy()
        
        # --- PREV DAY LEVELS ---
        completed_days = daily_full[daily_full.index.date < today_date]
        if completed_days.empty: continue
        prev_hi = float(completed_days.iloc[-1]['High'])
        prev_lo = float(completed_days.iloc[-1]['Low'])
        prev_close = float(completed_days.iloc[-1]['Close'])

        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])

        # Sigma & VWAP
        vol = float(completed_days['Close'].pct_change().tail(WINDOW).std())
        ub = float(max(day_open, prev_close) * (1 + BAND_MULT * vol))
        lb = float(min(day_open, prev_close) * (1 - BAND_MULT * vol))
        df_today['vwap'] = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()

        close_vals = df_today['Close'].values
        high_vals = df_today['High'].values
        low_vals = df_today['Low'].values
        
        # --- SCAN LOGIC ---
        sigma_hit = "BUY" if (close_vals > ub).any() else "SELL" if (close_vals < lb).any() else None
        
        # 1. Sigma Pod
        if (close_vals > ub).any():
            idx = np.where(close_vals > ub)[0][0]
            add_trade(t_name, "SIGMA", "BUY", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
        elif (close_vals < lb).any():
            idx = np.where(close_vals < lb)[0][0]
            add_trade(t_name, "SIGMA", "SELL", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)

        # 2. Reversal Pod
        if t_name != "INDIAVIX":
            r_buy = (day_open < prev_hi) & (high_vals >= prev_hi)
            r_sell = (day_open > prev_lo) & (low_vals <= prev_lo)
            if r_buy.any():
                idx = np.where(r_buy)[0][0]
                add_trade(t_name, "REVERSAL", "BUY", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="BUY" else "NORMAL", df_today, ltp, sl_ovr=day_open)
            elif r_sell.any():
                idx = np.where(r_sell)[0][0]
                add_trade(t_name, "REVERSAL", "SELL", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="SELL" else "NORMAL", df_today, ltp, sl_ovr=day_open)

        # --- GRAPHING ---
        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            line_color = "green" if ltp >= day_open else "red"
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color=line_color, width=2)))
            fig.add_trace(go.Scatter(x=df_today.index, y=df_today['vwap'], name="VWAP", line=dict(color='blue', width=1, dash='dot')))
            fig.add_hline(y=ub, line_color="green", line_dash="dash", opacity=0.3)
            fig.add_hline(y=lb, line_color="red", line_dash="dash", opacity=0.3)
            fig.add_hline(y=prev_hi, line_color="orange", line_dash="dot", opacity=0.5)
            fig.add_hline(y=prev_lo, line_color="orange", line_dash="dot", opacity=0.5)
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=10,b=10), template="plotly_white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, row, ub, lb, marker, df_today, ltp, sl_ovr=None):
    # Prevent duplicate entries for the same Ticker + Pod in the same session
    if any(t['Ticker'] == ticker and t['Pod'] == pod for t in st.session_state.active_trades): return
    
    entry = float(row['Close'])
    entry_time = row.name.strftime('%H:%M')
    sl = float(sl_ovr) if sl_ovr else (lb if side == "BUY" else ub)
    
    risk = abs(entry - sl)
    capped_risk = min(risk, entry * 0.006)
    mult = 1 if side == "BUY" else -1
    t1, t2, t3 = entry + (capped_risk * 1.5 * mult), entry + (capped_risk * 2.5 * mult), entry + (capped_risk * 4.0 * mult)
    
    df_after = df_today[df_today.index >= row.name]
    h_since, l_since = df_after['High'].max(), df_after['Low'].min()

    status = "Active"
    pnl_val = (float(ltp) - entry) * mult

    # Logic to "Lock" the status and P&L once a hit occurs
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
st.sidebar.title("Controls")
if st.sidebar.button("🚀 Run Scan"):
    run_integrated_analysis(reset_history=False)

if st.sidebar.button("🗑️ Clear History"):
    st.session_state.active_trades = []
    st.rerun()

if st.session_state.active_trades:
    df_res = pd.DataFrame(st.session_state.active_trades)
    st.divider()
    st.metric("Total Session P&L", f"{df_res['Live PnL'].sum():,.2f} Points")
    
    st.subheader("🏢 Comprehensive Pod History")
    st.dataframe(df_res.style.applymap(
        lambda x: 'background-color: #ff4b4b; color: white' if 'SL' in str(x) else 'background-color: #09ab3b; color: white' if 'HIT' in str(x) else '', 
        subset=['Status']
    ).format(precision=2))
else:
    st.info("No triggers recorded. Click 'Run Scan' to fetch data.")
