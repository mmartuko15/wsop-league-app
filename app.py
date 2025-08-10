
import streamlit as st, pandas as pd, base64, re, requests, json
from io import BytesIO
from datetime import date, datetime

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
            st.markdown("### WSOP League")


st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo: show_logo(st)
with col_title:
    st.markdown("### WSOP League — Admin")
    st.caption("Upload tracker, ingest events, manage opt-ins, High Hand timestamp, and publish to Player Home.")

st.divider()

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

st.sidebar.header("Publish to Player Home")
owner_repo = st.sidebar.text_input("GitHub repo (owner/repo)", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")
gh_token = st.secrets.get("GITHUB_TOKEN", "") or st.sidebar.text_input("GitHub token (repo scope)", type="password")

if st.sidebar.button("Test GitHub connection"):
    ok, msg = github_test(owner_repo, branch, gh_token)
    (st.sidebar.success if ok else st.sidebar.error)(msg)

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

tabs = st.tabs(["Leaderboard","Events","Add Event","High Hand (timestamp only)","Pools Ledger","Download/Publish"])

with tabs[0]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb if not lb.empty else pd.DataFrame(), use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    st.subheader("Add New Event from Timer Log (HTML export)")
    new_log = st.file_uploader("Timer Log Export", type=["html","csv","txt"], key="newlog_admin")
    if new_log is not None:
        try:
            raw = new_log.read()
            try:
                html = base64.b64decode(raw).decode("utf-8","ignore")
            except Exception:
                html = raw.decode("utf-8","ignore")
            tables = pd.read_html(html)
            ps = tables[0].copy()
            rp = tables[1].copy()

            def n(df): return {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
            psn = n(ps)
            name_col   = psn.get("name") or psn.get("player")
            place_col  = psn.get("place") or psn.get("rank") or psn.get("finish") or psn.get("position")
            payout_col = psn.get("payout")
            kos_col    = psn.get("kos") or psn.get("eliminations") or psn.get("eliminated") or psn.get("knockouts") or psn.get("numeliminated")

            if not (name_col and place_col and payout_col):
                st.error("Timer log missing required columns (Name/Player, Place/Rank, Payout).")
                st.stop()

            standings = ps[[place_col, payout_col, name_col] + ([kos_col] if kos_col else [])].copy()
            standings.columns = ["Place","Payout","Player"] + (["KOs"] if kos_col else [])
            if "KOs" not in standings.columns: standings["KOs"] = 0
            standings["Place"] = pd.to_numeric(standings["Place"], errors="coerce")
            standings = standings.dropna(subset=["Place"])
            standings["KOs"] = pd.to_numeric(standings["KOs"], errors="coerce").fillna(0).astype(int)
            standings["Points"] = standings["Place"].map(POINTS).fillna(0)
            standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
            widx = standings.index[standings["Place"]==1]
            if len(widx): standings.loc[widx[0],"Bounty $ (KOs*5)"] += 5
            standings["Payout_Amount"] = standings["Payout"].apply(parse_money)

            ev_nums = [int(n.split("_")[1]) for n in sheet_map.keys() if str(n).startswith("Event_") and str(n).endswith("_Standings")]
            ev_next = (max(ev_nums)+1) if ev_nums else 1

            events_df = sheet_map.get("Events", pd.DataFrame())
            e_date = str(events_df[events_df["Event #"]==ev_next]["Date"].iloc[0]) if not events_df.empty and not events_df[events_df["Event #"]==ev_next].empty else str(date.today())

            def n2(df): return {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
            rpn = n2(rp)
            players_field = rpn.get("players") or list(rp.columns)[0]
            players_list = [p.strip() for p in str(rp.iloc[0][players_field]).split(",") if p.strip()]
            n_players = len(players_list)

            players_sheet = sheet_map.get("Players", pd.DataFrame(columns=["Player","Active"])).copy()
            existing = set(players_sheet["Player"]) if not players_sheet.empty else set()
            for p in players_list:
                if p not in existing:
                    new_row = {"Player": p, "Active": True}
                    players_sheet = pd.concat([players_sheet, pd.DataFrame([new_row])], ignore_index=True)
            sheet_map["Players"] = players_sheet

            pools = sheet_map.get("Pools_Ledger", pd.DataFrame(columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])).copy()
            accruals = pd.DataFrame([
                [e_date, ev_next, "Accrual","WSOP",      3*n_players,  "", "WSOP addl funding ($3 x players)"],
                [e_date, ev_next, "Accrual","Nightly",  45*n_players, "", "Nightly payout funding ($45 x players)"],
                [e_date, ev_next, "Accrual","Bounty",    5*n_players, "", "Bounty pool funding ($5 x players)"],
                [e_date, ev_next, "Accrual","High Hand", 2*n_players, "", "High hand funding ($2 x players)"],
                [e_date, ev_next, "Payout","Nightly",    float(standings["Payout_Amount"].sum()), "Yes", "Paid out on event night based on finish order"],
            ], columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])
            pools = pd.concat([pools, accruals], ignore_index=True)
            sheet_map["Pools_Ledger"] = pools

            supplies = sheet_map.get("Supplies", pd.DataFrame(columns=["Event #","Date","Item","Amount","Notes"])).copy()
            mask = (supplies["Event #"]==ev_next) & (supplies["Item"]=="Server Tip")
            if supplies[mask].empty:
                tip_row = pd.DataFrame([{"Event #":ev_next, "Date":e_date, "Item":"Server Tip", "Amount":100.00, "Notes":"Auto-added"}])
                supplies = pd.concat([supplies, tip_row], ignore_index=True)
            sheet_map["Supplies"] = supplies

            sheet_map[f"Event_{ev_next}_Standings"] = standings
            st.success(f"Ingested event #{ev_next}. Use 'Download/Publish' to export.")
        except Exception as e:
            st.error(f"Could not add event: {e}")

with tabs[3]:
    st.subheader("High Hand — timestamp only (players see live jackpot)")
    # Provide a single timestamp string to record an update moment if you want it in the workbook
    ts = pd.DataFrame([{"Last Updated": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")}])
    sheet_map["HighHand_Info"] = ts
    st.dataframe(ts, use_container_width=True)

with tabs[4]:
    st.subheader("Pools Ledger (read-only here)")
    st.dataframe(sheet_map.get("Pools_Ledger", pd.DataFrame()), use_container_width=True)

with tabs[5]:
    st.subheader("Export your changes")
    # Write the current in-memory workbook
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as writer:
        for name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f:
        updated_bytes = f.read()
    st.download_button("Download updated tracker (.xlsx)", data=updated_bytes, file_name="tracker.xlsx")

    st.markdown("---")
    st.subheader("Publish to Player Home (GitHub)")
    if st.button("Publish tracker.xlsx to GitHub"):
        if not owner_repo or not branch or not gh_token:
            st.error("Provide repo (owner/repo), branch, and GITHUB_TOKEN secret.")
        else:
            status, text = github_put_file(owner_repo, "tracker.xlsx", branch, gh_token, updated_bytes, "Update tracker.xlsx from Admin app (v1.9)")
            if status in (200,201):
                st.success("Published to GitHub. If Player reads Repo file, it will reflect this after restart; or use Player's Fetch via API.")
            else:
                st.error(f"GitHub API response: {status} — {text}")
