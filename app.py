
import streamlit as st, pandas as pd, re, json
from io import BytesIO
from datetime import datetime, timezone

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


st.set_page_config(page_title="WSOP League — Admin (PR2a)", page_icon="🛠️", layout="wide")

st.sidebar.header("Data Source")
default_map, default_bytes = read_local_tracker()
uploaded_tracker = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"], key="tracker_admin")
if uploaded_tracker is not None:
    tracker_bytes = uploaded_tracker.read()
    sheet_map = read_tracker_bytes(tracker_bytes)
elif default_map is not None:
    st.sidebar.info("Using repo default: tracker.xlsx")
    sheet_map = default_map
    tracker_bytes = default_bytes
else:
    st.info("Upload your tracker .xlsx in the sidebar or add tracker.xlsx to the repo root.")
    st.stop()

# Persisted Player URL
st.sidebar.header("Player Home Refresh")
cfg_path = ".wsop_config.json"
owner_repo = st.sidebar.text_input("GitHub repo (owner/repo)", value="mmartuko15/wsop-league-app")
branch_main = st.sidebar.text_input("Main branch", value="main")
gh_token = st.secrets.get("GITHUB_TOKEN", "")
if not gh_token:
    gh_token = st.sidebar.text_input("GITHUB_TOKEN (repo scope)", type="password")
player_url = ""
try:
    with open(cfg_path,"r") as f:
        cfg = json.load(f)
        player_url = cfg.get("player_home_url","")
except Exception:
    pass
player_url = st.sidebar.text_input("Player Home URL (saved to repo)", value=player_url)
if st.sidebar.button("Save Player URL to repo"):
    with open(cfg_path,"w") as f:
        json.dump({"player_home_url": player_url}, f, indent=2)
    st.sidebar.success("Saved .wsop_config.json (commit via Git to persist).")

st.title("WSOP League — Admin")
st.caption("PR publish flow with guardrails.")

# KPI preview
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

tabs = st.tabs(["High Hand (Admin)", "Publish via Pull Request", "Verify on GitHub (API)"])

with tabs[0]:
    st.subheader("Edit High Hand")
    sheet_map = ensure_highhand_sheet(sheet_map)
    hh = sheet_map["HighHand_Info"].copy()
    holder = st.text_input("Current Holder", value=str(hh.at[0,"Current Holder"]))
    hand = st.text_input("Hand Description", value=str(hh.at[0,"Hand Description"]))
    override = st.text_input("Display Value (override)", value=str(hh.at[0,"Display Value (override)"]))
    note = st.text_area("Note", value=str(hh.at[0,"Note"]))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"] = (holder or "").strip()
        hh.at[0,"Hand Description"] = (hand or "").strip()
        hh.at[0,"Display Value (override)"] = (override or "").strip()
        hh.at[0,"Note"] = (note or "").strip()
        hh.at[0,"Last Updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        sheet_map["HighHand_Info"] = hh
        st.success(f"Saved High Hand info. Last Updated now: {hh.at[0,'Last Updated']}")
    st.markdown("**Review to be published**")
    st.dataframe(sheet_map.get("HighHand_Info", pd.DataFrame()), use_container_width=True)

with tabs[1]:
    st.subheader("Publish tracker.xlsx via Pull Request")
    # Guard: ensure sheet exists and has Last Updated
    sheet_map = ensure_highhand_sheet(sheet_map)
    hh = sheet_map["HighHand_Info"].copy()
    required_cols = ["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"]
    ok_cols = all(c in hh.columns for c in required_cols)
    ok_updated = bool(str(hh.at[0,"Last Updated"]).strip())
    if not (ok_cols and ok_updated):
        st.error("HighHand_Info missing or Last Updated blank. Please save High Hand first.")
    else:
        st.success(f"Ready. Last Updated: {hh.at[0,'Last Updated']}")
    # Build workbook bytes from *current* in-memory sheet_map
    import io
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        for name, df in sheet_map.items():
            df.to_excel(w, sheet_name=str(name)[:31], index=False)
    xls_bytes = bio.getvalue()
    st.download_button("Download updated tracker (.xlsx)", data=xls_bytes, file_name="tracker.xlsx")

    # PR creation
    new_branch = st.text_input("New branch name", value=f"wsop-update-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    pr_title = st.text_input("PR title", value=f"Update tracker.xlsx — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    pr_body = f"Automated update of tracker.xlsx.\n\nHigh Hand Last Updated: {hh.at[0,'Last Updated']}\n"
    if st.button("Create PR now", disabled=not (ok_cols and ok_updated)):
        # create branch
        r_branch, base_sha = github_create_branch(owner_repo, new_branch, branch_main, gh_token)
        if r_branch.status_code not in (201,422): # 422 if branch exists
            st.error(f"Create branch failed: {r_branch.status_code} — {r_branch.text}")
        # get sha (if file exists on branch)
        r_get = github_get_file(owner_repo, "tracker.xlsx", new_branch, gh_token)
        sha = r_get.json().get("sha") if r_get.status_code==200 else None
        r_put = github_put_file(owner_repo, "tracker.xlsx", new_branch, gh_token, xls_bytes, pr_title, sha)
        if r_put.status_code not in (200,201):
            st.error(f"Upload file failed: {r_put.status_code}: {r_put.text}")
        else:
            # create PR
            r_pr = github_create_pr(owner_repo, new_branch, branch_main, pr_title, gh_token, pr_body)
            if r_pr.status_code in (201,200):
                pr_url = r_pr.json().get("html_url", "")
                st.success(f"PR created: {pr_url}")
                if player_url:
                    st.markdown(f"[Open Player Home (refresh)]({player_url}?refresh={datetime.now(timezone.utc).timestamp()})")
            else:
                st.error(f"Create PR failed: {r_pr.status_code} — {r_pr.text}")

with tabs[2]:
    st.subheader("Verify on GitHub (API) — main")
    import pandas as pd
    if st.button("Fetch tracker.xlsx from GitHub (API)"):
        r = github_get_file(owner_repo, "tracker.xlsx", branch_main, gh_token)
        if r.status_code != 200:
            st.error(f"GET contents failed: {r.status_code} — {r.text}")
        else:
            import base64, io
            content = base64.b64decode(r.json()["content"])
            try:
                m = read_tracker_bytes(content)
                if "HighHand_Info" not in m:
                    st.error("HighHand_Info sheet not found in GitHub copy.")
                else:
                    st.success("HighHand_Info sheet FOUND in GitHub copy.")
                    st.dataframe(m["HighHand_Info"], use_container_width=True)
            except Exception as e:
                st.error(f"Parse error: {e}")
