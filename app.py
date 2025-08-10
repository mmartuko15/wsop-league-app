

import streamlit as st, pandas as pd, re, base64, requests, json, time
from io import BytesIO
from datetime import datetime

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    neg = s.startswith("(") and s.endswith(")")
    if neg: s = s[1:-1]
    try:
        v = float(s); return -v if neg else v
    except: return 0.0

def pools_balance_robust(df, pool_name):
    if df is None or df.empty: return 0.0
    cols = {re.sub(r'[^a-z0-9]','', str(c).lower()): c for c in df.columns}
    tcol = cols.get("type"); pcol = cols.get("pool"); acol = cols.get("amount") or cols.get("amt")
    if not (tcol and pcol and acol): return 0.0
    tmp = pd.DataFrame({
        "type": df[tcol].astype(str).str.strip().str.lower(),
        "pool": df[pcol].astype(str).str.strip().str.lower(),
        "amt": df[acol].apply(parse_money)
    })
    tmp["sign"] = tmp["type"].map({"accrual":1,"payout":-1}).fillna(1)
    return float((tmp[tmp["pool"]==pool_name.lower()]["amt"]*tmp[tmp["pool"]==pool_name.lower()]["sign"]).sum())

def read_tracker_bytes(b): return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")
def read_local_tracker():
    try:
        with open("tracker.xlsx","rb") as f: b=f.read()
        return read_tracker_bytes(b), b
    except: return (None,None)

def github_put(owner_repo, path, branch, token, file_bytes, message):
    import base64
    url=f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    hdr={"Authorization":f"token {token}"} if token else {}
    def getsha():
        r=requests.get(url,headers=hdr,params={"ref":branch},timeout=20)
        if r.status_code==200: return r.json().get("sha")
        return None
    payload={"message":message,"content":base64.b64encode(file_bytes).decode(),"branch":branch}
    sha=getsha()
    if sha: payload["sha"]=sha
    r=requests.put(url,headers=hdr,json=payload,timeout=30)
    return r.status_code, r.text

def robust_leaderboard(sheets):
    frames=[]
    for name,df in (sheets or {}).items():
        if not isinstance(df,pd.DataFrame): continue
        n=str(name).lower()
        if not (n.startswith("event_") and n.endswith("_standings")): continue
        if df.empty: continue
        cols={re.sub(r'[^a-z0-9]','',c.lower()):c for c in df.columns}
        pcol=cols.get("player") or cols.get("name")
        plc=cols.get("place") or cols.get("rank") or cols.get("finish") or cols.get("position")
        kos=cols.get("kos") or cols.get("knockouts") or cols.get("eliminations") or cols.get("elims")
        if not (pcol and plc): continue
        t=pd.DataFrame()
        t["Player"]=df[pcol].astype(str).str.strip()
        t["Place"]=pd.to_numeric(df[plc],errors="coerce")
        t["KOs"]=pd.to_numeric(df[kos],errors="coerce").fillna(0).astype(int) if kos else 0
        t=t.dropna(subset=["Place"])
        t["Points"]=t["Place"].map(POINTS).fillna(0)
        frames.append(t)
    if not frames: return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    allv=pd.concat(frames,ignore_index=True)
    g=(allv.groupby("Player",as_index=False)
        .agg(Total_Points=("Points","sum"),Total_KOs=("KOs","sum"),Events_Played=("Points","count"))
        .sort_values(["Total_Points","Total_KOs"],ascending=[False,False]).reset_index(drop=True))
    g.index=g.index+1
    return g

def show_logo(st, primary="league_logo.jpg", fallback="league_logo.png"):
    # Do not ship any placeholder; just try to render if present
    try: st.image(primary, use_column_width=True)
    except Exception:
        try: st.image(fallback, use_column_width=True)
        except Exception: st.markdown("### Mark & Rose's WSOP League")

import streamlit as st, pandas as pd, re, json, time, requests
from datetime import datetime, date

st.set_page_config(page_title="WSOP League — Admin", page_icon="🛠️", layout="wide")

# Persisted Player URL
CFG_PATH = ".wsop_config.json"
def read_cfg():
    try:
        with open(CFG_PATH,"r") as f: return json.load(f)
    except: return {}
def write_cfg(d):
    with open(CFG_PATH,"w") as f: json.dump(d,f,indent=2)
cfg=read_cfg()
player_url=cfg.get("player_home_url","")

col1,col2 = st.columns([1,4])
with col1: show_logo(st)
with col2: st.markdown("### Mark & Rose's WSOP League — Admin")

st.sidebar.header("Player Home Refresh")
player_url = st.sidebar.text_input("Player Home URL (persisted)", value=player_url, placeholder="https://<your-player-app>")
if st.sidebar.button("Save Player URL to repo"):
    cfg["player_home_url"]=player_url; write_cfg(cfg); st.sidebar.success("Saved")
