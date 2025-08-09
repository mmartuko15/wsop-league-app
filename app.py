
import streamlit as st
import pandas as pd
from pathlib import Path
from io import BytesIO

st.set_page_config(page_title="Mark & Rose's WSOP League", page_icon="🃏", layout="wide")

# --- Branding / Header ---
col_logo, col_title = st.columns([1,4])
with col_logo:
    st.image("league_logo.png", use_column_width=True)
with col_title:
    st.markdown("### Mark & Rose's WSOP League")
    st.caption("Countryside Country Club • Start 6:30 PM")

st.divider()

# --- Sidebar: data source ---
st.sidebar.header("Data")
uploaded = st.sidebar.file_uploader("Upload Tracker (.xlsx)", type=["xlsx"])
default_path = Path("WSOP_League_Tracker_2025-26_v1_1.xlsx")
if uploaded is not None:
    xls_bytes = uploaded.read()
    df_map = pd.read_excel(BytesIO(xls_bytes), sheet_name=None, engine="openpyxl")
elif default_path.exists():
    df_map = pd.read_excel(default_path, sheet_name=None, engine="openpyxl")
else:
    st.warning("Upload the tracker workbook to proceed.")
    st.stop()

def get(sheet):
    if sheet in df_map: return df_map[sheet].copy()
    return pd.DataFrame()

# --- Helpers ---
def pools_balance(pools_df, pool):
    if pools_df.empty: return 0.0
    d = pools_df[pools_df["Pool"]==pool].copy()
    if d.empty: return 0.0
    sign = d["Type"].map({"Accrual":1,"Payout":-1}).fillna(1)
    return float((d["Amount"]*sign).sum())

def fmt_money(x):
    try:
        return f"${x:,.2f}"
    except:
        return x

events = get("Events")
pools = get("Pools_Ledger")
supplies = get("Supplies")

# --- Top KPIs ---
wsop_total = pools_balance(pools,"WSOP")
bounty_total = pools_balance(pools,"Bounty")
highhand_total = pools_balance(pools,"High Hand")
nightly_total = pools_balance(pools,"Nightly")

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("WSOP Pool", fmt_money(wsop_total))
kpi2.metric("Seat Value (each of 5)", fmt_money(wsop_total/5 if wsop_total else 0))
kpi3.metric("Bounty Pool (live)", fmt_money(bounty_total))
kpi4.metric("High Hand (live)", fmt_money(highhand_total))
kpi5.metric("Nightly Payouts Accrued", fmt_money(nightly_total))

# --- Tabs ---
tabs = st.tabs(["Leaderboard","Events","Nightly Payouts","Bounties","High Hand","Second Chance","Redemptions Planner","Supplies","About"])

# Leaderboard (cumulative) - if present
with tabs[0]:
    if "Leaderboard" in df_map:
        lb = df_map["Leaderboard"].copy()
        st.dataframe(lb, use_container_width=True)
    else:
        st.info("Leaderboard will appear after multiple events are loaded.")

# Events
with tabs[1]:
    st.dataframe(events, use_container_width=True)
    st.caption("All events at Countryside Country Club • Start 6:30 PM")

# Nightly Payouts
with tabs[2]:
    if "Nightly_Payouts" in df_map:
        st.dataframe(df_map["Nightly_Payouts"], use_container_width=True)
    else:
        st.info("Nightly payouts will display as each event is parsed.")

# Bounties
with tabs[3]:
    if "Event_1_Standings" in df_map:
        e1 = df_map["Event_1_Standings"]
        view = e1[["Place","Player","KOs","Bounty $ (KOs*5)"]].rename(columns={"Bounty $ (KOs*5)":"Bounty $"})
        st.dataframe(view, use_container_width=True)
    st.write(f"**Bounty Pool (live):** {fmt_money(bounty_total)}")
    st.caption("Winner keeps their own $5 bounty; pool pays at final event.")

# High Hand
with tabs[4]:
    st.write(f"**High Hand Jackpot (live):** {fmt_money(highhand_total)}")
    st.caption("Pays at final event unless a Royal Flush winner opts for immediate payout.")

# Second Chance
with tabs[5]:
    optins = get("SecondChance_OptIns")
    sc_stand = get("SecondChance_Standings")
    st.subheader("Opt-Ins (Events 8–12)")
    st.dataframe(optins, use_container_width=True)
    st.subheader("Standings")
    st.dataframe(sc_stand, use_container_width=True)
    # Live SC pool = $100 per opt-in recorded
    if not optins.empty:
        sc_pool = (optins["Buy-In ($)"].fillna(0)).sum()
    else:
        sc_pool = 0.0
    st.write(f"**Second Chance Pool (live):** {fmt_money(sc_pool)}  \nPayout 50/30/20 at season end.")

# Redemptions Planner
with tabs[6]:
    st.subheader("Projected End-of-Season Payouts")
    # WSOP seats
    proj = []
    seat_val = wsop_total/5 if wsop_total else 0.0
    for i in range(1,6):
        proj.append({"Payout": f"WSOP Seat #{i}", "Projected Amount": seat_val})
    # Second chance (if available)
    optins = get("SecondChance_OptIns")
    sc_pool = (optins["Buy-In ($)"].fillna(0).sum()) if not optins.empty else 0.0
    if sc_pool:
        proj += [
            {"Payout":"Second Chance - 1st (50%)", "Projected Amount": sc_pool*0.50},
            {"Payout":"Second Chance - 2nd (30%)", "Projected Amount": sc_pool*0.30},
            {"Payout":"Second Chance - 3rd (20%)", "Projected Amount": sc_pool*0.20},
        ]
    # Bounty pool pays in full at season end
    proj.append({"Payout":"Bounties (season total)", "Projected Amount": bounty_total})
    # High hand - if no immediate payout recorded, pay live balance
    proj.append({"Payout":"High Hand Jackpot", "Projected Amount": highhand_total})
    proj_df = pd.DataFrame(proj)
    proj_df["Projected Amount"] = proj_df["Projected Amount"].map(lambda x: round(float(x),2))
    st.dataframe(proj_df, use_container_width=True)
    st.caption("Values update automatically as new logs are loaded, accruals posted, and any immediate Royal payouts recorded.")

# Supplies
with tabs[7]:
    st.dataframe(supplies, use_container_width=True)
    spent = supplies["Amount"].sum() if not supplies.empty else 0.0
    st.write(f"**Supplies Committed:** {fmt_money(spent)} (deducted from initial WSOP pool externally in ledger)")

# About
with tabs[8]:
    st.write("Style: gold & navy on black. Built for quick sharing of standings and pools with players.")
    st.write("Admin updates occur in the Excel tracker; upload a new workbook to refresh.")

