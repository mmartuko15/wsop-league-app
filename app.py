
import streamlit as st, pandas as pd, re, base64
from io import BytesIO

import base64, requests, pandas as pd, re
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def read_tracker_bytes(b: bytes) -> dict:
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f: b = f.read()
        return (read_tracker_bytes(b), b)
    except Exception:
        return (None, None)

def pools_balance(df, pool):
    if df is None or df.empty: return 0.0
    d = df[df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def robust_leaderboard(sheet_map: dict) -> pd.DataFrame:
    def norm_cols(df):
        m = {}
        for c in df.columns:
            m[c] = re.sub(r'[^a-z0-9]','', str(c).lower())
        return df.rename(columns=m)
    def pick(colset,*cands):
        for c in cands:
            if c in colset: return c
        return None
    frames = []
    for name, df in (sheet_map or {}).items():
        if not isinstance(df, pd.DataFrame): continue
        nm = str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df.empty: continue
        d2 = norm_cols(df)
        cols = set(d2.columns)
        p = pick(cols,"player","name"); pl = pick(cols,"place","rank","finish","position"); ko = pick(cols,"kos","knockouts","eliminations","elims","eliminated")
        if not p or not pl: continue
        t = pd.DataFrame()
        t["Player"] = d2[p].astype(str).str.strip()
        t["Place"] = pd.to_numeric(d2[pl], errors="coerce")
        t["KOs"] = pd.to_numeric(d2[ko], errors="coerce").fillna(0).astype(int) if ko else 0
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

def gh_get_sha(repo, path, branch, token):
    u = f"https://api.github.com/repos/{repo}/contents/{path}"
    h = {"Authorization": f"token {token}"} if token else {}
    r = requests.get(u, headers=h, params={"ref": branch}, timeout=20)
    if r.status_code==200: return r.json().get("sha")
    return None

def gh_put(repo, path, branch, token, file_bytes, message):
    import base64 as b64
    u = f"https://api.github.com/repos/{repo}/contents/{path}"
    h = {"Authorization": f"token {token}"} if token else {}
    sha = gh_get_sha(repo, path, branch, token)
    payload = {"message": message, "content": b64.b64encode(file_bytes).decode("utf-8"), "branch": branch}
    if sha: payload["sha"] = sha
    r = requests.put(u, headers=h, json=payload, timeout=30)
    return r.status_code, r.text


st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")
col_logo, col_title = st.columns([1,4])
with col_logo: st.image("league_logo.png", use_column_width=True)
with col_title:
    st.markdown("### Mark & Rose's WSOP League — Admin")
    st.caption("Upload tracker, ingest events, manage Second Chance opt-ins, High Hand, Buy-Ins.")

st.divider()

# Data source
st.sidebar.header("Data Source")
default_map, default_bytes = read_local_tracker()
uploaded = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"])
if uploaded is not None:
    tracker_bytes = uploaded.read()
    sheet_map = read_tracker_bytes(tracker_bytes)
elif default_map is not None:
    st.sidebar.info("Using repo default: tracker.xlsx")
    sheet_map = default_map
    tracker_bytes = default_bytes
else:
    st.info("Upload your tracker .xlsx or add tracker.xlsx to repo root.")
    st.stop()

# GitHub publish
st.sidebar.header("Publish to Player Home")
repo = st.sidebar.text_input("GitHub repo (owner/repo)", "youruser/wsop-league-app")
branch = st.sidebar.text_input("Branch", "main")
token = st.secrets.get("GITHUB_TOKEN", "") or st.sidebar.text_input("GitHub token (repo scope)", type="password")

# KPIs
pools = sheet_map.get("Pools_Ledger", pd.DataFrame())
k1,k2,k3,k4,k5 = st.columns(5)
wsop_total = pools_balance(pools,"WSOP"); bounty_total = pools_balance(pools,"Bounty")
hh_total = pools_balance(pools,"High Hand"); nightly_total = pools_balance(pools,"Nightly")
k1.metric("WSOP Pool", f"${wsop_total:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop_total/5 if wsop_total else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty_total:,.2f}")
k4.metric("High Hand (live)", f"${hh_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly_total:,.2f}")

tabs = st.tabs(["Leaderboard","Events","Add New Event","Opt-Ins (Admin)","High Hand (Admin)","Buy-Ins (Admin)","Player Finances","Pools Ledger","Supplies","Download/Publish"])

with tabs[0]:
    lb = robust_leaderboard(sheet_map)
    st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.dataframe(sheet_map.get("Events", pd.DataFrame()), use_container_width=True)

with tabs[2]:
    st.subheader("Upload timer export (HTML/CSV/TXT)")
    f = st.file_uploader("Timer Log", type=["html","csv","txt"], key="newlog")
    if f is not None:
        try:
            raw = f.read()
            try: html = base64.b64decode(raw).decode("utf-8","ignore")
            except Exception: html = raw.decode("utf-8","ignore")
            tables = pd.read_html(html)
            ps = tables[0].copy(); rp = tables[1].copy()
            # flexible cols
            norm = lambda df: {re.sub(r'[^a-z0-9]','',str(c).lower()): c for c in df.columns}
            psn = norm(ps)
            name_col = psn.get("name") or psn.get("player")
            place_col = psn.get("place") or psn.get("rank") or psn.get("finish") or psn.get("position")
            payout_col = psn.get("payout")
            kos_col = psn.get("kos") or psn.get("knockouts") or psn.get("eliminations") or psn.get("elims") or psn.get("eliminated")
            if not (name_col and place_col and payout_col):
                st.error("Timer log missing required columns (Name/Player, Place/Rank, Payout)."); st.stop()
            standings = ps[[place_col, payout_col, name_col] + ([kos_col] if kos_col else [])].copy()
            standings.columns = ["Place","Payout","Player"] + (["KOs"] if kos_col else [])
            if "KOs" not in standings.columns: standings["KOs"]=0
            standings["Place"] = pd.to_numeric(standings["Place"], errors="coerce")
            standings = standings.dropna(subset=["Place"])
            standings["KOs"] = pd.to_numeric(standings["KOs"], errors="coerce").fillna(0).astype(int)
            standings["Points"] = standings["Place"].map(POINTS).fillna(0)
            standings["Bounty $ (KOs*5)"] = standings["KOs"]*5
            w = standings.index[standings["Place"]==1]
            if len(w): standings.loc[w[0],"Bounty $ (KOs*5)"] += 5
            standings["Payout_Amount"] = standings["Payout"].apply(parse_money)
            # next event #
            ev_nums = [int(n.split("_")[1]) for n in sheet_map.keys() if str(n).startswith("Event_") and str(n).endswith("_Standings")]
            ev = (max(ev_nums)+1) if ev_nums else 1
            evtbl = sheet_map.get("Events", pd.DataFrame())
            e_date = str(evtbl[evtbl["Event #"]==ev]["Date"].iloc[0]) if not evtbl.empty and not evtbl[evtbl["Event #"]==ev].empty else ""
            # players list from buy-in row
            rpn = norm(rp); players_field = rpn.get("players") or list(rp.columns)[0]
            players = [p.strip() for p in str(rp.iloc[0][players_field]).split(",") if p.strip()]
            n = len(players)
            # add players to roster if new
            roster = sheet_map.get("Players", pd.DataFrame(columns=["Player","Active"])).copy()
            existing = set(roster["Player"]) if not roster.empty else set()
            to_add = [{"Player":p,"Active":True} for p in players if p not in existing]
            if to_add: roster = pd.concat([roster, pd.DataFrame(to_add)], ignore_index=True)
            sheet_map["Players"] = roster
            # pools ledger append
            pools = sheet_map.get("Pools_Ledger", pd.DataFrame(columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])).copy()
            accr = pd.DataFrame([
                [e_date, ev, "Accrual","WSOP",    200*n, "", "Initial buy-ins ($200 x players)"],
                [e_date, ev, "Accrual","Nightly", 45*n,  "", "Nightly payout funding ($45 x players)"],
                [e_date, ev, "Accrual","Bounty",  5*n,   "", "Bounty pool funding ($5 x players)"],
                [e_date, ev, "Accrual","WSOP",    3*n,   "", "WSOP addl funding ($3 x players)"],
                [e_date, ev, "Accrual","High Hand",2*n,  "", "High hand funding ($2 x players)"],
                [e_date, ev, "Payout","Nightly",  float(standings["Payout_Amount"].sum()), "Yes", "Paid out on event night based on finish order"],
            ], columns=["Date","Event #","Type","Pool","Amount","Immediate?","Note"])
            pools = pd.concat([pools, accr], ignore_index=True)
            sheet_map["Pools_Ledger"] = pools
            # supplies tip
            supplies = sheet_map.get("Supplies", pd.DataFrame(columns=["Event #","Date","Item","Amount","Notes"])).copy()
            mask = (supplies["Event #"]==ev) & (supplies["Item"]=="Server Tip")
            if supplies[mask].empty:
                supplies = pd.concat([supplies, pd.DataFrame([{"Event #":ev,"Date":e_date,"Item":"Server Tip","Amount":100.00,"Notes":"Auto-added"}])], ignore_index=True)
            sheet_map["Supplies"] = supplies
            # save standings
            sheet_map[f"Event_{ev}_Standings"] = standings
            st.success(f"Ingested event #{ev}. Use Download/Publish to export.")
        except Exception as e:
            st.error(f"Could not add event: {e}")

