
import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

c1,c2 = st.columns([1,4])
with c1: st.image("league_logo.png", use_column_width=True)
with c2:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.sidebar.header("Upload (Admin Only)")
uploaded = st.sidebar.file_uploader("Upload current tracker (.xlsx)", type=["xlsx"], key="tracker")

if uploaded is None:
    st.info("Please ask the organizer to upload the current tracker.")
    st.stop()

sheet_map = pd.read_excel(BytesIO(uploaded.read()), sheet_name=None, engine="openpyxl")

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def build_leaderboard(sheet_map):
    frames = []
    for name, df in sheet_map.items():
        if name.startswith("Event_") and name.endswith("_Standings") and "Player" in df.columns:
            t = df[["Player","Place","#Eliminated"]].copy()
            t.rename(columns={"#Eliminated":"KOs"}, inplace=True)
            t["Points"] = t["Place"].map(POINTS).fillna(0)
            frames.append(t)
    if not frames: return pd.DataFrame()
    all_ev = pd.concat(frames, ignore_index=True)
    g = all_ev.groupby("Player", as_index=False).agg(**{"Total Points":("Points","sum"),"Total KOs":("KOs","sum"),"Events Played":("Points","count")})
    g = g.sort_values(["Total Points","Total KOs"], ascending=[False,False]).reset_index(drop=True)
    g.index = g.index + 1
    return g

def pools_balance(pools_df, pool):
    if pools_df is None or pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

events = sheet_map.get("Events")
pools = sheet_map.get("Pools_Ledger", pd.DataFrame())

wsop_total = pools_balance(pools,"WSOP")
bounty_total = pools_balance(pools,"Bounty")
hh_pool = pools_balance(pools,"High Hand")

k1,k2,k3,k4 = st.columns(4)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (pool)", f"${hh_pool:,.2f}")

tabs = st.tabs(["Leaderboard","Events","Bounties","High Hand","Second Chance"])

with tabs[0]:
    lb = build_leaderboard(sheet_map)
    if lb.empty: st.info("Leaderboard will appear as results are posted.")
    else: st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.dataframe(events, use_container_width=True)
    st.caption("All events at Countryside Country Club • Start 6:30 PM")

with tabs[2]:
    ev_sheets = [k for k in sheet_map.keys() if k.startswith("Event_") and k.endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            view = df[["Place","Player","KOs","Bounty $ (KOs*5)"]].rename(columns={"Bounty $ (KOs*5)":"Bounty $"})
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True)
    st.caption("Winner keeps their own $5 bounty; bounty pool pays at final event.")

with tabs[3]:
    hh_info = sheet_map.get("HighHand_Info", pd.DataFrame({"Field":[],"Value":[]}))
    holder = hh_info[hh_info["Field"]=="Current Holder"]["Value"]
    handdesc = hh_info[hh_info["Field"]=="Hand Description"]["Value"]
    disp = hh_info[hh_info["Field"]=="Display Value (override)"]["Value"]
    dd = disp.iloc[0] if not disp.empty else ""
    val_text = dd if dd else f"${hh_pool:,.2f}"
    st.subheader("Current High Hand")
    st.write(f"**Holder:** {holder.iloc[0] if not holder.empty else '—'}")
    st.write(f"**Hand:** {handdesc.iloc[0] if not handdesc.empty else '—'}")
    st.write(f"**Jackpot Value:** {val_text}")
    st.caption("Pays at final event unless a Royal Flush winner opts for immediate payout.")

with tabs[4]:
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame())
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.metric("Second Chance Pool (live)", f"${sc_pool:,.2f}")
    st.dataframe(optins, use_container_width=True)
