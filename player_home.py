
import streamlit as st, pandas as pd, base64

import streamlit as st, pandas as pd, requests, base64, json, re
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

def read_tracker_bytes(b: bytes):
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def write_tracker_bytes(sheet_map: dict) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    return bio.getvalue()

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

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

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        colmap = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
        pcol = colmap.get("player") or colmap.get("name")
        plc  = colmap.get("place") or colmap.get("rank") or colmap.get("finish") or colmap.get("position")
        kos  = colmap.get("kos") or colmap.get("knockouts") or colmap.get("eliminations") or colmap.get("elims")
        if not pcol or not plc: continue
        t = pd.DataFrame()
        t["Player"] = df[pcol].astype(str).str.strip()
        t["Place"]  = pd.to_numeric(df[plc], errors="coerce")
        t["KOs"]    = pd.to_numeric(df[kos], errors="coerce").fillna(0).astype(int) if kos else 0
        t = t.dropna(subset=["Place"])
        t["Points"] = t["Place"].map(POINTS).fillna(0)
        frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["Player","Total_Points","Total_KOs","Events_Played"])
    all_ev = pd.concat(frames, ignore_index=True)
    g = (all_ev.groupby("Player", as_index=False)
         .agg(Total_Points=("Points","sum"),
              Total_KOs=("KOs","sum"),
              Events_Played=("Points","count"))
         .sort_values(["Total_Points","Total_KOs"], ascending=[False,False])
         .reset_index(drop=True))
    g.index = g.index + 1
    return g

def gh_headers(token): 
    return {"Authorization": f"token {token}"} if token else {}

def gh_get(url, token, params=None):
    r = requests.get(url, headers=gh_headers(token), params=params or {}, timeout=30)
    return r

def gh_put(url, token, json_payload):
    r = requests.put(url, headers=gh_headers(token), json=json_payload, timeout=30)
    return r

def gh_post(url, token, json_payload):
    r = requests.post(url, headers=gh_headers(token), json=json_payload, timeout=30)
    return r

def gh_contents_get(owner_repo, path, ref, token):
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    return gh_get(url, token, params={"ref": ref})

def gh_file_sha(owner_repo, path, ref, token):
    r = gh_contents_get(owner_repo, path, ref, token)
    if r.status_code==200:
        return r.json().get("sha")
    return None

def gh_branch_create(owner_repo, new_branch, from_branch, token):
    # get base ref SHA
    rf = gh_get(f"https://api.github.com/repos/{owner_repo}/git/ref/heads/{from_branch}", token)
    if rf.status_code!=200:
        return False, f"Cannot read base branch: {rf.status_code} {rf.text}"
    base_sha = rf.json()["object"]["sha"]
    # create ref
    cr = gh_post(f"https://api.github.com/repos/{owner_repo}/git/refs", token, {"ref": f"refs/heads/{new_branch}", "sha": base_sha})
    if cr.status_code in (201,422):  # 422 if already exists
        return True, base_sha
    return False, f"Cannot create branch: {cr.status_code} {cr.text}"

def gh_create_or_update(owner_repo, path, branch, token, content_bytes):
    content_b64 = base64.b64encode(content_bytes).decode("utf-8")
    existing_sha = gh_file_sha(owner_repo, path, branch, token)
    payload = {"message":"Update tracker.xlsx (Admin PR publish)","content":content_b64,"branch":branch}
    if existing_sha:
        payload["sha"] = existing_sha
    r = gh_put(f"https://api.github.com/repos/{owner_repo}/contents/{path}", token, payload)
    return r

def gh_open_pr(owner_repo, from_branch, to_branch, title, body, token):
    jr = gh_post(f"https://api.github.com/repos/{owner_repo}/pulls", token, {"title": title, "head": from_branch, "base": to_branch, "body": body})
    return jr

def gh_latest_commit_touching(owner_repo, path, branch, token):
    # list commits for the file
    r = gh_get(f"https://api.github.com/repos/{owner_repo}/commits", token, params={"path": path, "sha": branch, "per_page": 1})
    if r.status_code==200 and r.json():
        c = r.json()[0]
        return c.get("sha"), c
    return None, None

