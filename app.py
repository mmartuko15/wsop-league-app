
import streamlit as st, pandas as pd, json, datetime
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


st.set_page_config(page_title="WSOP League — Admin (PR Flow)", page_icon="🛠️", layout="wide")
st.title("WSOP League — Admin")

# Load tracker from repo file or upload
default_map = None; default_bytes=None
try:
    with open("tracker.xlsx","rb") as f:
        default_bytes=f.read(); default_map=read_xlsx_bytes(default_bytes)
except Exception: pass

uploaded = st.sidebar.file_uploader("Upload tracker (.xlsx)", type=["xlsx"], key="admin_xlsx")
if uploaded: tracker_bytes = uploaded.read(); sheets=read_xlsx_bytes(tracker_bytes)
elif default_map is not None: st.sidebar.info("Using repo default tracker.xlsx"); sheets=default_map; tracker_bytes=default_bytes
else: st.info("Upload a tracker.xlsx to proceed."); st.stop()

# Sidebar: GitHub config
st.sidebar.header("GitHub Config")
owner_repo = st.sidebar.text_input("Owner/Repo", value="mmartuko15/wsop-league-app")
branch = st.sidebar.text_input("Base branch", value="main")
token = st.secrets.get("GITHUB_TOKEN","")
if not token:
    token = st.sidebar.text_input("GITHUB_TOKEN (repo scope)", type="password")

# Player Home URL persistence
st.sidebar.header("Player Home Refresh")
cfg_path = ".wsop_config.json"
cfg = {}
try:
    with open(cfg_path,"r") as f: cfg=json.load(f)
except Exception: cfg={}
player_url = st.sidebar.text_input("Player Home URL", value=cfg.get("player_url",""))
if st.sidebar.button("Save Player URL to repo file"):
    try:
        with open(cfg_path,"w") as f: json.dump({"player_url":player_url}, f)
        st.sidebar.success("Saved to .wsop_config.json (in repo). Commit it via your normal git flow.")
    except Exception as e:
        st.sidebar.error(f"Save failed: {e}")

if player_url:
    st.sidebar.write(f"Saved URL: {player_url}")
    st.sidebar.link_button("Test Player URL (open)", player_url)
    if st.sidebar.button("Open Player Home (refresh now)"):
        st.sidebar.success("Click the link below to refresh cache:")
        st.sidebar.link_button("Open with refresh", f"{player_url}?refresh={pd.Timestamp.utcnow().value}")

# KPIs
pools = sheets.get("Pools_Ledger", pd.DataFrame())
k1,k2,k3,k4,k5 = st.columns(5)
wsop = pools_balance(pools,"WSOP"); bounty=pools_balance(pools,"Bounty"); hhbal=pools_balance(pools,"High Hand"); night=pools_balance(pools,"Nightly")
k1.metric("WSOP Pool", f"${wsop:,.2f}"); k2.metric("Seat Value (x5)", f"${(wsop/5 if wsop else 0):,.2f}")
k3.metric("Bounty Pool", f"${bounty:,.2f}"); k4.metric("High Hand", f"${hhbal:,.2f}"); k5.metric("Nightly Pool", f"${night:,.2f}")

tabs = st.tabs(["Leaderboard","High Hand (Admin)","Verify on GitHub (API)","Publish via Pull Request"])

with tabs[0]:
    st.subheader("Leaderboard")
    lb=leaderboard(sheets)
    st.dataframe(lb, use_container_width=True)

with tabs[1]:
    st.subheader("High Hand")
    hh = sheets.get("HighHand_Info", pd.DataFrame(columns=["Current Holder","Hand Description","Display Value (override)","Last Updated","Note"])).copy()
    if hh.empty: hh.loc[0]=["","","","",""]
    holder = st.text_input("Current Holder", value=str(hh.at[0,"Current Holder"] or ""))
    hand   = st.text_input("Hand Description", value=str(hh.at[0,"Hand Description"] or ""))
    override = st.text_input("Display Value (override)", value=str(hh.at[0,"Display Value (override)"] or ""))
    note   = st.text_area("Note", value=str(hh.at[0,"Note"] or ""))
    if st.button("Save High Hand Info"):
        hh.at[0,"Current Holder"]=holder.strip()
        hh.at[0,"Hand Description"]=hand.strip()
        hh.at[0,"Display Value (override)"]=override.strip()
        hh.at[0,"Last Updated"]=pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        hh.at[0,"Note"]=note.strip()
        sheets["HighHand_Info"]=hh
        st.success(f"Saved. Last Updated now: {hh.at[0,'Last Updated']}")
    if "HighHand_Info" in sheets:
        st.markdown("**Preview**")
        st.dataframe(sheets["HighHand_Info"], use_container_width=True)

