
import streamlit as st, pandas as pd, base64, requests, re

import base64, requests, pandas as pd, re, json
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
    type_col = cols.get("type"); pool_col = cols.get("pool")
    amt_col  = cols.get("amount") or cols.get("amt") or cols.get("value")
    if not (type_col and pool_col and amt_col): return 0.0
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

def github_get_contents(owner_repo: str, path: str, branch: str, token: str):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"} if token else {}
    params = {"ref": branch}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    return r

def github_get_latest_commit(owner_repo: str, path: str, branch: str, token: str):
    url = f"https://api.github.com/repos/{owner_repo}/commits"
    headers = {"Authorization": f"token {token}"} if token else {}
    params = {"path": path, "sha": branch, "per_page": 1}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 200 and isinstance(r.json(), list) and r.json():
        return r.json()[0]["sha"][:7]
    return ""

def github_get_file_sha(owner_repo: str, path: str, branch: str, token: str):
    r = github_get_contents(owner_repo, path, branch, token)
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
    r = requests.put(url, headers=headers, json=payload, timeout=60)
    return r

def github_test(owner_repo: str, branch: str, token: str):
    if not owner_repo or "/" not in owner_repo:
        return False, "Owner/Repo is blank or malformed. Expected 'owner/repo'."
    if not branch:
        return False, "Branch is blank."
    r = requests.get(f"https://api.github.com/repos/{owner_repo}", headers={"Authorization": f"token {token}"} if token else {}, timeout=20)
    if r.status_code == 404:
        return False, "Repository not found."
    if r.status_code in (401,403):
        return False, "Unauthorized or forbidden. Token missing/invalid or lacks access."
    r2 = requests.get(f"https://api.github.com/repos/{owner_repo}/branches/{branch}", headers={"Authorization": f"token {token}"} if token else {}, timeout=20)
    if r2.status_code == 404:
        return False, f"Branch '{branch}' not found."
    if r2.status_code in (401,403):
        return False, "Branch access denied."
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
        return False, "Write failed: 404 (path/branch)."
    if r3.status_code == 401:
        return False, "Unauthorized (401)."
    if r3.status_code == 403:
        return False, "Forbidden (403)."
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
            if cand in colset: return cand
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
with col_logo: show_logo(st)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Player Home")
    st.caption("Countryside Country Club • Start 6:30 PM")
st.divider()

# Modes: Repo file (bundled), Upload file, and explicit GitHub API fetch (no cache)
mode = st.sidebar.radio("Load tracker from", ["Repo file (default)","Upload file","Fetch from GitHub (no cache)"], index=0)
source_label = ""
commit_sha = ""
sheet_map = None

if mode == "Upload file":
    uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if uploaded:
        sheet_map = read_tracker_bytes(uploaded.read())
        source_label = "Uploaded file"
elif mode == "Fetch from GitHub (no cache)":
    owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
    branch = st.sidebar.text_input("Branch", value="main")
    token = st.secrets.get("PLAYER_GITHUB_TOKEN","")
    if st.sidebar.button("Fetch via API now"):
        try:
            url = f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx"
            headers = {"Authorization": f"token {token}"} if token else {}
            params = {"ref": branch}
            r = requests.get(url, headers=headers, params=params, timeout=45)
            r.raise_for_status()
            content = base64.b64decode(r.json()["content"])
            sheet_map = read_tracker_bytes(content)
            source_label = f"GitHub API — {owner_repo}@{branch}"
            # show latest commit touching this file
            c = requests.get(f"https://api.github.com/repos/{owner_repo}/commits", headers=headers, params={"path":"tracker.xlsx","sha":branch,"per_page":1}, timeout=30)
            if c.status_code == 200 and isinstance(c.json(), list) and c.json():
                commit_sha = c.json()[0]["sha"][:7]
        except Exception as e:
            st.sidebar.error(f"Fetch failed: {e}")
else:
    default_map, _ = read_local_tracker()
    if default_map is not None:
        sheet_map = default_map
        source_label = "Repo file (bundled)"

if sheet_map is None:
    st.info("No tracker loaded. Choose a source in the sidebar."); st.stop()

# HighHand last-updated
hh = sheet_map.get("HighHand_Info", pd.DataFrame())
last_updated = ""
if not hh.empty and "Last Updated" in hh.columns:
    try: last_updated = str(hh["Last Updated"].iloc[0])
    except Exception: last_updated = ""

banner = f"**Data source:** {source_label}"
if last_updated: banner += f" • **High Hand last updated:** {last_updated}"
if commit_sha:  banner += f" • **Commit:** {commit_sha}"
st.info(banner)

# KPIs
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
    if not pcol: return pd.DataFrame()
    out = pd.DataFrame()
    if place_col:
        out["Place"] = pd.to_numeric(df[place_col], errors="coerce").astype("Int64")
    else:
        out["Place"] = pd.Series(range(1, len(df)+1), dtype="Int64")
    out["Player"] = df[pcol].astype(str).str.strip()
    if payout_col: out["Payout"] = df[payout_col]
    return out

with tabs[0]:
    st.dataframe(robust_leaderboard(sheet_map), use_container_width=True)

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
            if not pcol: continue
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
        def clean(v): 
            if v is None: return ""
            s = str(v).strip()
            return "" if s.lower() == "nan" else s
        holder = clean(hh.get("Current Holder", [""])[0] if "Current Holder" in hh.columns else "")
        hand_desc = clean(hh.get("Hand Description", [""])[0] if "Hand Description" in hh.columns else "")
        override_val = clean(hh.get("Display Value (override)", [""])[0] if "Display Value (override)" in hh.columns else "")
    display_val = override_val
    if display_val:
        try:
            v = float(str(display_val).replace("$","").replace(",",""))
            amt = f"${v:,.2f}"
        except:
            amt = display_val
    else:
        amt = f"${highhand_total:,.2f}"
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
    st.write("Per-player finances (summary)")  # omitted for brevity
    # Could include the same function as Admin if needed

with tabs[7]:
    st.write("Read-only view of league standings and finances.")
