
import streamlit as st, pandas as pd, re, base64, requests
from io import BytesIO
from datetime import date, datetime

import pandas as pd, re, base64, requests
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

def read_tracker_bytes(b: bytes):
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f:
            b = f.read()
        return read_tracker_bytes(b)
    except Exception:
        return None

def pools_balance_robust(pools_df, pool_name):
    if pools_df is None or isinstance(pools_df, dict) or pools_df is pd.NA:
        return 0.0
    if pools_df is None or pools_df.empty: return 0.0
    df = pools_df.copy()
    cols = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
    tcol = cols.get("type"); pcol = cols.get("pool")
    acol = cols.get("amount") or cols.get("amt") or cols.get("value")
    if not (tcol and pcol and acol): return 0.0
    tmp = pd.DataFrame({
        "_type": df[tcol].astype(str).str.strip().str.lower(),
        "_pool": df[pcol].astype(str).str.strip().str.lower(),
        "_amt":  df[acol].apply(parse_money)
    })
    tmp["_sign"] = tmp["_type"].map({"accrual":1,"payout":-1}).fillna(1)
    return float((tmp.loc[tmp["_pool"]==pool_name.lower(), "_amt"] * tmp.loc[tmp["_pool"]==pool_name.lower(), "_sign"]).sum())

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        key = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
        pcol = key.get("player") or key.get("name")
        plcol = key.get("place") or key.get("rank") or key.get("finish") or key.get("position")
        kcol  = key.get("kos") or key.get("knockouts") or key.get("eliminations") or key.get("elims") or key.get("numeliminated") or key.get("eliminated")
        if not (pcol and plcol): continue
        t = pd.DataFrame({
            "Player": df[pcol].astype(str).str.strip(),
            "Place": pd.to_numeric(df[plcol], errors="coerce")
        })
        t["KOs"] = pd.to_numeric(df[kcol], errors="coerce").fillna(0).astype(int) if kcol else 0
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

def show_logo(st):
    # Do not ship/overwrite user's logo; try to load if present.
    try:
        st.image("league_logo.jpg", use_column_width=True)
    except Exception:
        try:
            st.image("league_logo.png", use_column_width=True)
        except Exception:
            st.markdown("### League")


st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

col_logo, col_title = st.columns([1,4])
with col_logo: show_logo(st)
with col_title:
    st.markdown("### WSOP League — Admin")
    st.caption("Upload tracker, ingest events, manage ledger/opt-ins, preview High Hand (from Excel).")

st.divider()

st.sidebar.header("Data Source")
uploaded = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"], key="tracker_admin")
if uploaded:
    sheet_map = read_tracker_bytes(uploaded.read())
    st.sidebar.success("Tracker loaded from upload.")
else:
    sheet_map = read_local_tracker()
    st.sidebar.info("Using repo tracker.xlsx.")

