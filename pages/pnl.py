# --- INITIALIZE SESSION STATE FOR TRACKING ---
if 'active_trades' not in st.session_state:
    st.session_state.active_trades = []

def run_strategy(expiry_val):
    summary_list = []
    session = get_session()
    
    # --- PART 1: ATM OPTION CROSSOVER ---
    # (Keep your existing ATM Option Crossover code here)
    st.divider()

    # --- PART 2: INDEX STRATEGY & PODS ---
    st.write("### 📈 Index Strategy & Live Pods")
    cols = st.columns(3)

    for i, TICKER in enumerate(TICKERS):
        t_name = TICKER.replace("^", "")
        df = yf.download(TICKER, period="7d", interval="1m", auto_adjust=True, progress=False)
        daily_data = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True, progress=False)

        if df.empty or daily_data.empty: continue
        df.index = df.index.tz_convert('Asia/Kolkata')
        
        trade_date_ist = df.index[-1].date()
        df_today = df[df['day'] == trade_date_ist].copy()
        
        # --- LEVELS ---
        ltp = df_today['Close'].iloc[-1]
        day_open = df_today['Open'].iloc[0]
        prev_hi = daily_data['High'].iloc[-2]
        prev_lo = daily_data['Low'].iloc[-2]
        prev_close = daily_data['Close'].iloc[-2]
        
        # Sigma Calculation (Using your existing logic)
        # ub = ..., lb = ... (Ensuring these variables are calculated as per your existing snippet)
        
        # --- POD TRIGGER LOGIC ---
        new_signal = None
        
        # 1. GAP POD (Trend)
        if t_name != "INDIAVIX":
            if day_open > prev_hi and ltp > prev_hi: new_signal = ("Gap", "BUY")
            elif day_open < prev_lo and ltp < prev_lo: new_signal = ("Gap", "SELL")

        # 2. SIGMA POD (Vol)
        # Using your signal_val logic
        current_sig = 1 if (ltp > ub and ltp > df_today['vwap'].iloc[-1]) else -1 if (ltp < lb and ltp < df_today['vwap'].iloc[-1]) else 0
        if current_sig != 0: new_signal = ("Sigma", "BUY" if current_sig == 1 else "SELL")

        # 3. REVERSAL POD (Squeeze)
        if t_name != "INDIAVIX":
            if day_open < prev_hi and ltp > day_open and ltp > prev_hi:
                new_signal = ("Reversal", "BUY")
            elif day_open > prev_lo and ltp < day_open and ltp < prev_lo:
                new_signal = ("Reversal", "SELL")

        # --- SIMULATE TRADE EXECUTION ---
        if new_signal:
            pod_type, side = new_signal
            # Avoid duplicate trades for the same ticker/pod in one session
            exists = any(t['Ticker'] == t_name and t['Pod'] == pod_type for t in st.session_state.active_trades)
            if not exists:
                risk = max(abs(ltp - day_open), 20)
                marker = "💎 ULTRA" if (pod_type == "Reversal" and current_sig != 0) else "NORMAL"
                
                st.session_state.active_trades.append({
                    'Ticker': t_name, 'Pod': pod_type, 'Side': side, 'Marker': marker,
                    'Entry': ltp, 'SL': day_open if pod_type == "Reversal" else prev_lo,
                    'T1': ltp + (risk * 1.5) if side == "BUY" else ltp - (risk * 1.5),
                    'T2': ltp + (risk * 2.5) if side == "BUY" else ltp - (risk * 2.5),
                    'LTP': ltp, 'PnL': 0
                })

        # ... (Keep your existing Plotting code here) ...

    # --- PART 3: LIVE SIGNAL TABLE & PNL ---
    if st.session_state.active_trades:
        st.divider()
        st.write("### 🏢 Live Pod Signal Table")
        
        # Update Live PnL before displaying
        for trade in st.session_state.active_trades:
            # Simple PnL: (Current Price - Entry) * Direction
            multiplier = 1 if trade['Side'] == "BUY" else -1
            trade['PnL'] = (ltp - trade['Entry']) * multiplier
        
        active_df = pd.DataFrame(st.session_state.active_trades)
        st.dataframe(active_df.style.format(precision=2).applymap(lambda x: 'color: green' if str(x).startswith('-') == False and isinstance(x, (int, float)) else 'color: red', subset=['PnL']))

        # --- PNL GRAPH ---
        st.write("### 📉 Strategy P&L Curve")
        pnl_data = [t['PnL'] for t in st.session_state.active_trades]
        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Scatter(y=np.cumsum(pnl_data), mode='lines+markers', name='Cumulative PnL', line=dict(color='royalblue', width=3)))
        fig_pnl.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), template="plotly_white")
        st.plotly_chart(fig_pnl, use_container_width=True)
