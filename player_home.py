
import streamlit as st, pandas as pd, re, base64, requests
from io import BytesIO

import pandas as pd, re, base64, requests
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True; s = s[1:-1]
    try:
        v = float(s)
        return -v if neg else v
    except:
        return 0.0

def read_tracker_bytes(b: bytes):
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return read_tracker_bytes(b)
    except Exception:
        return None

def pools_balance_robust(pools_df, pool_name):
    if pools_df is None or isinstance(pools_df, dict) or pools_df is pd.NA:
        return 0.0
    if pools_df is None or pools_df.empty: return 0.0
    df = pools_df.copy()
    cols = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
    tcol = cols.get("type"); pcol = cols.get("pool")
    acol = cols.get("amount") or cols.get("amt") or cols.get("value")
    if not (tcol and pcol and acol): return 0.0
    tmp = pd.DataFrame({
        "_type": df[tcol].astype(str).str.strip().str.lower(),
        "_pool": df[pcol].astype(str).str.strip().str.lower(),
        "_amt":  df[acol].apply(parse_money)
    })
    tmp["_sign"] = tmp["_type"].map({"accrual":1,"payout":-1}).fillna(1)
    return float((tmp.loc[tmp["_pool"]==pool_name.lower(), "_amt"] * tmp.loc[tmp["_pool"]==pool_name.lower(), "_sign"]).sum())

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        key = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
        pcol = key.get("player") or key.get("name")
        plcol = key.get("place") or key.get("rank") or key.get("finish") or key.get("position")
        kcol  = key.get("kos") or key.get("knockouts") or key.get("eliminations") or key.get("elims") or key.get("numeliminated") or key.get("eliminated")
        if not (pcol and plcol): continue
        t = pd.DataFrame({
            "Player": df[pcol].astype(str).str.strip(),
            "Place": pd.to_numeric(df[plcol], errors="coerce")
        })
        t["KOs"] = pd.to_numeric(df[kcol], errors="coerce").fillna(0).astype(int) if kcol else 0
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

def show_logo(st):
    # Do not ship/overwrite user's logo; try to load if present.
    try:
        st.image("league_logo.jpg", use_column_width=True)
    except Exception:
        try:
            st.image("league_logo.png", use_column_width=True)
        except Exception:
            st.markdown("### League")


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo: show_logo(st)
with col_title:
    st.markdown("### WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.divider()

# Load tracker
source_label = "Repo file (bundled)"
sheet_map = read_local_tracker()

mode = st.sidebar.radio("Load tracker from", ["Repo file (default)","Upload file","Fetch from GitHub (no cache)"], index=0)

if mode == "Upload file":
    up = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if up:
        sheet_map = read_tracker_bytes(up.read())
        source_label = "Uploaded file"
elif mode == "Fetch from GitHub (no cache)":
    owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
    branch = st.sidebar.text_input("Branch", value="main")
    token = st.secrets.get("PLAYER_GITHUB_TOKEN","")
    if st.sidebar.button("Fetch via API now"):
        try:
            url = f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx"
            headers = {"Authorization": f"token {token}"} if token else {}
            r = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
            r.raise_for_status()
            content_b64 = r.json()["content"]
            data = base64.b64decode(content_b64)
            sheet_map = read_tracker_bytes(data)
            source_label = f"GitHub API — {owner_repo}@{branch}"
            st.sidebar.success("Fetched latest tracker via API.")
        except Exception as e:
            st.sidebar.error(f"Fetch failed: {e}")

if sheet_map is None:
    st.info("No tracker found. Add tracker.xlsx to repo or upload one.")
    st.stop()

# Pools / KPIs
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
with k4:
    st.markdown("[View details ↓](#high-hand-details)")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

st.info(f"**Data source:** {source_label}")

tabs = st.tabs(["Leaderboard","Events","Nightly Payouts","Bounties","High Hand","Second Chance","Player Finances","About"])

def build_event_view(df: pd.DataFrame) -> pd.DataFrame:
    cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
    pcol = cols.get("player") or cols.get("name")
    place_col = cols.get("place") or cols.get("rank") or cols.get("finish") or cols.get("position")
    payout_col = cols.get("payout") or cols.get("payoutamount")
    if not pcol:
        return pd.DataFrame()
    out = pd.DataFrame()
    if place_col:
        out["Place"] = pd.to_numeric(df[place_col], errors="coerce").astype("Int64")
    else:
        out["Place"] = pd.Series(range(1, len(df)+1), dtype="Int64")
    out["Player"] = df[pcol].astype(str).str.strip()
    if payout_col:
        out["Payout"] = df[payout_col]
    return out

with tabs[0]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            view = build_event_view(df)
            if not view.empty:
                st.write(f"**{s}**")
                st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("Standings will appear after events are uploaded.")

with tabs[3]:
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    if ev_sheets:
        for s in sorted(ev_sheets):
            df = sheet_map[s]
            cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
            pcol = cols.get("player") or cols.get("name")
            place_col = cols.get("place") or cols.get("rank") or cols.get("finish") or cols.get("position")
            kos_col = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
            if not pcol:
                continue
            view = pd.DataFrame()
            if place_col:
                view["Place"] = pd.to_numeric(df[place_col], errors="coerce").astype("Int64")
            else:
                view["Place"] = pd.Series(range(1, len(df)+1), dtype="Int64")
            view["Player"] = df[pcol]
            view["KOs"] = pd.to_numeric(df[kos_col], errors="coerce").fillna(0).astype(int) if kos_col else 0
            view["Bounty $"] = view["KOs"] * 5
            st.write(f"**{s}**")
            st.dataframe(view, use_container_width=True, hide_index=True)
    st.write(f"**Bounty Pool (live):** ${bounty_total:,.2f}")
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

with tabs[4]:
    st.markdown('<a name="high-hand-details"></a>', unsafe_allow_html=True)
    st.subheader("High Hand")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame())
    holder = hand_desc = override_val = last_upd = ""
    if not hh.empty:
        try:
            holder = "" if pd.isna(hh.at[0,"Current Holder"]) else str(hh.at[0,"Current Holder"]).strip()
            hand_desc = "" if pd.isna(hh.at[0,"Hand Description"]) else str(hh.at[0,"Hand Description"]).strip()
            override_val = "" if pd.isna(hh.at[0,"Display Value (override)"]) else str(hh.at[0,"Display Value (override)"]).strip()
            last_upd = "" if pd.isna(hh.at[0,"Last Updated"]) else str(hh.at[0,"Last Updated"]).strip()
        except Exception:
            pass
    # Show details
    st.write(f"**Current Holder:** {holder if holder else '—'}")
    st.write(f"**Hand:** {hand_desc if hand_desc else '—'}")
    # Amounts
    def fmt_money(s):
        try:
            v = float(str(s).replace("$","").replace(",","").strip())
            return f"${v:,.2f}"
        except Exception:
            return s if s else f"${highhand_total:,.2f}"
    if override_val:
        st.write(f"**Jackpot Value (override):** {fmt_money(override_val)}")
    st.write(f"**Live Pool Total:** ${highhand_total:,.2f}")
    if last_upd:
        st.caption(f"Last Updated: {last_upd}")

