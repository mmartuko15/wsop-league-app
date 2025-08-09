
import streamlit as st, pandas as pd, base64
from io import BytesIO
from pathlib import Path

import base64, requests, pandas as pd
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def pools_balance(pools_df, pool):
    if pools_df is None or pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

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


st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

# Header
col_logo, col_title = st.columns([1,4])
with col_logo:
    st.image("league_logo.png", use_column_width=True)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Admin")
    st.caption("Upload tracker, ingest events, manage Second Chance opt-ins, and High Hand info.")

st.divider()

# Sidebar: data source
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

# Sidebar: GitHub publish settings
st.sidebar.header("Publish to Player Home")
owner_repo = st.sidebar.text_input("GitHub repo (owner/repo)", value="youruser/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")
gh_token = st.secrets.get("GITHUB_TOKEN", "")
if not gh_token:
    gh_token = st.sidebar.text_input("GitHub token (repo scope)", type="password")

# KPIs
pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
wsop_total = pools_balance(pools,"WSOP")
bounty_total = pools_balance(pools,"Bounty")
highhand_total = pools_balance(pools,"High Hand")
nightly_total = pools_balance(pools,"Nightly")

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

# Build leaderboard (works with one event)
def build_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in sheet_map.items():
        if name.startswith("Event_") and name.endswith("_Standings") and "Player" in df.columns:
            t = df[["Player","Place","#Eliminated"]].copy()
            t.rename(columns={"#Eliminated":"KOs"}, inplace=True)
            t["Points"] = t["Place"].map(POINTS).fillna(0)
            frames.append(t)
    if not frames:
        return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    all_ev = pd.concat(frames, ignore_index=True)
    g = all_ev.groupby("Player", as_index=False).agg(
        Total_Points=("Points","sum"),
        Total_KOs=("KOs","sum"),
        Events_Played=("Points","count")
    )
    g = g.sort_values(["Total_Points","Total_KOs"], ascending=[False,False]).reset_index(drop=True)
    g.index = g.index + 1
    g.rename(columns={"Total_Points":"Total Points","Total_KOs":"Total KOs","Events_Played":"Events Played"}, inplace=True)
    return g

tabs = st.tabs(["Leaderboard","Events","Add New Event from Timer Log","Opt-Ins (Admin)","High Hand (Admin)","Pools Ledger","Supplies","Download/Publish"])

# Leaderboard
with tabs[0]:
    lb = build_leaderboard(sheet_map)
    if lb.empty:
        st.info("No event standings found yet.")
    else:
        st.dataframe(lb, use_container_width=True)

# Events
with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

