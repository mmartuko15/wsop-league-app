
import streamlit as st, pandas as pd, time, requests
from io import BytesIO
from datetime import datetime

import streamlit as st, pandas as pd, requests, base64, re, json
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
    # Do not ship placeholder; try to show user's file if present.
    try:
        st.image(primary, use_column_width=True)
    except Exception:
        try:
            st.image(fallback, use_column_width=True)
        except Exception:
            st.markdown("### WSOP League")


st.set_page_config(page_title="WSOP League — Admin (PR flow)", page_icon="🛠️", layout="wide")

# Sidebar: repo, token, player URL persisted
st.sidebar.header("Repository & Auth")
owner_repo = st.sidebar.text_input("GitHub repo (owner/repo)", value="mmartuko15/wsop-league-app")
base_branch = st.sidebar.text_input("Target branch", value="main")
gh_token = st.secrets.get("GITHUB_TOKEN", "")
if not gh_token:
    gh_token = st.sidebar.text_input("GitHub token (repo/PR scope)", type="password")

st.sidebar.header("Player Home Refresh")
# Load/save .wsop_config.json in repo
def get_config_from_repo():
    try:
        url = f"https://api.github.com/repos/{owner_repo}/contents/.wsop_config.json"
        headers = {"Authorization": f"token {gh_token}"} if gh_token else {}
        r = requests.get(url, headers=headers, params={"ref": base_branch}, timeout=20)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"])
            return json.loads(content.decode("utf-8"))
    except Exception:
        pass
    return {}

cfg = get_config_from_repo()
player_url = st.sidebar.text_input("Player Home URL", value=cfg.get("player_url",""))
if st.sidebar.button("Save Player URL to repo"):
    try:
        # get current sha
        url = f"https://api.github.com/repos/{owner_repo}/contents/.wsop_config.json"
        headers = {"Authorization": f"token {gh_token}"} if gh_token else {}
        params = {"ref": base_branch}
        r = requests.get(url, headers=headers, params=params, timeout=20)
        sha = r.json().get("sha") if r.status_code==200 else None
        new_cfg = {"player_url": player_url, "updated": datetime.utcnow().isoformat()+"Z"}
        content_b64 = base64.b64encode(json.dumps(new_cfg, indent=2).encode("utf-8")).decode("utf-8")
        payload = {"message":"Update .wsop_config.json","content":content_b64,"branch":base_branch}
        if sha: payload["sha"]=sha
        r2 = requests.put(url, headers=headers, json=payload, timeout=20)
        if r2.status_code in (200,201):
            st.sidebar.success("Saved URL to repo.")
        else:
            st.sidebar.error(f"GitHub error {r2.status_code}: {r2.text[:200]}")
    except Exception as e:
        st.sidebar.error(f"Save failed: {e}")

if player_url:
    st.sidebar.write(f"Saved URL: {player_url}")
    if st.sidebar.button("Send refresh ping now"):
        try:
            ts = int(time.time())
            r = requests.get(player_url, params={"refresh": ts}, timeout=10)
            st.sidebar.success(f"Pinged at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        except Exception as e:
            st.sidebar.warning(f"Ping request sent (may be blocked): {e}")
    st.sidebar.markdown(f"[Open Player Home (refresh)]({player_url}?refresh={int(time.time())})")

st.title("WSOP League — Admin (PR Flow)")
col_logo, col_title = st.columns([1,5])
with col_logo: show_logo(st)
with col_title:
    st.caption("Manage tracker data and publish updates via Pull Request to satisfy branch protection rules.")

default_map, default_bytes = read_local_tracker()
uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])

if uploaded:
    tracker_bytes = uploaded.read()
    sheet_map = read_tracker_bytes(tracker_bytes)
elif default_map is not None:
    sheet_map = default_map
    tracker_bytes = default_bytes
else:
    st.info("Upload a tracker .xlsx to begin.")
    st.stop()

# KPI tiles
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

tabs = st.tabs(["Leaderboard","Events","High Hand (Admin)","Verify on GitHub (API)","Publish via Pull Request","Download/Export"])

