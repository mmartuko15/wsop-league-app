
import streamlit as st, pandas as pd, base64, requests, re
from io import BytesIO
from datetime import datetime

import base64, requests, pandas as pd, re, json
from io import BytesIO
from datetime import datetime, timezone

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

def github_api(method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"token {token}"
    headers["Accept"] = "application/vnd.github+json"
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)

def github_get_file(owner_repo: str, path: str, ref: str, token: str):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    resp = github_api("GET", url, token, params={"ref": ref})
    return resp

def github_put_file(owner_repo: str, path: str, branch: str, token: str, file_bytes: bytes, message: str, sha: str|None):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    content_b64 = base64.b64encode(file_bytes).decode("utf-8")
    payload = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    resp = github_api("PUT", url, token, json=payload)
    return resp

def github_create_branch(owner_repo: str, new_branch: str, from_branch: str, token: str):
    # get ref of from_branch
    r = github_api("GET", f"https://api.github.com/repos/{owner_repo}/git/ref/heads/{from_branch}", token)
    if r.status_code != 200:
        return r, None
    from_sha = r.json()["object"]["sha"]
    # create ref
    r2 = github_api("POST", f"https://api.github.com/repos/{owner_repo}/git/refs", token,
                    json={"ref": f"refs/heads/{new_branch}", "sha": from_sha})
    return r2, from_sha

def github_create_pr(owner_repo: str, head_branch: str, base_branch: str, title: str, token: str, body: str=""):
    url = f"https://api.github.com/repos/{owner_repo}/pulls"
    r = github_api("POST", url, token, json={"title": title, "head": head_branch, "base": base_branch, "body": body})
    return r

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

def ensure_highhand_sheet(sheet_map: dict):
    cols = ["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"]
    df = sheet_map.get("HighHand_Info")
    if df is None or df.empty:
        row = {k:"" for k in cols}
        row["Last Updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        sheet_map["HighHand_Info"] = pd.DataFrame([row], columns=cols)
    else:
        # normalize NaNs to empty strings
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        for c in cols:
            df[c] = df[c].fillna("").astype(str)
        sheet_map["HighHand_Info"] = df[cols]
    return sheet_map


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")
st.title("WSOP League — Player Home")

# Data source controls
mode = st.sidebar.radio("Load tracker from", ["Repo file (default)", "Upload file", "Fetch from GitHub (no cache, API)"], index=0)
sheet_map = None
source_label = ""

def fetch_api(owner_repo, branch, token=""):
    url = f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    r = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    r.raise_for_status()
    content = base64.b64decode(r.json()["content"])
    return read_tracker_bytes(content)

if mode == "Upload file":
    uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if uploaded:
        sheet_map = read_tracker_bytes(uploaded.read())
        source_label = "Uploaded file"
elif mode == "Fetch from GitHub (no cache, API)":
    owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
    branch = st.sidebar.text_input("Branch", value="main")
    token = st.secrets.get("PLAYER_GITHUB_TOKEN", "")
    if st.sidebar.button("Fetch via API now"):
        try:
            sheet_map = fetch_api(owner_repo, branch, token)
            source_label = f"GitHub API — {owner_repo}@{branch}"
        except Exception as e:
            st.sidebar.error(f"Fetch failed: {e}")
else:
    default_map, _ = read_local_tracker()
    if default_map is not None:
        sheet_map = default_map
        source_label = "Repo file (bundled)"

if sheet_map is None:
    st.info("No tracker loaded yet. Choose a source in the sidebar.")
    st.stop()

# Banner
last_updated = ""
if "HighHand_Info" in sheet_map and not sheet_map["HighHand_Info"].empty:
    try:
        last_updated = str(sheet_map["HighHand_Info"].loc[0,"Last Updated"])
    except Exception:
        pass
st.info(f"**Data source:** {source_label}" + (f"  •  **High Hand last updated:** {last_updated}" if last_updated else ""))

# Simple High Hand tab
tabs = st.tabs(["High Hand","Leaderboard"])
with tabs[0]:
    hh = sheet_map.get("HighHand_Info", pd.DataFrame())
    if hh.empty:
        st.warning("HighHand_Info sheet missing in tracker.")
    else:
        holder = str(hh.loc[0,"Current Holder"]) if pd.notna(hh.loc[0,"Current Holder"]) else ""
        hand = str(hh.loc[0,"Hand Description"]) if pd.notna(hh.loc[0,"Hand Description"]) else ""
        override = str(hh.loc[0,"Display Value (override)"]) if pd.notna(hh.loc[0,"Display Value (override)"]) else ""
        st.write(f"**Current Holder:** {holder or '—'}")
        st.write(f"**Hand:** {hand or '—'}")
        st.write(f"**Jackpot Value:** {(override if override else 'See High Hand pool total') }")

with tabs[1]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb, use_container_width=True)
