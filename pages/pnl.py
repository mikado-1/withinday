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
        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily = yf.download(TICKER, period="1mo", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df.index = df.index.tz_convert('Asia/Kolkata')
        df_today = df[df.index.date == df.index.date[-1]].copy()
        if df_today.empty: continue
        
        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])
        prev_hi = float(daily['High'].iloc[-2])
        prev_lo = float(daily['Low'].iloc[-2])
        prev_close = float(daily['Close'].iloc[-2])

        # Sigma & VWAP
        vol = float(daily['Close'].pct_change().tail(WINDOW).std())
        ub = float(max(day_open, prev_close) * (1 + BAND_MULT * vol))
        lb = float(min(day_open, prev_close) * (1 - BAND_MULT * vol))
        df_today['vwap'] = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()

        close_vals = df_today['Close'].values
        vwap_vals = df_today['vwap'].values
        
        # --- POD 1: SIGMA ---
        s_buy = (close_vals > ub) & (close_vals > vwap_vals)
        s_sell = (close_vals < lb) & (close_vals < vwap_vals)
        sigma_hit = None
        
        if s_buy.any():
            idx = np.where(s_buy)[0][0]
            add_trade(t_name, "SIGMA", "BUY", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_hit = "BUY"
        elif s_sell.any():
            idx = np.where(s_sell)[0][0]
            add_trade(t_name, "SIGMA", "SELL", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_hit = "SELL"

        # --- POD 2: REVERSAL ---
        if t_name != "INDIAVIX":
            r_buy = (day_open < prev_hi) & (close_vals > prev_hi) & (close_vals > day_open)
            r_sell = (day_open > prev_lo) & (close_vals < prev_lo) & (close_vals < day_open)
            
            if r_buy.any():
                idx = np.where(r_buy)[0][0]
                add_trade(t_name, "REVERSAL", "BUY", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="BUY" else "NORMAL", df_today, ltp, sl_ovr=day_open, trig_pt=prev_hi)
            elif r_sell.any():
                idx = np.where(r_sell)[0][0]
                add_trade(t_name, "REVERSAL", "SELL", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="SELL" else "NORMAL", df_today, ltp, sl_ovr=day_open, trig_pt=prev_lo)

        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            fig = go.Figure(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=180, margin=dict(l=0,r=0,t=10,b=10), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, row, ub, lb, marker, df_today, ltp, sl_ovr=None, trig_pt=None):
    if any(t['Ticker'] == ticker and t['Pod'] == pod for t in st.session_state.active_trades): return
    
    # Force float to prevent P&L calculation errors
    entry = float(row['Close'])
    sl = float(sl_ovr) if sl_ovr else (float(lb) if side == "BUY" else float(ub))
    
    # Target Capping
    risk = abs(entry - sl)
    capped_risk = min(risk, entry * 0.006)
    mult = 1 if side == "BUY" else -1
    t1, t2, t3 = entry + (capped_risk * 1.5 * mult), entry + (capped_risk * 2.5 * mult), entry + (capped_risk * 4.0 * mult)
    
    # Session Analysis
    df_after = df_today[df_today.index >= row.name]
    h_since, l_since = df_after['High'].max(), df_after['Low'].min()

    # Fixed P&L Calculation: (Current Price - Entry Price) * Side
    current_pnl = (float(ltp) - entry) * mult

    status = "Active"
    if (side == "BUY" and l_since <= sl) or (side == "SELL" and h_since >= sl): status = "❌ SL HIT"
    elif (side == "BUY" and h_since >= t3) or (side == "SELL" and l_since <= t3): status = "💰 T3 HIT"
    elif (side == "BUY" and h_since >= t2) or (side == "SELL" and l_since <= t2): status = "✅ T2 HIT"
    elif (side == "BUY" and h_since >= t1) or (side == "SELL" and l_since <= t1): status = "🎯 T1 HIT"

    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Trigger Pt": round(trig_pt, 2) if trig_pt else "Open/Sigma",
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(t1, 2), "T2": round(t2, 2), "T3": round(t3, 2),
        "Status": status, "Live PnL": round(current_pnl, 2)
    })

# --- 3. UI ---
if st.sidebar.button("🚀 Run Full Scan"):
    run_integrated_analysis()

if st.session_state.active_trades:
    df_res = pd.DataFrame(st.session_state.active_trades)
    st.divider()
    
    # Metrics
    total_pnl = df_res['Live PnL'].sum()
    st.metric("Total Strategy P&L", f"{total_pnl:,.2f} Pts", delta=f"{total_pnl:,.2f}")

    # Results Table
    st.subheader("🏢 Comprehensive Pod & Reversal Tracker")
    st.dataframe(df_res.style.applymap(
        lambda x: 'background-color: #ff4b4b; color: white' if 'SL' in str(x) else 'background-color: #09ab3b; color: white' if 'HIT' in str(x) else '', 
        subset=['Status']
    ).format(precision=2))
else:
    st.info("No active pod triggers found. Run scan to check.")
