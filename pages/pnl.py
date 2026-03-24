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
        df.index = df.index.tz_convert('Asia/Kolkata')
        df_today = df[df.index.date == df.index.date[-1]].copy()
        
        # Scalar Levels
        ltp = float(df_today['Close'].iloc[-1])
        day_open = float(df_today['Open'].iloc[0])
        prev_hi = float(daily['High'].iloc[-2])
        prev_lo = float(daily['Low'].iloc[-2])
        prev_close = float(daily['Close'].iloc[-2])

        # Sigma & VWAP
        vol = float(daily['Close'].pct_change().tail(WINDOW).std())
        ub = max(day_open, prev_close) * (1 + BAND_MULT * vol)
        lb = min(day_open, prev_close) * (1 - BAND_MULT * vol)
        df_today['vwap'] = (df_today['Close'] * df_today['Volume'].replace(0,1)).cumsum() / df_today['Volume'].replace(0,1).cumsum()

        # --- POD TRIGGERS ---
        # Find first minute where price crossed the Sigma Band + VWAP
        s_buy_df = df_today[(df_today['Close'] > ub) & (df_today['Close'] > df_today['vwap'])]
        s_sell_df = df_today[(df_today['Close'] < lb) & (df_today['Close'] < df_today['vwap'])]
        sigma_hit = "BUY" if not s_buy_df.empty else "SELL" if not s_sell_df.empty else None

        # 1. SIGMA POD
        if sigma_hit == "BUY":
            add_trade(t_name, "SIGMA", "BUY", s_buy_df.iloc[0], ub, lb, "NORMAL", df_today, s_buy_df.index[0])
        elif sigma_hit == "SELL":
            add_trade(t_name, "SIGMA", "SELL", s_sell_df.iloc[0], ub, lb, "NORMAL", df_today, s_sell_df.index[0])

        # 2. REVERSAL POD
        if t_name != "INDIAVIX":
            r_buy_df = df_today[(day_open < prev_hi) & (df_today['Close'] > prev_hi) & (df_today['Close'] > day_open)]
            r_sell_df = df_today[(day_open > prev_lo) & (df_today['Close'] < prev_lo) & (df_today['Close'] < day_open)]
            
            if not r_buy_df.empty:
                marker = "💎 ULTRA" if sigma_hit == "BUY" else "NORMAL"
                add_trade(t_name, "REVERSAL", "BUY", r_buy_df.iloc[0], ub, lb, marker, df_today, r_buy_df.index[0], sl_override=day_open)
            elif not r_sell_df.empty:
                marker = "💎 ULTRA" if sigma_hit == "SELL" else "NORMAL"
                add_trade(t_name, "REVERSAL", "SELL", r_sell_df.iloc[0], ub, lb, marker, df_today, r_sell_df.index[0], sl_override=day_open)

        with cols[i]:
            st.metric(t_name, f"{ltp:.2f}")
            fig = go.Figure(go.Scatter(x=df_today.index, y=df_today['Close'], name="Price", line=dict(color='black')))
            fig.add_hline(y=ub, line_color="green", line_dash="dot")
            fig.add_hline(y=lb, line_color="red", line_dash="dot")
            fig.update_layout(height=200, margin=dict(l=0,r=0,t=20,b=0), template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

def add_trade(ticker, pod, side, trigger_row, ub, lb, marker, df_today, trigger_time, sl_override=None):
    if any(t['Ticker'] == ticker and t['Pod'] == pod for t in st.session_state.active_trades): return
    
    entry = float(trigger_row['Close'])
    sl = sl_override if sl_override else (lb if side == "BUY" else ub)
    risk = abs(entry - sl)
    mult = 1 if side == "BUY" else -1
    
    t1, t2, t3 = entry + (risk * 1.5 * mult), entry + (risk * 2.5 * mult), entry + (risk * 4.0 * mult)
    
    # Analyze all prices AFTER the trigger time
    df_after = df_today[df_today.index >= trigger_time]
    max_reached = df_after['High'].max() if side == "BUY" else df_after['Low'].min()
    min_reached = df_after['Low'].min() if side == "BUY" else df_after['High'].max()

    # Determine Status based on session extremes
    status = "Active"
    if (side == "BUY" and min_reached <= sl) or (side == "SELL" and min_reached >= sl): status = "❌ SL HIT"
    elif (side == "BUY" and max_reached >= t3) or (side == "SELL" and max_reached <= t3): status = "💰 T3 HIT"
    elif (side == "BUY" and max_reached >= t2) or (side == "SELL" and max_reached <= t2): status = "✅ T2 HIT"
    elif (side == "BUY" and max_reached >= t1) or (side == "SELL" and max_reached <= t1): status = "🎯 T1 HIT"

    st.session_state.active_trades.append({
        "Ticker": ticker, "Pod": pod, "Side": side, "Marker": marker,
        "Entry": round(entry, 2), "SL": round(sl, 2),
        "T1": round(t1, 2), "T2": round(t2, 2), "T3": round(t3, 2),
        "Status": status, "Points": round((df_today['Close'].iloc[-1] - entry) * mult, 2)
    })

# --- 3. UI ---
if st.sidebar.button("🔍 Run Session Analysis", on_click=run_integrated_analysis):
    pass

if st.session_state.active_trades:
    st.divider()
    st.subheader("🏢 Session-Wide Target Tracker")
    df_pnl = pd.DataFrame(st.session_state.active_trades)
    
    def style_status(val):
        color = 'red' if 'SL' in val else 'green' if 'HIT' in val else 'gray'
        return f'background-color: {color}; color: white; font-weight: bold'

    st.dataframe(df_pnl.style.applymap(style_status, subset=['Status']).format(precision=2))

    st.subheader("📉 Cumulative Session Points")
    df_pnl['Cum_Points'] = df_pnl['Points'].cumsum()
    st.plotly_chart(go.Figure(go.Scatter(y=df_pnl['Cum_Points'], fill='tozeroy', line=dict(color='#00CC96'))).update_layout(height=250), use_container_width=True)
