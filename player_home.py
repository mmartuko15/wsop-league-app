
import streamlit as st, pandas as pd

import base64, requests, pandas as pd
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def read_tracker_bytes(file_bytes: bytes) -> dict:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

def pools_balance(pools_df, pool):
    if pools_df is None or pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def get_col(df, candidates):
    cols = {re.sub(r'[^a-z0-9]', '', c.lower()): c for c in df.columns}
    for cand in candidates:
        key = re.sub(r'[^a-z0-9]', '', cand.lower())
        if key in cols:
            return cols[key]
    return None

# Usage per event sheet:
pcol = get_col(df, ["Player","Name"])
kcol = get_col(df, ["KOs","#Eliminated","Knockouts","Eliminations"])


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

default_map, _ = read_local_tracker()
uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx) (optional)", type=["xlsx"])
if uploaded is not None:
    sheet_map = read_tracker_bytes(uploaded.read())
elif default_map is not None:
    sheet_map = default_map
else:
    st.info("Waiting for tracker.xlsx in repo.")
    st.stop()

pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance(pools,"WSOP")
bounty_total = pools_balance(pools,"Bounty")
high_total = pools_balance(pools,"High Hand")
nightly_total = pools_balance(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${high_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

st.subheader("Leaderboard")
lb = build_leaderboard(sheet_map)
st.dataframe(lb, use_container_width=True)

st.subheader("Events")
st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)
