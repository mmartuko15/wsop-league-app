
import streamlit as st, pandas as pd
from io import BytesIO
from pathlib import Path

import base64, requests, pandas as pd
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def pools_balance(pools_df, pool):
    if pools_df is None or pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def read_tracker_bytes(file_bytes: bytes) -> dict:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

def github_get_file_sha(owner_repo: str, path: str, branch: str, token: str):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"} if token else {}
    params = {"ref": branch}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def github_put_file(owner_repo: str, path: str, branch: str, token: str, file_bytes: bytes, message: str):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"} if token else {}
    content_b64 = base64.b64encode(file_bytes).decode("utf-8")
    sha = github_get_file_sha(owner_repo, path, branch, token)
    payload = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload, timeout=30)
    return r.status_code, r.text

def build_financial_summary(roster_df, event_sheets, series_buyins_df):
    frames = []
    for df in event_sheets:
        if df is None or df.empty: 
            continue
        tmp = df.copy()
        if "Payout_Amount" not in tmp.columns and "Payout" in tmp.columns:
            def pm(x):
                if pd.isna(x): return 0.0
                if isinstance(x,(int,float)): return float(x)
                s = str(x).replace("$","").replace(",","").strip()
                try: return float(s)
                except: return 0.0
            tmp["Payout_Amount"] = tmp["Payout"].map(pm)
        if "Bounty $ (KOs*5)" not in tmp.columns and "KOs" in tmp.columns:
            tmp["Bounty $ (KOs*5)"] = tmp["KOs"]*5
        frames.append(tmp[["Player","Payout_Amount","Bounty $ (KOs*5)"]])
    all_rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["Player","Payout_Amount","Bounty $ (KOs*5)"])

    events_played = all_rows.groupby("Player").size().rename("Events Played").to_frame()
    nightly_earned = all_rows.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned").to_frame()
    bounties_earned = all_rows.groupby("Player")["Bounty $ (KOs*5)"].sum().rename("Bounties Earned").to_frame()

    if series_buyins_df is not None and not series_buyins_df.empty:
        initial_buyins_paid = series_buyins_df.groupby("Player")["Amount"].sum().rename("Initial Buy-Ins Paid").to_frame()
    else:
        initial_buyins_paid = pd.DataFrame(columns=["Initial Buy-Ins Paid"])

    nightly_fees = (events_played["Events Played"] * 55).rename("Nightly Fees Paid").to_frame()
    bounty_contrib = (events_played["Events Played"] * 5).rename("Bounty Contributions Paid").to_frame()

    base = roster_df[["Player"]].copy()
    out = base.merge(events_played, left_on="Player", right_index=True, how="left")
    out = out.merge(nightly_earned, left_on="Player", right_index=True, how="left")
    out = out.merge(bounties_earned, left_on="Player", right_index=True, how="left")
    out = out.merge(nightly_fees, left_on="Player", right_index=True, how="left")
    out = out.merge(bounty_contrib, left_on="Player", right_index=True, how="left")
    out = out.merge(initial_buyins_paid, left_on="Player", right_index=True, how="left")

    out["Events Played"] = out["Events Played"].fillna(0).astype(int)
    for col in ["Nightly Payouts Earned","Bounties Earned","Nightly Fees Paid","Bounty Contributions Paid","Initial Buy-Ins Paid"]:
        if col in out.columns:
            out[col] = out[col].fillna(0.0)
        else:
            out[col] = 0.0

    out["Total Paid In"] = out["Initial Buy-Ins Paid"] + out["Nightly Fees Paid"]
    out["Total Earned"] = out["Nightly Payouts Earned"] + out["Bounties Earned"]
    out["Net Winnings"] = out["Total Earned"] - out["Total Paid In"]

    cols = [
        "Player","Events Played",
        "Initial Buy-Ins Paid","Nightly Fees Paid","Bounty Contributions Paid",
        "Nightly Payouts Earned","Bounties Earned",
        "Total Paid In","Total Earned","Net Winnings"
    ]
    for c in cols:
        if c not in out.columns:
            out[c] = 0.0
    return out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True)


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo:
    st.image("league_logo.png", use_column_width=True)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")
