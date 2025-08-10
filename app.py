
import streamlit as st, pandas as pd, base64, re
from io import BytesIO
from pathlib import Path
from datetime import date

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
            st.markdown("### Mark & Rose's WSOP League")


st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo:
    show_logo(st)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Admin")
    st.caption("Upload tracker, ingest events, manage Second Chance opt-ins, High Hand, Buy-Ins, and Ledger.")

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
gh_token = st.secrets.get("GITHUB_TOKEN", "")
if not gh_token:
    gh_token = st.sidebar.text_input("GitHub token (repo scope)", type="password")

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

tabs = st.tabs(["Leaderboard","Events","Add New Event from Timer Log","Opt-Ins (Admin)","High Hand (Admin)","Buy-Ins (Admin)","Player Finances","Pools Ledger","Supplies","Download/Publish"])

with tabs[0]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb if not lb.empty else pd.DataFrame(), use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    st.subheader("Upload the timer's event log (HTML/CSV export)")
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
            if "KOs" not in standings.columns:
                standings["KOs"] = 0
            standings["Place"] = pd.to_numeric(standings["Place"], errors="coerce")
            standings = standings.dropna(subset=["Place"])
            standings["KOs"] = pd.to_numeric(standings["KOs"], errors="coerce").fillna(0).astype(int)
            standings["Points"] = standings["Place"].map(POINTS).fillna(0)
            standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
            widx = standings.index[standings["Place"]==1]
            if len(widx):
                standings.loc[widx[0],"Bounty $ (KOs*5)"] += 5
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
    st.subheader("Second Chance Opt-Ins (Events 8–12)")
    players_sheet = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    all_players = sorted(players_sheet["Player"].dropna().unique().tolist()) if not players_sheet.empty else []
    event_choice = st.selectbox("Event #", list(range(8,13)))
    current_optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame(columns=["Event #","Player","Opt-In (Y/N)","Buy-In ($)"])).copy()
    existing_for_event = set(current_optins[current_optins["Event #"]==event_choice]["Player"]) if not current_optins.empty else set()
    selected = st.multiselect("Players opting in", all_players, default=list(existing_for_event))
    if st.button("Save Opt-Ins"):
        current_optins = current_optins[current_optins["Event #"]!=event_choice]
        for p in selected:
            current_optins.loc[len(current_optins)] = [event_choice, p, "Y", 100.00]
        sheet_map["SecondChance_OptIns"] = current_optins.sort_values(["Event #","Player"]).reset_index(drop=True)
        st.success("Saved opt-ins.")

with tabs[4]:
    st.subheader("High Hand Controls")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if hh.empty:
        hh.loc[0] = ["","", "", "", ""]
    holder = st.text_input("Current Holder", value=str(hh.at[0,"Current Holder"]))
    hand = st.text_input("Hand Description", value=str(hh.at[0,"Hand Description"]))
    value_override = st.text_input("Display Value (override)", value=str(hh.at[0,"Display Value (override)"]))
    note = st.text_area("Note", value=str(hh.at[0,"Note"]))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"] = holder
        hh.at[0,"Hand Description"] = hand
        hh.at[0,"Display Value (override)"] = value_override
        hh.at[0,"Last Updated"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        hh.at[0,"Note"] = note
        sheet_map["HighHand_Info"] = hh
        st.success("High Hand info saved.")

with tabs[5]:
    st.subheader("Record Series Buy-Ins ($200)")
    players_sheet = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    all_players = sorted(players_sheet["Player"].dropna().unique().tolist()) if not players_sheet.empty else []
    ledger = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount","Date","Method","Note"])).copy()
    col1,col2,col3,col4,col5 = st.columns([2,1,1,1,3])
    with col1:
        psel = st.selectbox("Player", all_players)
    with col2:
        amt = st.number_input("Amount", value=200.00, step=25.0)
    with col3:
        date_val = st.date_input("Date")
    with col4:
        method = st.selectbox("Method", ["Cash","Zelle","Venmo","Check","Other"])
    with col5:
        note = st.text_input("Note", value="")
    if st.button("Add Buy-In"):
        ledger.loc[len(ledger)] = [psel, float(amt), str(date_val), method, note]
        sheet_map["Series_BuyIns"] = ledger
        st.success("Buy-in recorded.")
    st.markdown("#### Current Buy-Ins")
    st.dataframe(ledger, use_container_width=True)

with tabs[6]:
    st.subheader("Per-Player Finances")
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