with tabs[3]:
    st.subheader("Second Chance Opt-Ins (Events 8–12)")
    players_df = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    all_players = sorted(players_df["Player"].dropna().unique().tolist()) if not players_df.empty else []
    ev = st.selectbox("Event #", list(range(8,13)))
    optins = sheet_map.get("SecondChance_OptIns", pd.DataFrame(columns=["Event #","Player","Opt-In (Y/N)","Buy-In ($)"])).copy()
    existing = set(optins[optins["Event #"]==ev]["Player"]) if not optins.empty else set()
    sel = st.multiselect("Players opting in", all_players, default=list(existing))
    if st.button("Save Opt-Ins"):
        optins = optins[optins["Event #"]!=ev]
        for p in sel: optins.loc[len(optins)] = [ev,p,"Y",100.00]
        sheet_map["SecondChance_OptIns"] = optins.sort_values(["Event #","Player"]).reset_index(drop=True)
        st.success("Saved opt-ins.")

with tabs[4]:
    st.subheader("High Hand Controls")
    hh = sheet_map.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if hh.empty: hh.loc[0]=["","","","",""]
    holder = st.text_input("Current Holder", value=str(hh.at[0,"Current Holder"]))
    hand = st.text_input("Hand Description", value=str(hh.at[0,"Hand Description"]))
    override = st.text_input("Display Value (override)", value=str(hh.at[0,"Display Value (override)"]))
    note = st.text_area("Note", value=str(hh.at[0,"Note"]))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"]=holder; hh.at[0,"Hand Description"]=hand
        hh.at[0,"Display Value (override)"]=override
        hh.at[0,"Last Updated"]=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        hh.at[0,"Note"]=note
        sheet_map["HighHand_Info"]=hh
        st.success("High Hand info saved.")

