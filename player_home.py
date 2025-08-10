
import streamlit as st, pandas as pd, re
from io import BytesIO
from pathlib import Path

import base64, requests, pandas as pd, re, io
from io import BytesIO
from PIL import Image

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def pools_balance_robust(pools_df, pool_name):
    """Case-insensitive, parses currency, Accrual=+, Payout=-"""
    if pools_df is None or len(pools_df)==0:
        return 0.0
    df = pools_df.copy()
    # normalize headers
    norm = {c: re.sub(r'[^a-z0-9]', '', str(c).lower()) for c in df.columns}
    df.columns = [norm[c] for c in df.columns]
    # map essential columns
    tcol = next((c for c in df.columns if c in ("type","entrytype")), None)
    pcol = next((c for c in df.columns if c in ("pool","fund")), None)
    acol = next((c for c in df.columns if c in ("amount","amt","value")), None)
    if not (tcol and pcol and acol):
        return 0.0
    df[acol] = df[acol].apply(parse_money)
    df[pcol] = df[pcol].astype(str).str.strip().str.lower()
    sign = df[tcol].astype(str).str.strip().str.lower().map({"accrual":1,"payout":-1}).fillna(1)
    sub = df[df[pcol] == str(pool_name).strip().lower()]
    return float((sub[acol] * sign.loc[sub.index]).sum())

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

def show_logo(st, primary="league_logo.jpg", secondary="league_logo.png"):
    """Attempt to display JPG then PNG; fallback to text if invalid/missing."""
    for path in (primary, secondary):
        try:
            with open(path, "rb") as f:
                data = f.read()
            Image.open(io.BytesIO(data))  # validate
            st.image(data, use_column_width=True)
            return
        except Exception:
            continue
    st.write("### Mark & Rose's WSOP League")

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    """Builds a leaderboard while tolerating header variations and skipping malformed sheets."""
    def norm_cols(df):
        mapping = {}
        for c in df.columns:
            key = re.sub(r'[^a-z0-9]', '', str(c).lower())
            mapping[c] = key
        return df.rename(columns=mapping)

    def pick(colset, *candidates):
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

        df2 = norm_cols(df)
        colset = set(df2.columns)

        player_key = pick(colset, "player", "name")
        place_key  = pick(colset, "place", "rank", "finish", "position")
        kos_key    = pick(colset, "kos", "ko", "knockouts", "knockout", "eliminations", "elimination", "elims", "numeliminated", "eliminated")

        if not player_key or not place_key:
            continue

        t = pd.DataFrame()
        t["Player"] = df2[player_key].astype(str).str.strip()
        t["Place"]  = pd.to_numeric(df2[place_key], errors="coerce")
        if kos_key and kos_key in df2.columns:
            t["KOs"] = pd.to_numeric(df2[kos_key], errors="coerce").fillna(0).astype(int)
        else:
            t["KOs"] = 0

        t = t.dropna(subset=["Place"])
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


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

# Header
col_logo, col_title = st.columns([1,4])
with col_logo:
    show_logo(st)  # prefers JPG, then PNG, fallback text
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.divider()

# Data source
default_map, _ = read_local_tracker()
uploaded = st.sidebar.file_uploader("(Optional) Upload tracker (.xlsx)", type=["xlsx"])

if uploaded is not None:
    sheet_map = read_tracker_bytes(uploaded.read())
elif default_map is not None:
    sheet_map = default_map
else:
    st.info("Waiting for tracker.xlsx to be present in the repo (or upload one).")
    st.stop()

# KPIs (robust)
pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance_robust(pools,"WSOP")
bounty_total = pools_balance_robust(pools,"Bounty")
highhand_total = pools_balance_robust(pools,"High Hand")
nightly_total = pools_balance_robust(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

tabs = st.tabs(["Leaderboard","Events","Nightly Payouts","Bounties","High Hand","Second Chance","Player Finances","About"])

# Leaderboard
with tabs[0]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb, use_container_width=True)

# Events
with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

# Nightly Payouts
with tabs[2]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
            pcol = cols.get("player") or cols.get("name")
            payout_col = cols.get("payout")
            if not (pcol and payout_col):
                continue
            view = df[[pcol, payout_col]].copy()
            view.columns = ["Player","Payout"]
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True)
    else:
        st.info("Standings will appear after events are uploaded.")

