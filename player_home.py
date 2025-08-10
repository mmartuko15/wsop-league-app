
import streamlit as st, pandas as pd, base64, requests, re, json
from io import BytesIO

import streamlit as st, pandas as pd, requests, base64, re, json
from io import BytesIO

POINTS = {1:14,2:11,3:9,4:7,5:5,6:4,7:3,8:2,9:1,10:0.5}

def read_xlsx_bytes(b): 
    return pd.read_excel(BytesIO(b), sheet_name=None, engine="openpyxl")

def parse_money(x):
    if pd.isna(x): return 0.0
    if isinstance(x,(int,float)): return float(x)
    s = str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return 0.0

def pools_balance(df, pool):
    if df is None or df.empty: return 0.0
    c = {re.sub(r'[^a-z0-9]','',str(k).lower()):k for k in df.columns}
    t = c.get("type"); p=c.get("pool"); a=c.get("amount") or c.get("amt")
    if not (t and p and a): return 0.0
    z=df.copy()
    z["_type"]=z[t].astype(str).str.lower().str.strip()
    z["_pool"]=z[p].astype(str).str.lower().str.strip()
    z["_amt"]=z[a].apply(parse_money)
    z["_sign"]=z["_type"].map({"accrual":1,"payout":-1}).fillna(1)
    m=z["_pool"]==pool.lower()
    return float((z.loc[m,"_amt"]*z.loc[m,"_sign"]).sum())

def leaderboard(sheets):
    out=[]
    for name,df in (sheets or {}).items():
        nm=str(name).lower()
        if not (nm.startswith("event_") and nm.endswith("_standings")): continue
        if df is None or df.empty: continue
        cols={re.sub(r'[^a-z0-9]','',c.lower()):c for c in df.columns}
        p=cols.get("player") or cols.get("name")
        pl=cols.get("place") or cols.get("rank")
        k =cols.get("kos") or cols.get("knockouts") or cols.get("elims")
        if not (p and pl): continue
        t=pd.DataFrame()
        t["Player"]=df[p].astype(str).str.strip()
        t["Place"]=pd.to_numeric(df[pl],errors="coerce")
        t["KOs"]=pd.to_numeric(df[k],errors="coerce").fillna(0).astype(int) if k else 0
        t=t.dropna(subset=["Place"]); t["Points"]=t["Place"].map(POINTS).fillna(0)
        out.append(t)
    if not out: return pd.DataFrame(columns=["Player","Total Points","Total KOs","Events Played"])
    all=pd.concat(out,ignore_index=True)
    g=(all.groupby("Player",as_index=False)
       .agg(Total_Points=("Points","sum"), Total_KOs=("KOs","sum"), Events_Played=("Points","count"))
       .sort_values(["Total_Points","Total_KOs"],ascending=[False,False]).reset_index(drop=True))
    g.index=g.index+1
    return g

def gh_headers(token=None, extra=None):
    h={"Accept":"application/vnd.github+json"}
    if token: h["Authorization"]=f"token {token}"
    if extra: h.update(extra)
    return h