with tabs[5]:
    st.subheader("Record Series Buy-Ins ($200)")
    players_df = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    all_players = sorted(players_df["Player"].dropna().unique().tolist()) if not players_df.empty else []
    ledger = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount","Date","Method","Note"])).copy()
    c1,c2,c3,c4,c5 = st.columns([2,1,1,1,3])
    with c1: psel = st.selectbox("Player", all_players)
    with c2: amt = st.number_input("Amount", value=200.00, step=25.0)
    with c3: date = st.date_input("Date")
    with c4: method = st.selectbox("Method", ["Cash","Zelle","Venmo","Check","Other"])
    with c5: note = st.text_input("Note","")
    if st.button("Add Buy-In"):
        ledger.loc[len(ledger)] = [psel, float(amt), str(date), method, note]
        sheet_map["Series_BuyIns"] = ledger
        st.success("Buy-in recorded.")
    st.markdown("#### Current Buy-Ins")
    st.dataframe(ledger, use_container_width=True)

with tabs[6]:
    st.subheader("Per-Player Finances")
    # Build from event sheets + Series_BuyIns
    ev_sheets = [k for k in sheet_map.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    ev_frames = []
    for s in ev_sheets:
        df = sheet_map[s]
        cols = {re.sub(r'[^a-z0-9]','', c.lower()): c for c in df.columns}
        pcol = cols.get("player") or cols.get("name")
        payout_col = cols.get("payout") or cols.get("payoutamount")
        kos_col = cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
        if not (pcol and payout_col): continue
        t = pd.DataFrame()
        t["Player"] = df[pcol].astype(str).str.strip()
        t["Payout_Amount"] = df[payout_col].apply(parse_money)
        t["BountyEarned"] = (pd.to_numeric(df[kos_col], errors="coerce").fillna(0).astype(int)*5) if kos_col else 0
        ev_frames.append(t)
    all_rows = pd.concat(ev_frames, ignore_index=True) if ev_frames else pd.DataFrame(columns=["Player","Payout_Amount","BountyEarned"])
    roster = sheet_map.get("Players", pd.DataFrame(columns=["Player"]))
    base = roster[["Player"]].dropna().drop_duplicates().copy()
    events_played = all_rows.groupby("Player").size().rename("Events Played").to_frame()
    nightly_earned = all_rows.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned").to_frame()
    bounties_earned = all_rows.groupby("Player")["BountyEarned"].sum().rename("Bounties Earned").to_frame()
    buyins = sheet_map.get("Series_BuyIns", pd.DataFrame(columns=["Player","Amount"])).copy()
    initial_buyins = buyins.groupby("Player")["Amount"].sum().rename("Initial Buy-Ins Paid").to_frame() if not buyins.empty else pd.DataFrame(columns=["Initial Buy-Ins Paid"])
    out = base.merge(events_played, left_on="Player", right_index=True, how="left")
    out = out.merge(nightly_earned, left_on="Player", right_index=True, how="left")
    out = out.merge(bounties_earned, left_on="Player", right_index=True, how="left")
    out["Events Played"] = out["Events Played"].fillna(0).astype(int)
    out["Nightly Fees Paid"] = out["Events Played"] * 55.0
    out["Bounty Contributions Paid"] = out["Events Played"] * 5.0
    out = out.merge(initial_buyins, left_on="Player", right_index=True, how="left")
    for col in ["Nightly Payouts Earned","Bounties Earned","Initial Buy-Ins Paid"]:
        out[col] = out[col].fillna(0.0)
    out["Total Paid In"] = out["Initial Buy-Ins Paid"] + out["Nightly Fees Paid"]
    out["Total Earned"] = out["Nightly Payouts Earned"] + out["Bounties Earned"]
    out["Net Winnings"] = out["Total Earned"] - out["Total Paid In"]
    cols = ["Player","Events Played","Initial Buy-Ins Paid","Nightly Fees Paid","Bounty Contributions Paid","Nightly Payouts Earned","Bounties Earned","Total Paid In","Total Earned","Net Winnings"]
    st.dataframe(out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True), use_container_width=True)

with tabs[7]: st.dataframe(sheet_map.get("Pools_Ledger", pd.DataFrame()), use_container_width=True)
with tabs[8]: st.dataframe(sheet_map.get("Supplies", pd.DataFrame()), use_container_width=True)

with tabs[9]:
    st.subheader("Export your changes")
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as w:
        for name, df in sheet_map.items():
            df.to_excel(w, sheet_name=str(name)[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f: updated = f.read()
    st.download_button("Download updated tracker (.xlsx)", data=updated, file_name="tracker.xlsx")
    st.markdown("---"); st.subheader("Publish to Player Home (GitHub)")
    if st.button("Publish tracker.xlsx to GitHub"):
        if not repo or not branch or not token:
            st.error("Provide repo, branch, and GITHUB_TOKEN."); 
        else:
            status, text = gh_put(repo, "tracker.xlsx", branch, token, updated, "Update tracker.xlsx from Admin app")
            if status in (200,201): st.success("Published to GitHub. Player Home will update automatically.")
            else: st.error(f"GitHub API response: {status} — {text}")