with tabs[0]:
    st.dataframe(robust_leaderboard(sheet_map), use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    st.subheader("High Hand Controls")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if hh.empty:
        hh.loc[0] = ["","", "", "", ""]
    holder = st.text_input("Current Holder", value=str(hh.at[0,"Current Holder"] or ""))
    hand = st.text_input("Hand Description", value=str(hh.at[0,"Hand Description"] or ""))
    value_override = st.text_input("Display Value (override)", value=str(hh.at[0,"Display Value (override)"] or ""))
    note = st.text_area("Note", value=str(hh.at[0,"Note"] or ""))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"] = holder.strip()
        hh.at[0,"Hand Description"] = hand.strip()
        hh.at[0,"Display Value (override)"] = value_override.strip()
        hh.at[0,"Last Updated"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        hh.at[0,"Note"] = note.strip()
        sheet_map["HighHand_Info"] = hh
        st.success(f"Saved High Hand info. Last Updated now: {hh.at[0,'Last Updated']}")
    st.markdown("**Preview (will be written when you publish):**")
    st.dataframe(hh, use_container_width=True)

with tabs[3]:
    st.subheader("Verify tracker.xlsx on GitHub (API, main)")
    if st.button("Fetch tracker.xlsx from GitHub (API)"):
        try:
            headers = {"Authorization": f"token {gh_token}"} if gh_token else {}
            # Get latest commit touching tracker.xlsx
            commits_url = f"https://api.github.com/repos/{owner_repo}/commits"
            cr = requests.get(commits_url, headers=headers, params={"path":"tracker.xlsx","sha":base_branch}, timeout=20)
            latest_commit = None
            if cr.status_code == 200 and len(cr.json())>0:
                latest_commit = cr.json()[0]
            # Fetch contents
            url = f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx"
            r = requests.get(url, headers=headers, params={"ref": base_branch}, timeout=20)
            if r.status_code != 200:
                st.error(f"GitHub API HTTP {r.status_code}: {r.text[:200]}")
            else:
                content = base64.b64decode(r.json()["content"])
                gh_map = read_tracker_bytes(content)
                hh = gh_map.get("HighHand_Info", pd.DataFrame())
                st.success("Fetched from GitHub.")
                if latest_commit:
                    st.write(f"Latest commit touching tracker.xlsx: **{latest_commit.get('sha','')[:7]}** — {latest_commit.get('commit',{}).get('message','')[:80]}")
                st.markdown("**HighHand_Info from GitHub:**")
                st.dataframe(hh if not hh.empty else pd.DataFrame(), use_container_width=True)
        except Exception as e:
            st.error(f"Verify failed: {e}")

with tabs[4]:
    st.subheader("Publish tracker.xlsx via Pull Request")
    pr_branch = st.text_input("New branch name", value=f"wsop-update-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
    pr_title = st.text_input("PR title", value="Update tracker.xlsx from Admin app")
    if st.button("Create PR now"):
        try:
            headers = {"Authorization": f"token {gh_token}"} if gh_token else {}
            # 1) Get base SHA of main
            br = requests.get(f"https://api.github.com/repos/{owner_repo}/git/ref/heads/{base_branch}", headers=headers, timeout=20)
            if br.status_code != 200:
                st.error(f"Get base ref failed: {br.status_code}: {br.text[:200]}")
                st.stop()
            base_sha = br.json()["object"]["sha"]
            # 2) Create ref for new branch
            rr = requests.post(f"https://api.github.com/repos/{owner_repo}/git/refs", headers=headers, json={"ref": f"refs/heads/{pr_branch}","sha": base_sha}, timeout=20)
            if rr.status_code not in (200,201):
                st.error(f"Create branch failed: {rr.status_code}: {rr.text[:200]}")
                st.stop()
            # 3) Prepare Excel bytes from current sheet_map
            with BytesIO() as bio:
                with pd.ExcelWriter(bio, engine="openpyxl") as writer:
                    for name, df in sheet_map.items():
                        df.to_excel(writer, sheet_name=str(name)[:31], index=False)
                tracker_bytes2 = bio.getvalue()
            # 4) Upload contents to new branch
            put_url = f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx"
            payload = {"message": pr_title, "content": base64.b64encode(tracker_bytes2).decode("utf-8"), "branch": pr_branch}
            ur = requests.put(put_url, headers=headers, json=payload, timeout=30)
            if ur.status_code not in (200,201):
                st.error(f"Upload file failed: {ur.status_code}: {ur.text[:200]}")
                st.stop()
            # 5) Open PR
            pr_url = f"https://api.github.com/repos/{owner_repo}/pulls"
            pr_payload = {"title": pr_title, "head": pr_branch, "base": base_branch, "body":"Automated update from Admin app."}
            prr = requests.post(pr_url, headers=headers, json=pr_payload, timeout=20)
            if prr.status_code not in (200,201):
                st.error(f"Create PR failed: {prr.status_code}: {prr.text[:200]}")
                st.stop()
            pr_json = prr.json()
            st.success(f"PR created: #{pr_json.get('number')} — {pr_json.get('html_url')}")
            if player_url:
                st.markdown(f"[Open Player Home (refresh)]({player_url}?refresh={int(time.time())})")
        except Exception as e:
            st.error(f"PR publish failed: {e}")

with tabs[5]:
    st.subheader("Download current in-memory tracker")
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as writer:
        for name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f:
        st.download_button("Download tracker.xlsx", data=f.read(), file_name="tracker.xlsx")