with tabs[2]:
    st.subheader("Verify tracker on GitHub (API)")
    if st.button("Fetch tracker.xlsx from GitHub"):
        try:
            r=gh_get_content(owner_repo,"tracker.xlsx",branch,token)
            if r.status_code!=200: st.error(f"GET contents failed: {r.status_code} — {r.text}"); 
            else:
                j=r.json(); content=base64.b64decode(j["content"])
                sm=read_xlsx_bytes(content)
                st.success("Fetched from GitHub API")
                sha, meta = gh_latest_commit_for_file(owner_repo,"tracker.xlsx",branch,token)
                st.write(f"Latest commit impacting tracker.xlsx on {branch}: {sha[:7] if sha else 'n/a'}")
                if "HighHand_Info" in sm:
                    st.dataframe(sm["HighHand_Info"], use_container_width=True)
                else:
                    st.warning("HighHand_Info sheet not found in GitHub copy.")
        except Exception as e:
            st.error(f"Verify failed: {e}")

with tabs[3]:
    st.subheader("Publish via Pull Request")
    # build updated tracker bytes from current sheets
    from openpyxl import Workbook
    import tempfile
    import pandas as pd
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=str(name)[:31], index=False)
    updated_bytes = buf.getvalue()

    # Branch name/title
    ts=pd.Timestamp.utcnow().strftime("%Y%m%d-%H%M%S")
    new_branch = st.text_input("New branch name", value=f"wsop-update-{ts}")
    pr_title = st.text_input("PR title", value=f"Update tracker.xlsx — {ts}")
    pr_body  = "Automated update from WSOP Admin (PR flow)."

    if st.button("Create PR now"):
        if not token or not owner_repo or not branch:
            st.error("Missing token/repo/branch.")
        else:
            # 1) Get base ref SHA
            r=gh_get_ref(owner_repo, branch, token); 
            if r.status_code!=200:
                st.error(f"Get base ref failed: {r.status_code} — {r.text}")
            else:
                base_sha = r.json()["object"]["sha"]
                # 2) Create new branch
                r2=gh_create_ref(owner_repo, new_branch, base_sha, token)
                if r2.status_code not in (201,422):
                    st.error(f"Create ref failed: {r2.status_code} — {r2.text}")
                else:
                    if r2.status_code==422:
                        st.info("Branch already exists; will reuse it.")
                    # 3) Determine if tracker.xlsx exists on new branch to include sha
                    cr=gh_get_content(owner_repo,"tracker.xlsx",new_branch,token)
                    sha=None
                    if cr.status_code==200:
                        try: sha=cr.json().get("sha")
                        except: sha=None
                    elif cr.status_code!=404:
                        st.error(f"Check existing content failed: {cr.status_code} — {cr.text}")
                        st.stop()
                    # 4) PUT content
                    put=gh_put_content(owner_repo,"tracker.xlsx",new_branch,updated_bytes, pr_title, token, sha=sha)
                    if put.status_code not in (200,201):
                        st.error(f"Upload file failed: {put.status_code}: {put.text}")
                    else:
                        # 5) Create PR
                        pr=gh_create_pr(owner_repo, new_branch, branch, pr_title, pr_body, token)
                        if pr.status_code in (201,200):
                            url=pr.json().get("html_url")
                            number=pr.json().get("number")
                            st.success(f"PR created: #{number}")
                            st.link_button("Open PR", url)
                        elif pr.status_code==422 and "A pull request already exists" in pr.text:
                            st.info("PR already exists for this branch.")
                        else:
                            st.error(f"Create PR failed: {pr.status_code} — {pr.text}")
