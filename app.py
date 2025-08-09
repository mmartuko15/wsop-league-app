
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

def build_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in sheet_map.items():
        if not (name.startswith("Event_") and name.endswith("_Standings")):
            continue
        # Normalize column names
        cols = {c.strip(): c for c in df.columns if isinstance(c, str)}
        if "Player" not in cols or "Place" not in cols:
            continue
        # KO column can be '#Eliminated' or 'KOs'
        ko_col = None
        for candidate in ["#Eliminated","KOs","Kos","KOs "]:
            if candidate in cols:
                ko_col = cols[candidate]
                break
        if ko_col is None:
            # If no KO column, assume zeros
            t = df[[cols["Player"], cols["Place"]]].copy()
            t["KOs"] = 0
        else:
            t = df[[cols["Player"], cols["Place"], ko_col]].copy().rename(columns={ko_col:"KOs"})
        t.rename(columns={cols["Player"]:"Player", cols["Place"]:"Place"}, inplace=True)
        t["Points"] = t["Place"].map(POINTS).fillna(0)
        frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    all_ev = pd.concat(frames, ignore_index=True)
    g = all_ev.groupby("Player", as_index=False).agg(
        **{"Total Points":("Points","sum"), "Total KOs":("KOs","sum"), "Events Played":("Points","count")}
    )
    g = g.sort_values(["Total Points","Total KOs"], ascending=[False,False]).reset_index(drop=True)
    g.index = g.index + 1
    return g

st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

default_map, default_bytes = read_local_tracker()
uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
if uploaded is not None:
    sheet_map = read_tracker_bytes(uploaded.read())
elif default_map is not None:
    sheet_map = default_map
else:
    st.info("Upload a tracker or add tracker.xlsx to repo.")
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
