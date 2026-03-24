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
        if isinstance(daily.columns, pd.MultiIndex): daily.columns = daily.columns.get_level_values(0)

        df.index = df.index.tz_convert('Asia/Kolkata')
        df_today = df[df.index.date == df.index.date[-1]].copy()
        
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
        
        # --- POD TRIGGER SCAN ---
        sigma_hit = None
        s_buy = (close_vals > ub) & (close_vals > vwap_vals)
        s_sell = (close_vals < lb) & (close_vals < vwap_vals)

        # 1. SIGMA POD
        if s_buy.any():
            idx = np.where(s_buy)[0][0]
            add_trade(t_name, "SIGMA", "BUY", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_hit = "BUY"
        elif s_sell.any():
            idx = np.where(s_sell)[0][0]
            add_trade(t_name, "SIGMA", "SELL", df_today.iloc[idx], ub, lb, "NORMAL", df_today, ltp)
            sigma_hit = "SELL"

        # 2. REVERSAL POD (Trigger points included)
        if t_name != "INDIAVIX":
            r_buy = (day_open < prev_hi) & (close_vals > prev_hi) & (close_vals > day_open)
            r_sell = (day_open > prev_lo) & (close_vals < prev_lo) & (close_vals < day_open)
            
            if r_buy.any():
                idx = np.where(r_buy)[0][0]
                add_trade(t_name, "REVERSAL", "BUY", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="BUY" else "NORMAL", df_today, ltp, sl_ovr=day_open, trig_pt=prev_hi)
            elif r_sell.any():
                idx = np.where(r_sell)[0][0]
                add_trade(t_name, "REVERSAL", "SELL", df_today.iloc[idx], ub, lb, "💎 ULTRA" if sigma_hit=="SELL" else "NORMAL", df_today, ltp, sl_ovr=day_open, trig_pt=prev_lo)

        # 3. GAP POD
        if t_name != "INDIAVIX":
            if day_open > prev_hi and ltp > prev_hi:
                add_trade(t_name, "GAP", "BUY", df_today.iloc[0], ub, lb, "NORMAL", df_today, ltp, sl_ovr=prev_lo)
            elif day_open < prev_lo and ltp < prev_lo:
                add_trade(t_name, "GAP", "SELL", df_today.iloc[0], ub, lb, "NORMAL", df_today, ltp, sl_ovr=prev_hi)

        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            fig = go.Figure(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, row, ub, lb, marker, df_today, ltp, sl_ovr=None, trig_pt=None):
    if any(t['Ticker'] == ticker and t['Pod'] == pod for t in st.session_state.active_trades): return
    
    entry = float(row['Close'])
    sl = float(sl_ovr) if sl_ovr else (lb if side == "BUY" else ub)
    
    # --- DYNAMIC TARGETS (Capped Risk) ---
    raw_risk = abs(entry - sl)
    capped_risk = min(raw_risk, entry * 0.006) # Targets capped at 0.6% move for realism
    
    mult = 1 if side == "BUY" else -1
    t1, t2, t3 = entry + (capped_risk * 1.5 * mult), entry + (capped_risk * 2.5 * mult), entry + (capped_risk * 4.0 * mult)
    
    # Session Extreme Scan (Since Trigger)
    df_after = df_today[df_today.index >= row.name]
    high_since, low_since = df_after['High'].max(), df_after['Low'].min()

    status = "Active"
    if (side == "BUY" and low_since <= sl) or (side == "SELL" and high_since >= sl): status = "❌ SL HIT"
    elif (side == "BUY" and high_since >= t3) or (side == "SELL" and low_since <= t3): status = "💰 T3 HIT"
    elif (side == "BUY" and high_since >= t2) or (side == "SELL" and low_since <= t2): status = "✅ T2 HIT"
    elif (side == "BUY" and high_since >= t1) or (side == "SELL" and low_since <= t1): status = "🎯 T1 HIT"

    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Trigger Pt": round(trig_pt, 2) if trig_pt else "Open/Sigma",
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(t1, 2), "T2": round(t2, 2), "T3": round(t3, 2),
        "Status": status, "Live PnL": round((ltp - entry) * mult, 2)
    })

# --- 3. UI ---
if st.sidebar.button("🔍 Run Session Scan"):
    run_integrated_analysis()

if st.session_state.active_trades:
    st.divider()
    df_res = pd.DataFrame(st.session_state.active_trades)
    
    # Metrics
    total_pts = df_res['Live PnL'].sum()
    st.metric("Total Strategy P&L (Points)", f"{total_pts:.2f} Pts", delta=f"{total_pts:.2f}")

    # Results Table
    st.subheader("🏢 Comprehensive Pod Tracker")
    st.dataframe(df_res.style.applymap(lambda x: 'background-color: #ff4b4b; color: white' if 'SL' in str(x) else 'background-color: #09ab3b; color: white' if 'HIT' in str(x) else '', subset=['Status']).format(precision=2))

    # P&L Curve
    st.subheader("📈 Session Cumulative P&L")
    df_res['Cum_Pts'] = df_res['Live PnL'].cumsum()
    st.plotly_chart(go.Figure(go.Scatter(y=df_res['Cum_Pts'], fill='tozeroy', line=dict(color='#00CC96', width=4))).update_layout(height=300), use_container_width=True)
