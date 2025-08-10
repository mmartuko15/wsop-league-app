
import streamlit as st, pandas as pd, re, base64, requests
from io import BytesIO

import base64, requests, pandas as pd, re
from io import BytesIO
from PIL import Image

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

def pools_balance_robust(pools_df, pool_name):
    if pools_df is None or pools_df.empty: return 0.0
    df = pools_df.copy()
    cols = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
    type_col = cols.get("type")
    pool_col = cols.get("pool")
    amt_col  = cols.get("amount") or cols.get("amt") or cols.get("value")
    if not (type_col and pool_col and amt_col):
        return 0.0
    df["_type"] = df[type_col].astype(str).str.strip().str.lower()
    df["_pool"] = df[pool_col].astype(str).str.strip().str.lower()
    df["_amt"]  = df[amt_col].apply(parse_money)
    df["_sign"] = df["_type"].map({"accrual":1,"payout":-1}).fillna(1)
    mask = df["_pool"]==pool_name.lower()
    return float((df.loc[mask, "_amt"] * df.loc[mask, "_sign"]).sum())

def read_tracker_bytes(file_bytes: bytes) -> dict:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

def github_get_file(owner_repo: str, branch: str, token: str, path: str="tracker.xlsx") -> bytes:
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"} if token else {}
    params = {"ref": branch}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    import base64 as _b
    return _b.b64decode(r.json()["content"])

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

def github_test(owner_repo: str, branch: str, token: str):
    if not owner_repo or "/" not in owner_repo:
        return False, "Owner/Repo is blank or malformed. Expected 'owner/repo'."
    if not branch:
        return False, "Branch is blank."
    r = requests.get(f"https://api.github.com/repos/{owner_repo}", headers={"Authorization": f"token {token}"} if token else {}, timeout=20)
    if r.status_code == 404:
        return False, "Repository not found (check owner/repo spelling and that your token can see it)."
    if r.status_code in (401,403):
        return False, "Unauthorized. Token missing/invalid or lacks access (repo scope / SSO not authorized)."
    r2 = requests.get(f"https://api.github.com/repos/{owner_repo}/branches/{branch}", headers={"Authorization": f"token {token}"} if token else {}, timeout=20)
    if r2.status_code == 404:
        return False, f"Branch '{branch}' not found."
    if r2.status_code in (401,403):
        return False, "Branch access denied. Token lacks permissions."
    # Write test
    url = f"https://api.github.com/repos/{owner_repo}/contents/.wsop_write_test.txt"
    payload = {"message":"write-test","content":base64.b64encode(b"wsop-write-test").decode("utf-8"),"branch":branch}
    r3 = requests.put(url, headers={"Authorization": f"token {token}"} if token else {}, json=payload, timeout=20)
    if r3.status_code in (200,201):
        try:
            sha = r3.json().get("content",{}).get("sha")
            if sha:
                requests.delete(url, headers={"Authorization": f"token {token}"} if token else {}, json={"message":"cleanup","sha":sha,"branch":branch}, timeout=20)
        except Exception:
            pass
        return True, "Connection OK. Repo, branch, and write permission verified."
    if r3.status_code == 404:
        return False, "Write failed with 404. Repo/branch path not reachable with this token."
    if r3.status_code == 401:
        return False, "Unauthorized (401). Token missing or invalid."
    if r3.status_code == 403:
        return False, "Forbidden (403). Token lacks 'repo' scope or SSO not authorized."
    return False, f"Write test failed: HTTP {r3.status_code}: {r3.text}"

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
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
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        df2 = norm_cols(df); colset = set(df2.columns)
        player_key = pick(colset,"player","name")
        place_key  = pick(colset,"place","rank","finish","position")
        kos_key    = pick(colset,"kos","ko","knockouts","knockout","eliminations","elimination","elims","numeliminated","eliminated")
        if not player_key or not place_key: continue
        t = pd.DataFrame()
        t["Player"] = df2[player_key].astype(str).str.strip()
        t["Place"]  = pd.to_numeric(df2[place_key], errors="coerce")
        t["KOs"]    = pd.to_numeric(df2[kos_key], errors="coerce").fillna(0).astype(int) if (kos_key and kos_key in df2.columns) else 0
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

def show_logo(st, primary="league_logo.jpg", fallback="league_logo.png"):
    try:
        st.image(primary, use_column_width=True)
    except Exception:
        try:
            st.image(fallback, use_column_width=True)
        except Exception:
            st.markdown("### Mark & Rose's WSOP League")


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo:
    show_logo(st)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.divider()

# Sidebar: Auto-fetch toggle
st.sidebar.header("Data source")
auto_fetch = st.sidebar.checkbox("Auto-fetch from GitHub on load", value=True)
owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")

sheet_map = None
source_label = ""
last_updated = ""

def do_fetch():
    token = st.secrets.get("PLAYER_GITHUB_TOKEN", "")
    if not token:
        token = st.sidebar.text_input("GitHub token (read-only)", type="password", key="player_token")
    try:
        bytes_ = github_get_file(owner_repo, branch, token, path="tracker.xlsx")
        return read_tracker_bytes(bytes_)
    except Exception as e:
        st.sidebar.error(f"GitHub fetch failed: {e}")
        return None

if auto_fetch:
    fetched = do_fetch()
    if fetched is not None:
        sheet_map = fetched
        source_label = f"GitHub API — {owner_repo}@{branch}"
    else:
        st.sidebar.warning("Falling back to repo file / upload because auto-fetch failed.")

if sheet_map is None:
    mode = st.sidebar.radio("Manual source", ["Repo file (bundled)", "Upload file", "Fetch now"], index=0)
    if mode == "Upload file":
        uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
        if uploaded:
            sheet_map = read_tracker_bytes(uploaded.read())
            source_label = "Uploaded file"
    elif mode == "Fetch now":
        sheet_map = do_fetch()
        if sheet_map is not None:
            source_label = f"GitHub API — {owner_repo}@{branch}"
    else:
        default_map, _ = read_local_tracker()
        if default_map is not None:
            sheet_map = default_map
            source_label = "Repo file (bundled)"

if sheet_map is None:
    st.info("No tracker loaded yet. Choose a data source in the sidebar.")
    st.stop()

# Banner with last updated
hh = sheet_map.get("HighHand_Info", pd.DataFrame())
if not hh.empty and "Last Updated" in hh.columns:
    try:
        last_updated = str(hh["Last Updated"].iloc[0])
    except Exception:
        last_updated = ""

st.info(f"**Data source:** {source_label}" + (f"  •  **High Hand last updated:** {last_updated}" if last_updated else ""))

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
    holder = hand_desc = override_val = ""
    if "HighHand_Info" in sheet_map and not sheet_map["HighHand_Info"].empty:
        hh = sheet_map["HighHand_Info"]
        holder = str(hh.get("Current Holder", [""])[0])
        hand_desc = str(hh.get("Hand Description", [""])[0])
        override_val = str(hh.get("Display Value (override)", [""])[0])
    display_val = override_val.strip()
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

with tabs[7]:
    st.write("Read-only view of league standings and finances.")