# Add New Event from Timer Log
with tabs[2]:
    st.subheader("Upload the timer's event log (HTML/CSV export)")
    new_log = st.file_uploader("Timer Log Export", type=["html","csv","txt"], key="newlog_admin")
    if new_log is not None:
        try:
            # Parse
            raw = new_log.read()
            try:
                html = base64.b64decode(raw).decode("utf-8","ignore")
            except Exception:
                html = raw.decode("utf-8","ignore")
            tables = pd.read_html(html)
            ps = tables[0].copy()
            rp = tables[1].copy()

            standings = ps[["Place","Payout","Name","#Eliminated","Eliminated By"]].rename(columns={"Name":"Player","#Eliminated":"KOs"})
            standings["Place"] = standings["Place"].astype(int)
            standings["KOs"] = standings["KOs"].fillna(0).astype(int)
            standings["Points"] = standings["Place"].map(POINTS).fillna(0)
            standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
            win_idx = standings.index[standings["Place"]==1]
            if len(win_idx):
                standings.loc[win_idx[0],"Bounty $ (KOs*5)"] += 5

            standings["Payout_Amount"] = standings["Payout"].apply(parse_money)

            # Determine next event #
            ev_nums = [int(n.split("_")[1]) for n in sheet_map.keys() if n.startswith("Event_") and n.endswith("_Standings")]
            ev_next = (max(ev_nums)+1) if ev_nums else 1

            events = sheet_map.get("Events", pd.DataFrame())
            e_date = str(events[events["Event #"]==ev_next]["Date"].iloc[0]) if not events.empty and not events[events["Event #"]==ev_next].empty else "2025-01-01"

            # Players list from BuyIn row
            buyin_row = rp.iloc[0]
            players_list = [p.strip() for p in str(buyin_row.get("Players","")).split(",") if p.strip()]
            n_players = len(players_list)

            # Auto-add new players to Players sheet
            players_sheet = sheet_map.get("Players", pd.DataFrame(columns=["Player","Initial Buy-In Paid","Active"])).copy()
            existing = set(players_sheet["Player"]) if not players_sheet.empty else set()
            for p in players_list:
                if p not in existing:
                    players_sheet.loc[len(players_sheet)] = [p, 200.0, True]
            sheet_map["Players"] = players_sheet

            # Pools ledger
            pools = sheet_map.get("Pools_Ledger", pd.DataFrame(columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])).copy()
            def add_ledger(date, ev, typ, pool, amount, immediate, note):
                nonlocal pools
                pools.loc[len(pools)] = [date, ev, typ, pool, amount, immediate, note]

            add_ledger(e_date, ev_next, "Accrual", "WSOP", 200*n_players, "", "Initial buy-ins ($200 x players)")
            add_ledger(e_date, ev_next, "Accrual", "Nightly", 45*n_players, "", "Nightly payout funding ($45 x players)")
            add_ledger(e_date, ev_next, "Accrual", "Bounty", 5*n_players, "", "Bounty pool funding ($5 x players)")
            add_ledger(e_date, ev_next, "Accrual", "WSOP", 3*n_players, "", "WSOP addl funding ($3 x players)")
            add_ledger(e_date, ev_next, "Accrual", "High Hand", 2*n_players, "", "High hand funding ($2 x players)")
            add_ledger(e_date, ev_next, "Payout", "Nightly", float(standings["Payout_Amount"].sum()), "Yes", "Paid out on event night based on finish order")
            sheet_map["Pools_Ledger"] = pools

            # Supplies: ensure $100 tip for this event
            supplies = sheet_map.get("Supplies", pd.DataFrame(columns=["Event #","Date","Item","Amount","Notes"])).copy()
            if not supplies[(supplies["Event #"]==ev_next) & (supplies["Item"]=="Server Tip")].any().any():
                supplies.loc[len(supplies)] = [ev_next, e_date, "Server Tip", 100.00, "Auto-added"]
            sheet_map["Supplies"] = supplies

            # Save standings
            sheet_map[f"Event_{ev_next}_Standings"] = standings

            st.success(f"Ingested event #{ev_next}. Use 'Download/Publish' tab to export.")
        except Exception as e:
            st.error(f"Could not add event: {e}")

# Opt-Ins (Admin)
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

# High Hand (Admin)
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

# Pools Ledger
with tabs[5]:
    st.dataframe(sheet_map.get("Pools_Ledger", pd.DataFrame()), use_container_width=True)

# Supplies
with tabs[6]:
    st.dataframe(sheet_map.get("Supplies", pd.DataFrame()), use_container_width=True)

# Download / Publish
with tabs[7]:
    st.subheader("Export your changes")
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as writer:
        for name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f:
        updated_bytes = f.read()
    st.download_button("Download updated tracker (.xlsx)", data=updated_bytes, file_name="tracker.xlsx")

    st.markdown("---")
    st.subheader("Publish to Player Home (GitHub)")
    if st.button("Publish tracker.xlsx to GitHub"):
        if not owner_repo or not branch or not gh_token:
            st.error("Please provide repo, branch, and a GitHub token (repo scope).")
        else:
            status, text = github_put_file(owner_repo, "tracker.xlsx", branch, gh_token, updated_bytes, "Update tracker.xlsx from Admin app")
            if status in (200,201):
                st.success("Published to GitHub. Player Home will update automatically.")
            else:
                st.error(f"GitHub API response: {status} — {text}")