def gh_get_content(owner_repo, path, ref, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    r=requests.get(url, headers=gh_headers(token), params={"ref":ref}, timeout=30)
    return r

def gh_get_ref(owner_repo, branch, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/git/ref/heads/{branch}"
    return requests.get(url, headers=gh_headers(token), timeout=30)

def gh_create_ref(owner_repo, new_branch, from_sha, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/git/refs"
    payload={"ref":f"refs/heads/{new_branch}", "sha":from_sha}
    return requests.post(url, headers=gh_headers(token), json=payload, timeout=30)

def gh_put_content(owner_repo, path, branch, content_bytes, message, token=None, sha=None):
    url=f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    payload={"message":message, "content": base64.b64encode(content_bytes).decode("utf-8"), "branch": branch}
    if sha: payload["sha"]=sha
    return requests.put(url, headers=gh_headers(token), json=payload, timeout=60)

def gh_create_pr(owner_repo, head_branch, base_branch, title, body, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/pulls"
    payload={"title":title, "head":head_branch, "base":base_branch, "body":body}
    return requests.post(url, headers=gh_headers(token), json=payload, timeout=30)

def gh_latest_commit_for_file(owner_repo, path, branch, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/commits"
    r=requests.get(url, headers=gh_headers(token), params={"sha":branch,"path":path,"per_page":1}, timeout=30)
    if r.status_code==200 and r.json():
        j=r.json()[0]; return j.get("sha"), j
    return None, None

def gh_prs_for_commit(owner_repo, commit_sha, token=None):
    url=f"https://api.github.com/repos/{owner_repo}/commits/{commit_sha}/pulls"
    # special preview header to list PRs for commit
    h=gh_headers(token, extra={"Accept":"application/vnd.github.groot-preview+json"})
    r=requests.get(url, headers=h, timeout=30)
    if r.status_code==200: return r.json()
    return []


st.set_page_config(page_title="WSOP League — Player Home", page_icon="🃏", layout="wide")
st.title("WSOP League — Player Home")

# Load tracker
mode = st.sidebar.radio("Load tracker from", ["Repo file (default)","Upload file","Fetch from GitHub (no cache)"], index=0)

sheets=None; source=""
if mode=="Upload file":
    up=st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"])
    if up: sheets=read_xlsx_bytes(up.read()); source="Uploaded file"
elif mode=="Fetch from GitHub (no cache)":
    owner_repo=st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
    branch=st.sidebar.text_input("Branch", value="main")
    token = st.secrets.get("PLAYER_GITHUB_TOKEN","")
    if st.sidebar.button("Fetch via API now"):
        try:
            r=requests.get(f"https://api.github.com/repos/{owner_repo}/contents/tracker.xlsx", headers=gh_headers(token), params={"ref":branch}, timeout=30)
            r.raise_for_status()
            content=base64.b64decode(r.json()["content"])
            sheets=read_xlsx_bytes(content); source=f"GitHub API — {owner_repo}@{branch}"
            # Find latest commit touching file
            sha, meta = gh_latest_commit_for_file(owner_repo,"tracker.xlsx",branch,token)
            prnum = None
            if sha:
                prs = gh_prs_for_commit(owner_repo, sha, token)
                if isinstance(prs,list) and prs:
                    prnum = prs[0].get("number")
            last_updated = ""
            if "HighHand_Info" in sheets and not sheets["HighHand_Info"].empty:
                val = sheets["HighHand_Info"]["Last Updated"].iloc[0]
                last_updated = "" if pd.isna(val) else str(val)
            banner = f"Data source: {source}"
            if last_updated: banner += f" • High Hand last updated: {last_updated}"
            if sha: banner += f" • Commit: {sha[:7]}"
            if prnum: banner += f" • Merged PR: #{prnum}"
            st.info(banner)
        except Exception as e:
            st.error(f"Fetch failed: {e}")
else:
    try:
        with open("tracker.xlsx","rb") as f:
            sheets=read_xlsx_bytes(f.read()); source="Repo file (bundled)"
    except Exception:
        st.info("No bundled tracker.xlsx found. Upload one or use API fetch.")

if sheets is None: st.stop()

# KPIs
pools = sheets.get("Pools_Ledger", pd.DataFrame())
k1,k2,k3,k4,k5 = st.columns(5)
wsop=pools_balance(pools,"WSOP"); bounty=pools_balance(pools,"Bounty"); hh=pools_balance(pools,"High Hand"); night=pools_balance(pools,"Nightly")
k1.metric("WSOP Pool", f"${wsop:,.2f}"); k2.metric("Seat Value (x5)", f"${(wsop/5 if wsop else 0):,.2f}")
k3.metric("Bounty Pool", f"${bounty:,.2f}"); k4.metric("High Hand", f"${hh:,.2f}"); k5.metric("Nightly Pool", f"${night:,.2f}")

tabs=st.tabs(["Leaderboard","Nightly Payouts","Bounties","High Hand","Second Chance","Player Finances"])

with tabs[0]:
    lb=leaderboard(sheets); st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.write("Nightly payouts by event")
    ev=[k for k in sheets.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    for s in sorted(ev):
        df=sheets[s]; cols={re.sub(r'[^a-z0-9]','',c.lower()):c for c in df.columns}
        pcol=cols.get("player") or cols.get("name"); pl=cols.get("place") or cols.get("rank"); pay=cols.get("payout") or cols.get("payoutamount")
        if not pcol: continue
        view=pd.DataFrame(); view["Place"]=pd.to_numeric(df[pl],errors="coerce").astype("Int64") if pl else pd.Series(range(1,len(df)+1),dtype="Int64")
        view["Player"]=df[pcol].astype(str).str.strip()
        if pay: view["Payout"]=df[pay]
        st.write(f"**{s}**"); st.dataframe(view, use_container_width=True, hide_index=True)

with tabs[2]:
    st.write("Bounties per event")
    ev=[k for k in sheets.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
    for s in sorted(ev):
        df=sheets[s]; cols={re.sub(r'[^a-z0-9]','',c.lower()):c for c in df.columns}
        pcol=cols.get("player") or cols.get("name"); pl=cols.get("place") or cols.get("rank"); kcol=cols.get("kos") or cols.get("knockouts") or cols.get("elims")
        if not pcol: continue
        view=pd.DataFrame(); view["Place"]=pd.to_numeric(df[pl],errors="coerce").astype("Int64") if pl else pd.Series(range(1,len(df)+1),dtype="Int64")
        view["Player"]=df[pcol].astype(str).str.strip()
        view["KOs"]=pd.to_numeric(df[kcol],errors="coerce").fillna(0).astype(int) if kcol else 0
        view["Bounty $"]=view["KOs"]*5
        st.write(f"**{s}**"); st.dataframe(view, use_container_width=True, hide_index=True)
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

with tabs[3]:
    holder=hand=override=""; last=""
    if "HighHand_Info" in sheets and not sheets["HighHand_Info"].empty:
        row=sheets["HighHand_Info"].iloc[0]
        def clean(v): 
            if pd.isna(v): return ""
            s=str(v).strip()
            return "" if s.lower()=="nan" else s
        holder=clean(row.get("Current Holder","")); hand=clean(row.get("Hand Description",""))
        override=clean(row.get("Display Value (override)","")); last=clean(row.get("Last Updated",""))
    val = override if override else f"${hh:,.2f}"
    st.write(f"**Current Holder:** {holder or '—'}")
    st.write(f"**Hand:** {hand or '—'}")
    st.write(f"**Jackpot Value:** {val}")
    if last: st.caption(f"Last Updated: {last}")

with tabs[4]:
    optins = sheets.get("SecondChance_OptIns", pd.DataFrame())
    st.dataframe(optins, use_container_width=True)
    pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    st.write(f"**Second Chance Pool:** ${pool:,.2f}")

with tabs[5]:
    def finances(sheets):
        ev=[k for k in sheets.keys() if str(k).startswith("Event_") and str(k).endswith("_Standings")]
        rows=[]
        for s in ev:
            df=sheets[s]; cols={re.sub(r'[^a-z0-9]','',c.lower()):c for c in df.columns}
            p=cols.get("player") or cols.get("name"); pay=cols.get("payout") or cols.get("payoutamount"); k=cols.get("kos") or cols.get("knockouts") or cols.get("elims")
            if not (p and pay): continue
            t=pd.DataFrame(); t["Player"]=df[p].astype(str).str.strip()
            t["Payout_Amount"]=df[pay].apply(parse_money)
            t["BountyEarned"]=pd.to_numeric(df[k],errors="coerce").fillna(0).astype(int)*5 if k else 0
            rows.append(t)
        all=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=["Player","Payout_Amount","BountyEarned"])
        players = sheets.get("Players", pd.DataFrame(columns=["Player"]))
        base = players[["Player"]].dropna().drop_duplicates().copy()
        ev_played = all.groupby("Player").size().rename("Events Played").to_frame()
        nightly = all.groupby("Player")["Payout_Amount"].sum().rename("Nightly Payouts Earned").to_frame()
        bnty = all.groupby("Player")["BountyEarned"].sum().rename("Bounties Earned").to_frame()
        out = base.merge(ev_played, left_on="Player", right_index=True, how="left").merge(nightly, left_on="Player", right_index=True, how="left").merge(bnty, left_on="Player", right_index=True, how="left")
        out["Events Played"]=out["Events Played"].fillna(0).astype(int)
        out["Nightly Fees Paid"]=out["Events Played"]*55.0; out["Bounty Contributions Paid"]=out["Events Played"]*5.0
        out[["Nightly Payouts Earned","Bounties Earned"]]=out[["Nightly Payouts Earned","Bounties Earned"]].fillna(0.0)
        out["Total Paid In"]=out["Nightly Fees Paid"] # initial buy-ins excluded here for brevity
        out["Total Earned"]=out["Nightly Payouts Earned"]+out["Bounties Earned"]
        out["Net Winnings"]=out["Total Earned"]-out["Total Paid In"]
        cols=["Player","Events Played","Nightly Fees Paid","Bounty Contributions Paid","Nightly Payouts Earned","Bounties Earned","Total Paid In","Total Earned","Net Winnings"]
        return out[cols].sort_values(["Net Winnings","Total Earned"], ascending=[False,False]).reset_index(drop=True)
    st.dataframe(finances(sheets), use_container_width=True)