st.divider()

default_map, _ = read_local_tracker()
uploaded = st.sidebar.file_uploader("(Optional) Upload tracker (.xlsx)", type=["xlsx"])

if uploaded is not None:
    sheet_map = read_tracker_bytes(uploaded.read())
elif default_map is not None:
    sheet_map = default_map
else:
    st.info("Waiting for tracker.xlsx to be present in the repo (or upload one).")
    st.stop()

pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance(pools,"WSOP")
bounty_total = pools_balance(pools,"Bounty")
highhand_total = pools_balance(pools,"High Hand")
nightly_total = pools_balance(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

hh = sheet_map.get("HighHand_Info", pd.DataFrame())
holder, hand_desc, override_val = "", "", ""
if not hh.empty:
    holder = str(hh.get("Current Holder", [""])[0])
    hand_desc = str(hh.get("Hand Description", [""])[0])
    override_val = str(hh.get("Display Value (override)", [""])[0])

tabs = st.tabs(["Leaderboard","Events","Nightly Payouts","Bounties","High Hand","Second Chance","Player Finances","About"])

def build_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in sheet_map.items():
        if name.startswith("Event_") and name.endswith("_Standings") and "Player" in df.columns:
            t = df[["Player","Place","#Eliminated"]].copy()
            t.rename(columns={"#Eliminated":"KOs"}, inplace=True)
            t["Points"] = t["Place"].map(POINTS).fillna(0)
            frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    all_ev = pd.concat(frames, ignore_index=True)
    g = all_ev.groupby("Player", as_index=False).agg(
        Total_Points=("Points","sum"),
        Total_KOs=("KOs","sum"),
        Events_Played=("Points","count")
    )
    g = g.sort_values(["Total_Points","Total_KOs"], ascending=[False,False]).reset_index(drop=True)
    g.index = g.index + 1
    g.rename(columns={"Total_Points":"Total Points","Total_KOs":"Total KOs","Events_Played":"Events Played"}, inplace=True)
    return g

with tabs[0]:
    lb = build_leaderboard(sheet_map)
    st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    ev_sheets = [k for k in sheet_map.keys() if k.startswith("Event_") and k.endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            view = df[["Place","Player","Payout"]]
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True)
    else:
        st.info("Standings will appear after events are uploaded.")

with tabs[3]:
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            view = df[["Place","Player","KOs","Bounty $ (KOs*5)"]].rename(columns={"Bounty $ (KOs*5)":"Bounty $"})
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True)
    st.write(f"**Bounty Pool (live):** ${bounty_total:,.2f}")
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

with tabs[4]:
    display_val = (override_val or "").strip()
    amt = display_val if display_val else f"${highhand_total:,.2f}"
    st.write(f"**Current Holder:** {holder if holder else '—'}")
    st.write(f"**Hand:** {hand_desc if hand_desc else '—'}")
    st.write(f"**Jackpot Value:** {amt}")

with tabs[5]:
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame())
    st.subheader("Second Chance Pool & Opt-Ins")
    st.dataframe(optins, use_container_width=True)
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.write(f"**Second Chance Pool (live):** ${sc_pool:,.2f}  \nPayout 50/30/20 at season end.")

with tabs[6]:
    st.subheader("Per-Player Finances")
    roster_df = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    ev_sheets2 = []
    for k,v in sheet_map.items():
        if k.startswith("Event_") and k.endswith("_Standings"):
            ev_sheets2.append(v)
    fin = build_financial_summary(roster_df, ev_sheets2, sheet_map.get("Series_BuyIns", pd.DataFrame()))
    name_filter = st.text_input("Filter by player name", value="")
    view = fin.copy()
    if name_filter:
        view = view[view["Player"].str.contains(name_filter, case=False, na=False)]
    st.dataframe(view, use_container_width=True)

with tabs[7]:
    st.write("This is a read-only view of league standings and finances.")