if player_url:
    st.sidebar.write("Saved URL:"); st.sidebar.code(player_url)
    if st.sidebar.button("Test Player URL (open)"): st.sidebar.markdown(f"[Open Player Home]({player_url})")
    if st.sidebar.button("Send refresh ping now"):
        try:
            ts=int(time.time()); url=f"{player_url.rstrip('/')}/?refresh={ts}"
            r=requests.get(url,timeout=5)
            st.sidebar.success(f"Ping {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} (HTTP {r.status_code})")
        except Exception as e:
            st.sidebar.warning(f"Ping failed: {e}")

st.sidebar.markdown("---")
st.sidebar.header("Publish to Player Home (GitHub)")
owner_repo = st.sidebar.text_input("GitHub repo", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")
gh_token = st.secrets.get("GITHUB_TOKEN","")
if not gh_token: gh_token = st.sidebar.text_input("GitHub token (repo)", type="password")

st.sidebar.markdown("---")
st.sidebar.header("Data Source")
default_map, default_bytes = read_local_tracker()
up = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"])
if up is not None:
    tracker_bytes = up.read(); sheets = read_tracker_bytes(tracker_bytes)
elif default_map is not None:
    st.sidebar.info("Using repo default: tracker.xlsx"); sheets = default_map; tracker_bytes = default_bytes
else:
    st.info("Upload tracker.xlsx or add it to the repo."); st.stop()

# High Hand last updated
hh = sheets.get("HighHand_Info", pd.DataFrame())
if not hh.empty and "Last Updated" in hh.columns:
    try: st.caption(f"High Hand last updated: {str(hh['Last Updated'].iloc[0])}")
    except: pass

# KPIs
pools = sheets.get("Pools_Ledger", pd.DataFrame())
st.columns(5)[0].metric("WSOP Pool", f"${pools_balance_robust(pools,'WSOP'):,.2f}")
st.columns(5)[1].metric("Seat Value (each of 5)", f"${(pools_balance_robust(pools,'WSOP')/5 if pools is not None else 0):,.2f}")
st.columns(5)[2].metric("Bounty Pool (live)", f"${pools_balance_robust(pools,'Bounty'):,.2f}")
st.columns(5)[3].metric("High Hand (live)", f"${pools_balance_robust(pools,'High Hand'):,.2f}")
st.columns(5)[4].metric("Nightly Pool (post-payout)", f"${pools_balance_robust(pools,'Nightly'):,.2f}")

tabs = st.tabs(["Leaderboard","High Hand (Admin)","Pools Ledger","Download/Publish"])

with tabs[0]:
    st.dataframe(robust_leaderboard(sheets), use_container_width=True)

with tabs[1]:
    st.subheader("High Hand (Admin)")
    df = sheets.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if df.empty: df.loc[0]=["","","","",""]
    holder = st.text_input("Current Holder", value=str(df.at[0,"Current Holder"] or ""))
    hand = st.text_input("Hand Description", value=str(df.at[0,"Hand Description"] or ""))
    override = st.text_input("Display Value (override)", value=str(df.at[0,"Display Value (override)"] or ""))
    note = st.text_area("Note", value=str(df.at[0,"Note"] or ""))
    if st.button("Save High Hand Info"):
        df.at[0,"Current Holder"]=(holder or "").strip()
        df.at[0,"Hand Description"]=(hand or "").strip()
        df.at[0,"Display Value (override)"]=(override or "").strip()
        df.at[0,"Last Updated"]=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        df.at[0,"Note"]=(note or "").strip()
        sheets["HighHand_Info"]=df
        st.success("Saved High Hand info.")
        st.caption(f"Last Updated now: {df.at[0,'Last Updated']}")

with tabs[2]:
    st.dataframe(pools, use_container_width=True)

with tabs[3]:
    st.subheader("Export your changes")
    import io
    with pd.ExcelWriter("updated_tracker.xlsx", engine="openpyxl") as w:
        for name,df in sheets.items():
            df.to_excel(w, sheet_name=str(name)[:31], index=False)
    with open("updated_tracker.xlsx","rb") as f: updated = f.read()
    st.download_button("Download updated tracker (.xlsx)", data=updated, file_name="tracker.xlsx")

    st.markdown("---")
    st.subheader("Publish to Player Home (GitHub)")
    if st.button("Publish tracker.xlsx to GitHub"):
        if not owner_repo or not branch or not gh_token:
            st.error("Provide repo, branch, and GITHUB_TOKEN secret.")
        else:
            code, resp = github_put(owner_repo, "tracker.xlsx", branch, gh_token, updated, "Update tracker.xlsx from Admin (v1.8.8f)")
            if code in (200,201):
                st.success("Published to GitHub.")
                if player_url:
                    import time
                    ts=int(time.time())
                    link=f"{player_url.rstrip('/')}/?refresh={ts}"
                    st.markdown(f"**Open Player Home (refresh)** → [{link}]({link})")
            else:
                st.error(f"GitHub API: {code} — {resp}")