def gh_pr_for_commit(owner_repo, sha, token):
    # search PRs by commit
    r = gh_get(f"https://api.github.com/search/issues", token, params={"q": f"repo:{owner_repo} type:pr is:merged {sha}"})
    if r.status_code==200 and r.json().get("items"):
        item = r.json()["items"][0]
        number = item.get("number")
        return number
    return None

def safe_str(x):
    if x is None: return ""
    if isinstance(x, float) and pd.isna(x): return ""
    s = str(x).strip()
    if s.lower()=="nan": return ""
    return s


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

# Load default tracker from repo bundle
default_map, _ = read_local_tracker()
mode = st.sidebar.radio("Load tracker from", ["Repo file (default)","Upload file","Fetch from GitHub (no cache)"], index=0)

sheet_map = None
banner_bits = []

if mode=="Repo file (default)":
    sheet_map = default_map
    banner_bits.append("Repo file (bundled)")
elif mode=="Upload file":
    up = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if up:
        sheet_map = read_tracker_bytes(up.read())
        banner_bits.append("Uploaded file")
else:
    owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
    branch = st.sidebar.text_input("Branch", value="main")
    token = st.secrets.get("PLAYER_GITHUB_TOKEN","")
    if st.sidebar.button("Fetch via API now"):
        r = gh_contents_get(owner_repo, "tracker.xlsx", branch, token)
        if r.status_code==200:
            content = base64.b64decode(r.json()["content"])
            sheet_map = read_tracker_bytes(content)
            banner_bits.append(f"GitHub API — {owner_repo}@{branch}")
            # discover latest commit and PR#
            sha, c = gh_latest_commit_touching(owner_repo, "tracker.xlsx", branch, token)
            if sha:
                banner_bits.append(f"Commit: {sha[:7]}")
                prn = gh_pr_for_commit(owner_repo, sha, token)
                if prn:
                    banner_bits.append(f"Merged PR: #{prn}")
        else:
            st.sidebar.error(f"GitHub API: {r.status_code} — {r.text}")

if sheet_map is None:
    st.info("No tracker loaded yet.")
    st.stop()

hh = sheet_map.get("HighHand_Info", pd.DataFrame())
last_upd = ""
if "HighHand_Info" in sheet_map and not sheet_map["HighHand_Info"].empty:
    last_upd = safe_str(sheet_map["HighHand_Info"].get("Last Updated",[ ""])[0])
if last_upd:
    banner_bits.append(f"High Hand last updated: {last_upd}")
st.info(" • ".join(banner_bits))

pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance_robust(pools,"WSOP")
bounty_total = pools_balance_robust(pools,"Bounty")
highhand_total = pools_balance_robust(pools,"High Hand")
nightly_total = pools_balance_robust(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool", f"${bounty_total:,.2f}")
k4.metric("High Hand", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool", f"${nightly_total:,.2f}")

tabs = st.tabs(["Leaderboard","High Hand","Nightly Payouts","Bounties","Second Chance","About"])

with tabs[0]:
    st.dataframe(robust_leaderboard(sheet_map), use_container_width=True)

with tabs[1]:
    holder = hand_desc = override_val = ""
    if "HighHand_Info" in sheet_map and not sheet_map["HighHand_Info"].empty:
        hhdf = sheet_map["HighHand_Info"]
        holder = safe_str(hhdf.get("Current Holder",[""])[0])
        hand_desc = safe_str(hhdf.get("Hand Description",[""])[0])
        override_val = safe_str(hhdf.get("Display Value (override)",[""])[0])
    display_val = override_val.strip()
    amt = display_val if display_val else f"${highhand_total:,.2f}"
    st.write(f"**Current Holder:** {holder if holder else '—'}")
    st.write(f"**Hand:** {hand_desc if hand_desc else '—'}")
    st.write(f"**Jackpot Value:** {amt}")
