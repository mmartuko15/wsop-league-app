

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

import streamlit as st, pandas as pd, re, requests

st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")

c1,c2 = st.columns([1,4])
with c1: show_logo(st)
with c2: st.markdown("### Mark & Rose's WSOP League — Player Home"); st.caption("Countryside Country Club • Start 6:30 PM")
st.divider()

default_map, _ = read_local_tracker()
mode = st.sidebar.radio("Load tracker from", ["Repo file (default)", "Upload file"], index=0)
if mode=="Upload file":
    up = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if up:
        sheets = read_tracker_bytes(up.read()); src = "Uploaded file"
    else:
        sheets = default_map; src = "Repo file (bundled)"
else:
    sheets = default_map; src="Repo file (bundled)"

st.sidebar.markdown("---")
st.sidebar.subheader("Manual refresh (optional)")
owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Branch", value="main")
if st.sidebar.button("Fetch latest tracker from GitHub now"):
    try:
        url=f"https://raw.githubusercontent.com/{owner_repo}/{branch}/tracker.xlsx"
        r=requests.get(url,timeout=20); r.raise_for_status()
        sheets=read_tracker_bytes(r.content); src=f"GitHub raw — {owner_repo}@{branch}"
    except Exception as e:
        st.sidebar.error(f"Fetch failed: {e}")

if sheets is None:
    st.info("Waiting for tracker.xlsx…"); st.stop()

last_updated = ""
hh = sheets.get("HighHand_Info", pd.DataFrame())
if not hh.empty and "Last Updated" in hh.columns:
    try: last_updated = str(hh["Last Updated"].iloc[0])
    except: pass
st.info(f"**Data source:** {src}" + (f"  •  **High Hand last updated:** {last_updated}" if last_updated else ""))

pools = sheets.get("Pools_Ledger", pd.DataFrame())
wsop = pools_balance_robust(pools,"WSOP")
bounty = pools_balance_robust(pools,"Bounty")
hh_total = pools_balance_robust(pools,"High Hand")
nightly = pools_balance_robust(pools,"Nightly")
k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("WSOP Pool", f"${wsop:,.2f}")
k2.metric("Seat Value (each of 5)", f"${(wsop/5 if wsop else 0):,.2f}")
k3.metric("Bounty Pool (live)", f"${bounty:,.2f}")
k4.metric("High Hand (live)", f"${hh_total:,.2f}")
k5.metric("Nightly Pool (post-payout)", f"${nightly:,.2f}")

tabs = st.tabs(["Leaderboard","High Hand","About"])

with tabs[0]:
    st.dataframe(robust_leaderboard(sheets), use_container_width=True)

with tabs[1]:
    holder=hand=override=""
    if "HighHand_Info" in sheets and not sheets["HighHand_Info"].empty:
        def clean(v):
            import pandas as pd
            if pd.isna(v): return ""
            s=str(v).strip()
            return "" if s.lower()=="nan" else s
        df=sheets["HighHand_Info"]
        holder=clean(df.get("Current Holder",[""])[0] if "Current Holder" in df.columns else "")
        hand=clean(df.get("Hand Description",[""])[0] if "Hand Description" in df.columns else "")
        override=clean(df.get("Display Value (override)",[""])[0] if "Display Value (override)" in df.columns else "")
    def fmt_money(x):
        try:
            v=float(str(x).replace("$","").replace(",","")); return f"${v:,.2f}"
        except: return str(x)
    amt = fmt_money(override) if override else f"${hh_total:,.2f}"
    st.write(f"**Current Holder:** {holder or '—'}")
    st.write(f"**Hand:** {hand or '—'}")
    st.write(f"**Jackpot Value:** {amt}")

with tabs[2]:
    st.write("Read-only view of league standings and finances.")
