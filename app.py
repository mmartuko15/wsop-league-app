
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
    """
    Robust leaderboard:
    - Accepts various column labels for Player/Place/KOs
    - Skips malformed event sheets instead of raising KeyError
    """
    import re

    def norm_cols(df):
        # lowercase, remove non-alnum for easy matching
        mapping = {}
        for c in df.columns:
            key = re.sub(r'[^a-z0-9]', '', str(c).lower())
            mapping[c] = key
        return df.rename(columns=mapping), set(mapping.values()), mapping

    def pick(colset, *candidates):
        # first candidate that exists
        for cand in candidates:
            if cand in colset:
                return cand
        return None

    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame):
            continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")):
            continue
        if df.empty:
            continue

        df2, colset, mapping = norm_cols(df)

        # Flexible header aliases
        player_key = pick(colset, "player", "name")
        place_key  = pick(colset, "place", "rank", "finish", "position")
        kos_key    = pick(colset, "kos", "ko", "knockouts", "knockout", "eliminations", "elimination", "eliminated", "eliminatedby", "elims", "numeliminated", "eliminatedcount", "eliminated_")

        if not player_key or not place_key:
            # Skip this sheet; it's missing essentials
            continue

        t = pd.DataFrame()
        t["Player"] = df2[player_key].astype(str).str.strip()
        t["Place"] = pd.to_numeric(df2[place_key], errors="coerce")

        if kos_key and kos_key in df2.columns:
            t["KOs"] = pd.to_numeric(df2[kos_key], errors="coerce").fillna(0).astype(int)
        else:
            t["KOs"] = 0

        t = t.dropna(subset=["Place"])
        # POINTS must be defined above
        t["Points"] = t["Place"].map(POINTS).fillna(0)
        frames.append(t)

    if not frames:
        return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])

    all_ev = pd.concat(frames, ignore_index=True)
    g = (
        all_ev.groupby("Player", as_index=False)
        .agg(Total_Points=("Points","sum"),
             Total_KOs=("KOs","sum"),
             Events_Played=("Points","count"))
        .sort_values(["Total_Points","Total_KOs"], ascending=[False,False])
        .reset_index(drop=True)
    )
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
