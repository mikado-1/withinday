import streamlit as st

# 1. This must be the VERY FIRST line of code
st.set_page_config(
    page_title="Withinday Trading Suite",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Main Page Content
st.title("📈 Withinday Trading Dashboard")
st.write("Welcome to the unified trading suite. Please select a tool from the sidebar to begin.")

# 3. Quick descriptions of your tools
st.markdown("""
### Available Tools:
1. **Nifty ATM Analysis** (Consecrutum_with_Niftyatm.py)
2. **Bank Nifty Percent Change** (BN_pct_op_graph.py)
3. **Nifty Percent Change** (N_pct_op_graph.py)
""")

st.info("👈 Use the sidebar on the left to navigate between these tools.")
