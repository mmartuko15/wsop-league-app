
import streamlit as st, pandas as pd, re
from io import BytesIO

import base64, requests, pandas as pd, re
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def read_tracker_bytes(b: bytes) -> dict:
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f: b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

def pools_balance(df, pool):
    if df is None or df.empty: return 0.0
    d = df[df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    def norm_cols(df):
        m = {}
        for c in df.columns:
            m[c] = re.sub(r'[^a-z0-9]','', str(c).lower())
        return df.rename(columns=m)
    def pick(colset,*cands):
        for c in cands:
            if c in colset: return c
        return None
    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        d2 = norm_cols(df)
        cols = set(d2.columns)
        p = pick(cols,"player","name"); pl = pick(cols,"place","rank","finish","position"); ko = pick(cols,"kos","knockouts","eliminations","elims","eliminated")
        if not p or not pl: continue
        t = pd.DataFrame()
        t["Player"] = d2[p].astype(str).str.strip()
        t["Place"] = pd.to_numeric(d2[pl], errors="coerce")
        t["KOs"] = pd.to_numeric(d2[ko], errors="coerce").fillna(0).astype(int) if ko else 0
        t = t.dropna(subset=["Place"])
        t["Points"] = t["Place"].map(POINTS).fillna(0)
        frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    all_ev = pd.concat(frames, ignore_index=True)
    g = (all_ev.groupby("Player", as_index=False)
         .agg(Total_Points=("Points","sum"),
              Total_KOs=("KOs","sum"),
              Events_Played=("Points","count"))
         .sort_values(["Total_Points","Total_KOs"], ascending=[False,False])
         .reset_index(drop=True))
    g.index = g.index + 1
    return g

def gh_get_sha(repo, path, branch, token):
    u = f"https://api.github.com/repos/{repo}/contents/{path}"
    h = {"Authorization": f"token {token}"} if token else {}
    r = requests.get(u, headers=h, params={"ref": branch}, timeout=20)
    if r.status_code==200: return r.json().get("sha")
    return None

def gh_put(repo, path, branch, token, file_bytes, message):
    import base64 as b64
    u = f"https://api.github.com/repos/{repo}/contents/{path}"
    h = {"Authorization": f"token {token}"} if token else {}
    sha = gh_get_sha(repo, path, branch, token)
    payload = {"message": message, "content": b64.b64encode(file_bytes).decode("utf-8"), "branch": branch}
    if sha: payload["sha"] = sha
    r = requests.put(u, headers=h, json=payload, timeout=30)
    return r.status_code, r.text


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")
col_logo, col_title = st.columns([1,4])
with col_logo: st.image("league_logo.png", use_column_width=True)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")
st.divider()

default_map, _ = read_local_tracker()
uploaded = st.sidebar.file_uploader("(Optional) Upload tracker (.xlsx)", type=["xlsx"])
if uploaded is not None: sheet_map = read_tracker_bytes(uploaded.read())
elif default_map is not None: sheet_map = default_map
else:
    st.info("Waiting for tracker.xlsx in repo (or upload one)."); st.stop()

pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance(pools,"WSOP"); bounty_total = pools_balance(pools,"Bounty")
hh_total = pools_balance(pools,"High Hand"); nightly_total = pools_balance(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${hh_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

tabs = st.tabs(["Leaderboard","Events","Nightly Payouts","Bounties","High Hand","Second Chance","Player Finances","About"])

with tabs[0]:
    st.dataframe(robust_leaderboard(sheet_map), use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    if not ev_sheets: st.info("Standings will appear after events are uploaded.")
    for s in sorted(ev_sheets):
        df = sheet_map[s]
        cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
        pcol = cols.get("player") or cols.get("name"); pay = cols.get("payout")
        if not (pcol and pay): continue
        view = df[[pcol, pay]].copy(); view.columns=["Player","Payout"]
        st.write(f"**{s}**"); st.dataframe(view, use_container_width=True)

with tabs[3]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    for s in sorted(ev_sheets):
        df = sheet_map[s]
        cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
        pcol = cols.get("player") or cols.get("name"); kcol = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
        if not pcol: continue
        view = pd.DataFrame(); view["Player"]=df[pcol]
        view["KOs"]=pd.to_numeric(df[kcol], errors="coerce").fillna(0).astype(int) if kcol else 0
        view["Bounty $"]=view["KOs"]*5
        st.write(f"**{s}**"); st.dataframe(view, use_container_width=True)
    st.write(f"**Bounty Pool (live):** ${bounty_total:,.2f}")
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

with tabs[4]:
    hh = sheet_map.get("HighHand_Info", pd.DataFrame())
    holder = hand_desc = override = ""
    if not hh.empty:
        holder = str(hh.get("Current Holder", [""])[0]); hand_desc = str(hh.get("Hand Description", [""])[0]); override = str(hh.get("Display Value (override)", [""])[0])
    amt = (override.strip() if override and str(override).strip() else f"${hh_total:,.2f}")
    st.write(f"**Current Holder:** {holder if holder else '—'}")
    st.write(f"**Hand:** {hand_desc if hand_desc else '—'}")
    st.write(f"**Jackpot Value:** {amt}")

with tabs[5]:
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame())
    st.subheader("Second Chance Pool & Opt-Ins"); st.dataframe(optins, use_container_width=True)
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.write(f"**Second Chance Pool (live):** ${sc_pool:,.2f}  \nPayout 50/30/20 at season end.")

with tabs[6]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    ev_frames=[]
    for s in ev_sheets:
        df = sheet_map[s]
        cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
        pcol = cols.get("player") or cols.get("name")
        pay = cols.get("payout") or cols.get("payoutamount")
        kcol = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
        if not (pcol and pay): continue
        t = pd.DataFrame()
        t["Player"]=df[pcol].astype(str).str.strip()
        t["Payout_Amount"]=df[pay].apply(parse_money)
        t["BountyEarned"]=(pd.to_numeric(df[kcol], errors="coerce").fillna(0).astype(int)*5) if kcol else 0
        ev_frames.append(t)
    all_rows = pd.concat(ev_frames, ignore_index=True) if ev_frames else pd.DataFrame(columns=["Player","Payout_Amount","BountyEarned"])
    roster = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    base = roster[["Player"]].dropna().drop_duplicates().copy()
    events_played = all_rows.groupby("Player").size().rename("Events Played").to_frame()
    nightly_earned = all_rows.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned").to_frame()
    bounties_earned = all_rows.groupby("Player")["BountyEarned"].sum().rename("Bounties Earned").to_frame()
    buyins = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount"])).copy()
    initial = buyins.groupby("Player")["Amount"].sum().rename("Initial Buy-Ins Paid").to_frame() if not buyins.empty else pd.DataFrame(columns=["Initial Buy-Ins Paid"])
    out = base.merge(events_played, left_on="Player", right_index=True, how="left")
    out = out.merge(nightly_earned, left_on="Player", right_index=True, how="left")
    out = out.merge(bounties_earned, left_on="Player", right_index=True, how="left")
    out["Events Played"]=out["Events Played"].fillna(0).astype(int)
    out["Nightly Fees Paid"]=out["Events Played"]*55.0
    out["Bounty Contributions Paid"]=out["Events Played"]*5.0
    out = out.merge(initial, left_on="Player", right_index=True, how="left")
    for c in ["Nightly Payouts Earned","Bounties Earned","Initial Buy-Ins Paid"]:
        out[c]=out[c].fillna(0.0)
    out["Total Paid In"]=out["Initial Buy-Ins Paid"]+out["Nightly Fees Paid"]
    out["Total Earned"]=out["Nightly Payouts Earned"]+out["Bounties Earned"]
    out["Net Winnings"]=out["Total Earned"]-out["Total Paid In"]
    cols=["Player","Events Played","Initial Buy-Ins Paid","Nightly Fees Paid","Bounty Contributions Paid","Nightly Payouts Earned","Bounties Earned","Total Paid In","Total Earned","Net Winnings"]
    st.dataframe(out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True), use_container_width=True)

with tabs[7]:
    st.write("Read-only view of league standings and finances.")
