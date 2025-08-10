
import streamlit as st, pandas as pd
from datetime import datetime, timezone

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


st.set_page_config(page_title="WSOP League — Admin (PR Flow)", page_icon="🛠️", layout="wide")

# Load tracker (from repo or upload)
default_map, default_bytes = read_local_tracker()
uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"], key="tracker_admin")
if uploaded:
    tracker_bytes = uploaded.read()
    sheet_map = read_tracker_bytes(tracker_bytes)
else:
    sheet_map = default_map
    tracker_bytes = default_bytes

if sheet_map is None:
    st.warning("Add tracker.xlsx to repo root or upload a workbook.")
    st.stop()

# KPI header
pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance_robust(pools,"WSOP")
bounty_total = pools_balance_robust(pools,"Bounty")
highhand_total = pools_balance_robust(pools,"High Hand")
nightly_total = pools_balance_robust(pools,"Nightly")
k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (5x)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool", f"${nightly_total:,.2f}")

tabs = st.tabs(["High Hand (Admin)","Leaderboards","Verify on GitHub (API)","Publish via Pull Request","Download/Publish (direct)"])

with tabs[0]:
    st.subheader("High Hand Controls")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if hh.empty:
        hh.loc[0] = ["","","","", ""]
    holder = st.text_input("Current Holder", value=safe_str(hh.at[0,"Current Holder"]))
    hand = st.text_input("Hand Description", value=safe_str(hh.at[0,"Hand Description"]))
    override = st.text_input("Display Value (override)", value=safe_str(hh.at[0,"Display Value (override)"]))
    note = st.text_area("Note", value=safe_str(hh.at[0,"Note"]))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"] = safe_str(holder)
        hh.at[0,"Hand Description"] = safe_str(hand)
        hh.at[0,"Display Value (override)"] = safe_str(override)
        hh.at[0,"Last Updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        hh.at[0,"Note"] = safe_str(note)
        sheet_map["HighHand_Info"] = hh
        st.success(f"Saved. Last Updated now: {hh.at[0,'Last Updated']}")

    st.markdown("**Preview to be published**")
    st.dataframe(sheet_map["HighHand_Info"], use_container_width=True)

with tabs[1]:
    st.dataframe(robust_leaderboard(sheet_map), use_container_width=True)

with tabs[2]:
    st.subheader("Verify tracker.xlsx on GitHub (main)")
    owner_repo = st.text_input("Repo (owner/repo)", value="mmartuko15/wsop-league-app", key="vr_repo")
    branch = st.text_input("Branch", value="main", key="vr_branch")
    token = st.secrets.get("GITHUB_TOKEN", "")
    if not token:
        token = st.text_input("GitHub token (read)", type="password")
    if st.button("Fetch tracker.xlsx from GitHub (API)"):
        r = gh_contents_get(owner_repo, "tracker.xlsx", branch, token)
        if r.status_code!=200:
            st.error(f"GitHub API: {r.status_code} — {r.text}")
        else:
            try:
                content = base64.b64decode(r.json()["content"])
                sm = read_tracker_bytes(content)
                if "HighHand_Info" not in sm:
                    st.error("HighHand_Info sheet not found in GitHub copy.")
                else:
                    st.success("HighHand_Info found.")
                    st.dataframe(sm["HighHand_Info"], use_container_width=True)
                sha, c = gh_latest_commit_touching(owner_repo, "tracker.xlsx", branch, token)
                if sha:
                    st.info(f"Latest commit touching tracker.xlsx on {branch}: {sha[:7]}")
            except Exception as e:
                st.error(f"Error reading workbook: {e}")

with tabs[3]:
    st.subheader("Publish via Pull Request (respects branch protection)")
    owner_repo = st.text_input("Repo (owner/repo)", value="mmartuko15/wsop-league-app", key="pr_repo")
    base_branch = st.text_input("Base branch", value="main", key="pr_base")
    new_branch = st.text_input("New branch name", value=f"wsop-update-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}", key="pr_branch")
    pr_title = st.text_input("PR title", value="Update tracker.xlsx (WSOP Admin)", key="pr_title")
    token = st.secrets.get("GITHUB_TOKEN", "")
    if not token:
        token = st.text_input("GitHub token (repo, PR write)", type="password")
    # guardrails
    hh = sheet_map.get("HighHand_Info", pd.DataFrame())
    guard_ok = True
    guard_msg = ""
    if hh.empty or all(col not in hh.columns for col in ["Current Holder","Last Updated"]):
        guard_ok = False
        guard_msg = "HighHand_Info is missing or has wrong columns."
    elif safe_str(hh.at[0,"Last Updated"])=="":
        guard_ok = False
        guard_msg = "HighHand_Info.Last Updated is blank. Click 'Save High Hand Info' first."
    if not guard_ok:
        st.warning(f"Guardrail: {guard_msg}")
    if st.button("Create PR now", disabled=not guard_ok):
        # always build from in-memory sheet_map
        try:
            content_bytes = write_tracker_bytes(sheet_map)
        except Exception as e:
            st.error(f"Could not serialize workbook: {e}")
            st.stop()
        ok, msg = gh_branch_create(owner_repo, new_branch, base_branch, token)
        if not ok:
            st.error(msg)
            st.stop()
        rput = gh_create_or_update(owner_repo, "tracker.xlsx", new_branch, token, content_bytes)
        if rput.status_code not in (200,201):
            st.error(f"Upload file failed: {rput.status_code}: {rput.text}")
            st.stop()
        body = f"Automated publish from Admin.\n\nHighHand_Info:\n\n{hh.to_string(index=False)}"
        rpr = gh_open_pr(owner_repo, new_branch, base_branch, pr_title, body, token)
        if rpr.status_code not in (200,201):
            st.error(f"PR create failed: {rpr.status_code}: {rpr.text}")
            st.stop()
        pr_number = rpr.json().get("number")
        st.success(f"PR created: #{pr_number}")
        st.markdown(f"[Open PR](https://github.com/{owner_repo}/pull/{pr_number})")

        # post-publish verification on branch
        rv = gh_contents_get(owner_repo, "tracker.xlsx", new_branch, token)
        if rv.status_code==200:
            try:
                vb = base64.b64decode(rv.json()["content"])
                smv = read_tracker_bytes(vb)
                if "HighHand_Info" in smv:
                    st.info("Verification: HighHand_Info present in PR branch.")
                else:
                    st.error("Verification: HighHand_Info MISSING in PR branch!")
            except Exception as e:
                st.error(f"Verification read error: {e}")
        else:
            st.error(f"Verification contents get failed: {rv.status_code}: {rv.text}")

with tabs[4]:
    st.caption("Direct publish (for unprotected branches). Not recommended with protection rules.")
    owner_repo = st.text_input("Repo (owner/repo)", value="mmartuko15/wsop-league-app", key="dp_repo")
    branch = st.text_input("Branch", value="main", key="dp_branch")
    token = st.secrets.get("GITHUB_TOKEN","")
    if not token:
        token = st.text_input("GitHub token (repo)", type="password")
    if st.button("Publish tracker.xlsx directly (overwrite)"):
        try:
            content_bytes = write_tracker_bytes(sheet_map)
        except Exception as e:
            st.error(f"Serialize error: {e}")
            st.stop()
        r = gh_create_or_update(owner_repo, "tracker.xlsx", branch, token, content_bytes)
        if r.status_code in (200,201):
            st.success("Direct publish OK.")
        else:
            st.error(f"GitHub API: {r.status_code} — {r.text}")