st.sidebar.header("GitHub (optional publish)")
owner_repo = st.sidebar.text_input("Repo (owner/repo)", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")
token = st.secrets.get("GITHUB_TOKEN","")
if not token:
    token = st.sidebar.text_input("GITHUB_TOKEN (repo scope)", type="password")

def backfill_kpis(sheet_map):
    pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
    wsop_total = pools_balance_robust(pools,"WSOP")
    bounty_total = pools_balance_robust(pools,"Bounty")
    highhand_total = pools_balance_robust(pools,"High Hand")
    nightly_total = pools_balance_robust(pools,"Nightly")
    return wsop_total, bounty_total, highhand_total, nightly_total

wsop_total, bounty_total, highhand_total, nightly_total = backfill_kpis(sheet_map if sheet_map else {})

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${highhand_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

tabs = st.tabs(["Leaderboard","Events","Add New Event (Timer Log)","Opt-Ins","High Hand (Preview)","Pools Ledger","Supplies","Download/Publish"])

with tabs[0]:
    lb = robust_leaderboard(sheet_map or {})
    st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.dataframe((sheet_map or {}).get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    st.subheader("Upload timer export (HTML)")
    new_log = st.file_uploader("Timer Log Export (HTML)", type=["html","csv","txt"], key="newlog")
    if new_log and sheet_map is not None:
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
                st.error("Timer log missing required columns (Name/Player, Place, Payout).")
            else:
                standings = ps[[place_col, payout_col, name_col] + ([kos_col] if kos_col else [])].copy()
                standings.columns = ["Place","Payout","Player"] + (["KOs"] if kos_col else [])
                if "KOs" not in standings.columns: standings["KOs"]=0
                standings["Place"] = pd.to_numeric(standings["Place"], errors="coerce")
                standings = standings.dropna(subset=["Place"])
                standings["KOs"] = pd.to_numeric(standings["KOs"], errors="coerce").fillna(0).astype(int)
                standings["Points"] = standings["Place"].map(POINTS).fillna(0)
                standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
                widx = standings.index[standings["Place"]==1]
                if len(widx): standings.loc[widx[0],"Bounty $ (KOs*5)"] += 5
                standings["Payout_Amount"] = standings["Payout"].apply(parse_money)

                ev_nums = [int(n.split("_")[1]) for n in (sheet_map or {}).keys() if str(n).startswith("Event_") and str(n).endswith("_Standings")]
                ev_next = (max(ev_nums)+1) if ev_nums else 1

                events_df = (sheet_map or {}).get("Events", pd.DataFrame())
                try:
                    e_date = str(events_df[events_df["Event #"]==ev_next]["Date"].iloc[0])
                except Exception:
                    e_date = str(date.today())

                # Update Players sheet
                rpn = n(rp)
                players_field = rpn.get("players") or list(rp.columns)[0]
                players_list = [p.strip() for p in str(rp.iloc[0][players_field]).split(",") if p.strip()]
                players_sheet = (sheet_map or {}).get("Players", pd.DataFrame(columns=["Player","Active"])).copy()
                existing = set(players_sheet["Player"]) if not players_sheet.empty else set()
                for p in players_list:
                    if p not in existing:
                        players_sheet.loc[len(players_sheet)] = [p, True]
                sheet_map["Players"] = players_sheet

                # Pools ledger accruals & nightly payout
                pools = (sheet_map or {}).get("Pools_Ledger", pd.DataFrame(columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])).copy()
                n_players = len(players_list)
                accruals = pd.DataFrame([
                    [e_date, ev_next, "Accrual","WSOP",      3*n_players,  "", "WSOP addl funding ($3 x players)"],
                    [e_date, ev_next, "Accrual","Nightly",  45*n_players, "", "Nightly payout funding ($45 x players)"],
                    [e_date, ev_next, "Accrual","Bounty",    5*n_players, "", "Bounty pool funding ($5 x players)"],
                    [e_date, ev_next, "Accrual","High Hand", 2*n_players, "", "High hand funding ($2 x players)"],
                    [e_date, ev_next, "Payout","Nightly",    float(standings["Payout_Amount"].sum()), "Yes", "Paid out on event night based on finish order"],
                ], columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])
                pools = pd.concat([pools, accruals], ignore_index=True)
                sheet_map["Pools_Ledger"] = pools

                # Supplies: add server tip if missing
                supplies = (sheet_map or {}).get("Supplies", pd.DataFrame(columns=["Event #","Date","Item","Amount","Notes"])).copy()
                mask = (supplies["Event #"]==ev_next) & (supplies["Item"]=="Server Tip")
                if supplies[mask].empty:
                    supplies.loc[len(supplies)] = [ev_next, e_date, "Server Tip", 100.00, "Auto-added"]
                sheet_map["Supplies"] = supplies

                # Save Event sheet
                sheet_map[f"Event_{ev_next}_Standings"] = standings
                st.success(f"Ingested event #{ev_next}. Remember to publish.")

        except Exception as e:
            st.error(f"Could not add event: {e}")

with tabs[3]:
    st.subheader("Second Chance Opt-Ins (Events 8–12)")
    players_sheet = (sheet_map or {}).get("Players", pd.DataFrame(columns=["Player"]))
    all_players = sorted(players_sheet["Player"].dropna().unique().tolist()) if not players_sheet.empty else []
    event_choice = st.selectbox("Event #", list(range(8,13)))
    current = (sheet_map or {}).get("SecondChance_OptIns", pd.DataFrame(columns=["Event #","Player","Opt-In (Y/N)","Buy-In ($)"])).copy()
    existing_for_event = set(current[current["Event #"]==event_choice]["Player"]) if not current.empty else set()
    selected = st.multiselect("Players opting in", all_players, default=list(existing_for_event))
    if st.button("Save Opt-Ins"):
        current = current[current["Event #"]!=event_choice]
        for p in selected:
            current.loc[len(current)] = [event_choice, p, "Y", 100.00]
        sheet_map["SecondChance_OptIns"] = current.sort_values(["Event #","Player"]).reset_index(drop=True)
        st.success("Saved opt-ins.")

with tabs[4]:
    st.subheader("High Hand (read from Excel)")
    hh = (sheet_map or {}).get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"]))
    st.dataframe(hh, use_container_width=True)

with tabs[5]:
    st.subheader("Pools Ledger")
    st.dataframe((sheet_map or {}).get("Pools_Ledger", pd.DataFrame()), use_container_width=True)
    st.caption("Accruals are added when you ingest events; add payouts for immediate High Hand or season-end as needed.")

with tabs[6]:
    st.subheader("Supplies")
    st.dataframe((sheet_map or {}).get("Supplies", pd.DataFrame()), use_container_width=True)

with tabs[7]:
    st.subheader("Export your changes")
    # rebuild workbook from current sheet_map
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as writer:
        for name, df in (sheet_map or {}).items():
            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f:
        updated_bytes = f.read()
    st.download_button("Download updated tracker (.xlsx)", data=updated_bytes, file_name="tracker.xlsx")