with tabs[5]:
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame())
    st.subheader("Second Chance Pool & Opt-Ins")
    st.dataframe(optins, use_container_width=True)
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.write(f"**Second Chance Pool (live):** ${sc_pool:,.2f}  \nPayout 50/30/20 at season end.")

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
        base = players_df[["Player"]].dropna().drop_duplicates().copy() if not players_df.empty else pd.DataFrame(columns=["Player"])
        out = base.merge(all_rows.groupby("Player").size().rename("Events Played"), left_on="Player", right_index=True, how="left")
        out = out.merge(all_rows.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned"), left_on="Player", right_index=True, how="left")
        out = out.merge(all_rows.groupby("Player")["BountyEarned"].sum().rename("Bounties Earned"), left_on="Player", right_index=True, how="left")
        out["Events Played"] = out["Events Played"].fillna(0).astype(int)
        out["Nightly Fees Paid"] = out["Events Played"] * 55.0
        out["Bounty Contributions Paid"] = out["Events Played"] * 5.0
        buyins = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount"])).copy()
        if not buyins.empty:
            initial_buyins_paid = buyins.groupby("Player")["Amount"].sum().rename("Initial Buy-Ins Paid").to_frame()
            out = out.merge(initial_buyins_paid, left_on="Player", right_index=True, how="left")
        else:
            out["Initial Buy-Ins Paid"] = 0.0
        for col in ["Nightly Payouts Earned","Bounties Earned","Initial Buy-Ins Paid"]:
            if col not in out.columns: out[col]=0.0
            out[col] = out[col].fillna(0.0)
        out["Total Paid In"] = out["Initial Buy-Ins Paid"] + out["Nightly Fees Paid"]
        out["Total Earned"] = out["Nightly Payouts Earned"] + out["Bounties Earned"]
        out["Net Winnings"] = out["Total Earned"] - out["Total Paid In"]
        cols = ["Player","Events Played","Initial Buy-Ins Paid","Nightly Fees Paid","Bounty Contributions Paid","Nightly Payouts Earned","Bounties Earned","Total Paid In","Total Earned","Net Winnings"]
        return out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True)
    fin = build_financials(sheet_map)
    st.dataframe(fin, use_container_width=True)

with tabs[7]:
    st.write("Read-only view of league standings and finances.")