# Bounties
with tabs[3]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
            pcol = cols.get("player") or cols.get("name")
            kos_col = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
            if not pcol:
                continue
            view = pd.DataFrame()
            view["Player"] = df[pcol]
            view["KOs"] = pd.to_numeric(df[kos_col], errors="coerce").fillna(0).astype(int) if kos_col else 0
            view["Bounty $"] = view["KOs"] * 5
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True)
    st.write(f"**Bounty Pool (live):** ${bounty_total:,.2f}")
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

# High Hand
with tabs[4]:
    hh = sheet_map.get("HighHand_Info", pd.DataFrame())
    holder = hand_desc = override_val = ""
    if not hh.empty:
        holder = str(hh.get("Current Holder", [""])[0])
        hand_desc = str(hh.get("Hand Description", [""])[0])
        override_val = str(hh.get("Display Value (override)", [""])[0])
    display_val = override_val.strip()
    amt = display_val if display_val else f"${highhand_total:,.2f}"
    st.write(f"**Current Holder:** {holder if holder else '—'}")
    st.write(f"**Hand:** {hand_desc if hand_desc else '—'}")
    st.write(f"**Jackpot Value:** {amt}")

# Second Chance
with tabs[5]:
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame())
    st.subheader("Second Chance Pool & Opt-Ins")
    st.dataframe(optins, use_container_width=True)
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.write(f"**Second Chance Pool (live):** ${sc_pool:,.2f}  \nPayout 50/30/20 at season end.")

# Player Finances (read-only)
with tabs[6]:
    def build_financials(sheet_map):
        ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
        ev_frames = []
        for s in ev_sheets:
            df = sheet_map[s]
            cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
            pcol = cols.get("player") or cols.get("name")
            payout_col = cols.get("payout") or cols.get("payoutamount")
            kos_col = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
            if not (pcol and payout_col):
                continue
            t = pd.DataFrame()
            t["Player"] = df[pcol].astype(str).str.strip()
            t["Payout_Amount"] = df[payout_col].apply(parse_money)
            t["BountyEarned"] = pd.to_numeric(df[kos_col], errors="coerce").fillna(0).astype(int)*5 if kos_col else 0
            ev_frames.append(t)
        all_rows = pd.concat(ev_frames, ignore_index=True) if ev_frames else pd.DataFrame(columns=["Player","Payout_Amount","BountyEarned"])

        players_df = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
        base = players_df[["Player"]].dropna().drop_duplicates().copy()

        events_played = all_rows.groupby("Player").size().rename("Events Played").to_frame()
        nightly_earned = all_rows.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned").to_frame()
        bounties_earned = all_rows.groupby("Player")["BountyEarned"].sum().rename("Bounties Earned").to_frame()

        buyins = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount"])).copy()
        initial_buyins_paid = buyins.groupby("Player")["Amount"].sum().rename("Initial Buy-Ins Paid").to_frame() if not buyins.empty else pd.DataFrame(columns=["Initial Buy-Ins Paid"])

        out = base.merge(events_played, left_on="Player", right_index=True, how="left")
        out = out.merge(nightly_earned, left_on="Player", right_index=True, how="left")
        out = out.merge(bounties_earned, left_on="Player", right_index=True, how="left")
        out["Events Played"] = out["Events Played"].fillna(0).astype(int)
        out["Nightly Fees Paid"] = out["Events Played"] * 55.0
        out["Bounty Contributions Paid"] = out["Events Played"] * 5.0
        out = out.merge(initial_buyins_paid, left_on="Player", right_index=True, how="left")

        for col in ["Nightly Payouts Earned","Bounties Earned","Initial Buy-Ins Paid"]:
            out[col] = out[col].fillna(0.0)

        out["Total Paid In"] = out["Initial Buy-Ins Paid"] + out["Nightly Fees Paid"]
        out["Total Earned"] = out["Nightly Payouts Earned"] + out["Bounties Earned"]
        out["Net Winnings"] = out["Total Earned"] - out["Total Paid In"]

        cols = ["Player","Events Played","Initial Buy-Ins Paid","Nightly Fees Paid","Bounty Contributions Paid","Nightly Payouts Earned","Bounties Earned","Total Paid In","Total Earned","Net Winnings"]
        return out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True)

    fin = build_financials(sheet_map)
    st.dataframe(fin, use_container_width=True)

# About
with tabs[7]:
    st.write("Read-only view of league standings and finances.")
