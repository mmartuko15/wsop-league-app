
import streamlit as st
import pandas as pd
from io import BytesIO
import base64

st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

# Header
c1, c2 = st.columns([1,4])
with c1: st.image("league_logo.png", use_column_width=True)
with c2:
    st.markdown("### Admin — Mark & Rose's WSOP League")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.sidebar.header("Tracker")
uploaded_tracker = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"], key="tracker")

@st.cache_data(show_spinner=False)
def read_tracker(file_bytes: bytes) -> dict:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=None, engine="openpyxl")

def write_tracker(sheet_map: dict) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheet_map.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    bio.seek(0)
    return bio.getvalue()

def pools_balance(pools_df, pool):
    if pools_df is None or pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

@st.cache_data(show_spinner=False)
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
        **{"Total Points":("Points","sum"), "Total KOs":("KOs","sum"), "Events Played":("Points","count")}
    )
    g = g.sort_values(["Total Points","Total KOs"], ascending=[False,False]).reset_index(drop=True)
    g.index = g.index + 1
    return g

def next_event_number(sheet_map: dict) -> int:
    ev_nums = []
    for name in sheet_map.keys():
        if name.startswith("Event_") and name.endswith("_Standings"):
            try: ev_nums.append(int(name.split("_")[1]))
            except: pass
    return (max(ev_nums)+1) if ev_nums else 1

def add_event_from_timer(sheet_map: dict, log_bytes: bytes):
    # Try base64 then raw html
    try:
        html = base64.b64decode(log_bytes).decode("utf-8","ignore")
    except Exception:
        html = log_bytes.decode("utf-8","ignore")

    tables = pd.read_html(html)
    player_summaries = tables[0].copy()
    raw_players_table = tables[1].copy()

    standings = player_summaries[["Place","Payout","Name","#Eliminated","Eliminated By"]].rename(
        columns={"Name":"Player","#Eliminated":"KOs"}
    )
    standings["Place"] = standings["Place"].astype(int)
    standings["KOs"] = standings["KOs"].fillna(0).astype(int)
    standings["Points"] = standings["Place"].map(POINTS).fillna(0)
    standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
    widx = standings.index[standings["Place"]==1]
    if len(widx): standings.loc[widx[0],"Bounty $ (KOs*5)"] += 5
    standings["Payout_Amount"] = standings["Payout"].apply(parse_money)

    # Event #
    ev_num = next_event_number(sheet_map)

    # Pools ledger & events & supplies
    pools = sheet_map.get("Pools_Ledger", pd.DataFrame(columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])).copy()
    events = sheet_map.get("Events", pd.DataFrame())
    event_date = str(events.loc[events["Event #"]==ev_num,"Date"].iloc[0]) if not events.empty and (events["Event #"]==ev_num).any() else "2025-01-01"

    buyin_row = raw_players_table.iloc[0]
    players_list = [p.strip() for p in str(buyin_row.get("Players","")).split(",") if p.strip()]
    n_players = len(players_list)

    # Auto-add new players to Players sheet
    players_sheet = sheet_map.get("Players", pd.DataFrame(columns=["Player","Initial Buy-In Paid","Active"])).copy()
    for p in players_list:
        if p not in players_sheet["Player"].values:
            players_sheet.loc[len(players_sheet)] = [p, 200.0, True]  # assume initial buy-in paid upon first appearance
    sheet_map["Players"] = players_sheet

    def add_ledger(date, ev, typ, pool, amount, immediate, note):
        nonlocal pools
        pools.loc[len(pools)] = [date, ev, typ, pool, amount, immediate, note]

    add_ledger(event_date, ev_num, "Accrual", "WSOP", 200*n_players, "", "Initial buy-ins ($200 x players)")
    add_ledger(event_date, ev_num, "Accrual", "Nightly", 45*n_players, "", "Nightly payout funding ($45 x players)")
    add_ledger(event_date, ev_num, "Accrual", "Bounty", 5*n_players, "", "Bounty pool funding ($5 x players)")
    add_ledger(event_date, ev_num, "Accrual", "WSOP", 3*n_players, "", "WSOP addl funding ($3 x players)")
    add_ledger(event_date, ev_num, "Accrual", "High Hand", 2*n_players, "", "High hand funding ($2 x players)")
    add_ledger(event_date, ev_num, "Payout", "Nightly", float(standings["Payout_Amount"].sum()), "Yes", "Paid out on event night based on finish order")
    sheet_map["Pools_Ledger"] = pools

    # Save standings
    sheet_map[f"Event_{ev_num}_Standings"] = standings

    # Ensure $100 server tip
    supplies = sheet_map.get("Supplies", pd.DataFrame(columns=["Event #","Date","Item","Amount","Notes"])).copy()
    if not supplies[(supplies["Event #"]==ev_num) & (supplies["Item"]=="Server Tip")].any().any():
        supplies.loc[len(supplies)] = [ev_num, event_date, "Server Tip", 100.00, "Auto-added"]
    sheet_map["Supplies"] = supplies

    # Recompute Admin & Leaderboard
    wsop_total = pools_balance(pools,"WSOP")
    bounty_total = pools_balance(pools,"Bounty")
    high_total = pools_balance(pools,"High Hand")
    nightly_total = pools_balance(pools,"Nightly")
    admin = pd.DataFrame({
        "Metric":[
            "WSOP Pool (live)","WSOP Seat Value (each of 5)",
            "Bounty Pool (live)","High Hand (live)",
            "Nightly Pool (post-payout)"
        ],
        "Value":[wsop_total, wsop_total/5 if wsop_total else 0.0, bounty_total, high_total, nightly_total]
    })
    sheet_map["Admin_Dashboard"] = admin

    lb = build_leaderboard(sheet_map)
    sheet_map["Leaderboard"] = lb
    return sheet_map

