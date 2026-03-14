import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import timedelta
from sklearn.linear_model import LinearRegression

# --- CONFIG ---
st.set_page_config(page_title="BankNifty Momentum Pro", layout="wide")
COLOR_CE, COLOR_PE = "#00D4FF", "#4C4CCF"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/"
}

def get_session():
    s = requests.Session()
    try: s.get("https://www.nseindia.com/", headers=HEADERS, timeout=10)
    except: pass
    return s

def get_bn_open(session):
    url = "https://www.nseindia.com/api/allIndices"
    try:
        res = session.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            indices = res.json().get('data', [])
            for index in indices:
                # Changed from NIFTY 50 to NIFTY BANK
                if index['index'] == "NIFTY BANK":
                    val = index['open']
                    return float(val.replace(',', '')) if isinstance(val, str) else float(val)
    except: return None

def fetch_analysis(symbol, session):
    url = f"https://www.nseindia.com/api/chart-databyindex?index={symbol}"
    try:
        res = session.get(url, headers=HEADERS, timeout=5)
        if res.status_code != 200: return None
        raw_data = res.json().get("grapthData", [])
        if not raw_data or len(raw_data) < 2: return None
        
        df = pd.DataFrame(raw_data, columns=["ts", "price"])
        df["time"] = pd.to_datetime(df["ts"], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
        
        last_date = df['time'].dt.date.iloc[-1]
        df = df[df['time'].dt.date == last_date]
        
        if df.empty: return None

        open_val = df["price"].iloc[0]
        df["pct"] = ((df["price"] - open_val) / open_val) * 100
        df["velocity"] = df["pct"].diff().fillna(0).cumsum()
        
        y = df["pct"].values.reshape(-1, 1)
        X = np.arange(len(y)).reshape(-1, 1)
        model = LinearRegression().fit(X, y)
        
        return {
            "df": df[['time', 'pct', 'velocity']], 
            "slope": model.coef_[0][0], 
            "r2": model.score(X, y), 
            "last_pct": df["pct"].iloc[-1],
            "data_date": last_date
        }
    except: return None

# --- APP ENGINE ---
session = get_session()
bn_open = get_bn_open(session)

st.title("📈 BankNifty Last Session Momentum")

if bn_open:
    # BankNifty typically uses 100 point strike intervals
    atm_anchor = round(bn_open / 100) * 100
    strikes = [atm_anchor + (i * 100) for i in range(-5, 6)]
    
    with st.sidebar:
        expiry = st.text_input("Expiry (DD-MM-YYYY)", "19-03-2026")
        st.metric("BankNifty Open Anchor", bn_open)

    all_results, ce_trend_list, pe_trend_list, scanner_data = {}, [], [], []
    active_date = None

    with st.spinner("Retrieving BankNifty Data..."):
        for s in strikes:
            # Updated naming convention for BankNifty Options
            ce = fetch_analysis(f"OPTIDXBANKNIFTY{expiry}CE{float(s):.2f}", session)
            pe = fetch_analysis(f"OPTIDXBANKNIFTY{expiry}PE{float(s):.2f}", session)
            
            if ce and pe:
                active_date = ce['data_date']
                all_results[s] = {"ce": ce['df'], "pe": pe['df']}
                ce_trend_list.append(ce['df'].set_index('time')['velocity'])
                pe_trend_list.append(pe['df'].set_index('time')['velocity'])
                
                scanner_data.append({
                    "Strike": s, "CE ROI%": f"{ce['last_pct']:.1f}%",
                    "CE Day Slope": round(ce['slope'], 3), "CE R²": f"{ce['r2']:.2f}",
                    "PE ROI%": f"{pe['last_pct']:.1f}%", "PE Day Slope": round(pe['slope'], 3),
                    "PE R²": f"{pe['r2']:.2f}"
                })

    if active_date:
        st.info(f"📅 Displaying Data for: **{active_date.strftime('%d %b %Y')}**")

    if ce_trend_list and pe_trend_list:
        agg_ce = pd.concat(ce_trend_list, axis=1).sum(axis=1)
        agg_pe = pd.concat(pe_trend_list, axis=1).sum(axis=1)
        
        st.subheader("⏱ Phase Momentum Timeline (IST)")
        start_time = agg_ce.index[0]
        curr_time = agg_ce.index[-1]
        total_m = int((curr_time - start_time).total_seconds() / 60)
        phase_count = (total_m // 30) + 1
        
        for i in range(0, phase_count, 6):
            cols = st.columns(6)
            for j in range(6):
                p_idx = i + j
                if p_idx < phase_count:
                    target_time = start_time + timedelta(minutes=(p_idx + 1) * 30)
                    if curr_time >= target_time:
                        bias = "BULLISH" if agg_ce.asof(target_time) > agg_pe.asof(target_time) else "BEARISH"
                        color = "#28a745" if bias == "BULLISH" else "#dc3545"
                        with cols[j]:
                            st.markdown(f"""
                                <div style="background-color:{color}; padding:10px; border-radius:8px; text-align:center; color:white; margin-bottom:10px;">
                                    <small>{target_time.strftime('%I:%M %p')}</small><br>
                                    <b style="font-size:16px;">{bias}</b>
                                </div>
                                """, unsafe_allow_html=True)

        st.divider()
        st.subheader("📋 BankNifty R² & Slope Scanner")
        st.dataframe(pd.DataFrame(scanner_data), use_container_width=True, hide_index=True)

        st.divider()
        g1, g2 = st.columns(2)
        with g1:
            st.markdown(f"<h3 style='color:{COLOR_CE};'>CE Total Velocity</h3>", unsafe_allow_html=True)
            st.plotly_chart(go.Figure(go.Scatter(x=agg_ce.index, y=agg_ce, fill='tozeroy', line=dict(color=COLOR_CE))), use_container_width=True)
        with g2:
            st.markdown(f"<h3 style='color:{COLOR_PE};'>PE Total Velocity</h3>", unsafe_allow_html=True)
            st.plotly_chart(go.Figure(go.Scatter(x=agg_pe.index, y=agg_pe, fill='tozeroy', line=dict(color=COLOR_PE))), use_container_width=True)

        st.divider()
        st.subheader("📍 Individual Strike Profiles")
        sorted_s = sorted(all_results.keys())
        for i in range(0, len(sorted_s), 4):
            grid_cols = st.columns(4)
            for j in range(4):
                if i + j < len(sorted_s):
                    s = sorted_s[i + j]
                    with grid_cols[j]:
                        st.caption(f"Strike {s}")
                        f = go.Figure()
                        f.add_trace(go.Scatter(x=all_results[s]['ce']['time'], y=all_results[s]['ce']['velocity'], line=dict(color=COLOR_CE)))
                        f.add_trace(go.Scatter(x=all_results[s]['pe']['time'], y=all_results[s]['pe']['velocity'], line=dict(color=COLOR_PE)))
                        f.update_layout(height=160, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, plot_bgcolor="white")
                        st.plotly_chart(f, use_container_width=True)
else:
    st.error("Could not retrieve BankNifty Open price.")