# Require tracker
if uploaded_tracker is None:
    st.info("Upload your tracker .xlsx to begin.")
    st.stop()

sheet_map = read_tracker(uploaded_tracker.read())

# Tabs
tabs = st.tabs(["Dashboard","Add New Event","Opt‑Ins (Admin)","High Hand (Admin)","Download"])

# Dashboard KPIs
with tabs[0]:
    pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
    wsop_total = pools_balance(pools,"WSOP")
    bounty_total = pools_balance(pools,"Bounty")
    high_total = pools_balance(pools,"High Hand")
    nightly_total = pools_balance(pools,"Nightly")
    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
    k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
    k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
    k4.metric("High Hand (live)", f"${high_total:,.2f}")
    k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

    st.subheader("Leaderboard")
    lb = build_leaderboard(sheet_map)
    if lb.empty: st.info("Leaderboard will populate after events are loaded."); 
    else: st.dataframe(lb, use_container_width=True)

# Add New Event
with tabs[1]:
    st.subheader("Upload timer log (HTML/CSV export)")
    new_log = st.file_uploader("Timer Log Export", type=["html","csv","txt"], key="newlog")
    if new_log is not None:
        try:
            updated = add_event_from_timer(sheet_map.copy(), new_log.read())
            out_bytes = write_tracker(updated)
            st.download_button("Download updated tracker (.xlsx)", out_bytes, file_name="WSOP_League_Tracker_updated.xlsx")
            st.success("Event ingested. Download the updated tracker, then re-upload on the sidebar to refresh.")
        except Exception as e:
            st.error(f"Could not add event: {e}")

# Opt-Ins (Admin)
with tabs[2]:
    st.subheader("Second Chance Opt‑Ins (Events 8–12)")
    players = sheet_map.get("Players", pd.DataFrame())
    events = sheet_map.get("Events", pd.DataFrame())
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame(columns=["Event #","Player","Opt-In (Y/N)","Buy-In ($)"])).copy()
    if players.empty:
        st.info("No players found. Ingest at least one event or add players to the Players sheet.")
    else:
        ev = st.selectbox("Event", [8,9,10,11,12])
        roster = sorted(players["Player"].dropna().unique().tolist())
        current = optins[optins["Event #"]==ev]["Player"].tolist()
        selected = st.multiselect("Players opted in", roster, default=current)
        if st.button("Save Opt‑Ins"):
            # remove existing rows for this event
            optins = optins[optins["Event #"]!=ev]
            # add selected with $100
            for p in selected:
                optins.loc[len(optins)] = [ev, p, "Y", 100.00]
            sheet_map["SecondChance_OptIns"] = optins
            st.success("Opt‑ins saved. Download an updated tracker on the Download tab.")

# High Hand (Admin)
with tabs[3]:
    st.subheader("High Hand Status")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame({"Field":[],"Value":[]})).copy()
    def get_val(field, default=""):
        s = hh[hh["Field"]==field]["Value"]
        return s.iloc[0] if not s.empty else default
    holder = st.text_input("Current Holder", value=get_val("Current Holder",""))
    hand = st.text_input("Hand Description", value=get_val("Hand Description",""))
    disp_val = st.text_input("Display Value (override, optional)", value=get_val("Display Value (override)",""))
    note = st.text_area("Note", value=get_val("Note",""))
    if st.button("Save High Hand"):
        data = {
            "Field": ["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"],
            "Value": [holder, hand, disp_val, pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), note]
        }
        sheet_map["HighHand_Info"] = pd.DataFrame(data)
        st.success("High Hand info saved. Download an updated tracker on the Download tab.")

# Download
with tabs[4]:
    st.subheader("Download updated tracker")
    out_bytes = write_tracker(sheet_map)
    st.download_button("Download tracker (.xlsx)", out_bytes, file_name="WSOP_League_Tracker_updated.xlsx")
