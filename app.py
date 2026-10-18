import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

st.set_page_config(
    page_title="FinWise Analytics Hub",
    page_icon="📈",
    layout="wide"
)

# Base path for dashboard data
DATA_DIR = Path(__file__).resolve().parent / "dashboards" / "data"

@st.cache_data
def load_data():
    positions = pd.read_csv(DATA_DIR / "pbi_positions.csv")
    sectors = pd.read_csv(DATA_DIR / "pbi_sectors.csv")
    performance = pd.read_csv(DATA_DIR / "pbi_performance.csv")
    hhi = pd.read_csv(DATA_DIR / "pbi_hhi.csv")
    fundamentals = pd.read_csv(DATA_DIR / "pbi_fundamentals.csv")

    if "ticker" in fundamentals.columns and "ticker_symbol" in positions.columns:
        positions = positions.merge(
            fundamentals, left_on="ticker_symbol", right_on="ticker", how="left"
        )
    return positions, sectors, performance, hhi

# Load datasets
try:
    df_pos, df_sec, df_perf, df_hhi = load_data()
except Exception as e:
    st.error(f"Error loading CSV files from {DATA_DIR}: {e}")
    st.stop()

# Header
st.title("📊 FinWise | Portfolio & Risk Analytics")
st.markdown("Interactive portfolio surveillance, sector exposures, and concentration tracking.")

# Sidebar - Portfolio Selection
portfolio_list = sorted(df_pos["portfolio_name"].dropna().unique().tolist())
selected_portfolio = st.sidebar.selectbox("Select Portfolio", portfolio_list)

# Filter datasets by selected portfolio
port_pos = df_pos[df_pos["portfolio_name"] == selected_portfolio]
current_port_id = port_pos["portfolio_id"].iloc[0] if not port_pos.empty else None

port_sec = df_sec[df_sec["portfolio_id"] == current_port_id] if current_port_id is not None else pd.DataFrame()
port_perf = df_perf[df_perf["portfolio_id"] == current_port_id] if current_port_id is not None else pd.DataFrame()
port_hhi = df_hhi[df_hhi["portfolio_id"] == current_port_id] if current_port_id is not None else pd.DataFrame()

# ----------------- Row 1: KPI Cards -----------------
total_market_val = port_pos["market_value"].sum() if "market_value" in port_pos.columns else 0.0
total_unrealized_pl = port_pos["unrealized_pl"].sum() if "unrealized_pl" in port_pos.columns else 0.0
hhi_value = port_hhi["hhi_score"].iloc[0] if not port_hhi.empty and "hhi_score" in port_hhi.columns else 0.0

col1, col2, col3 = st.columns(3)
col1.metric("Total Market Value", f"${total_market_val:,.2f}")
col2.metric("Total Unrealized P/L", f"${total_unrealized_pl:,.2f}", delta=f"{total_unrealized_pl:,.2f}")
col3.metric("HHI Concentration Index", f"{hhi_value:,.1f}")

st.divider()

# ----------------- Row 2: Charts -----------------
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Sector Allocation")
    if not port_sec.empty and "sector_name" in port_sec.columns and "sector_value" in port_sec.columns:
        fig_donut = px.pie(
            port_sec,
            names="sector_name",
            values="sector_value",
            hole=0.45,
            color_discrete_sequence=px.colors.qualitative.Plotly
        )
        fig_donut.update_layout(margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_donut, use_container_width=True)
    else:
        st.info("No sector breakdown data available for this portfolio.")

with chart_col2:
    st.subheader("Historical Performance Trend")
    if not port_perf.empty and "snapshot_date" in port_perf.columns and "total_market_value" in port_perf.columns:
        port_perf = port_perf.copy()
        port_perf["snapshot_date"] = pd.to_datetime(port_perf["snapshot_date"])
        port_perf = port_perf.sort_values("snapshot_date")
        fig_line = px.line(
            port_perf,
            x="snapshot_date",
            y="total_market_value",
            markers=True,
            labels={"snapshot_date": "Date", "total_market_value": "Portfolio Value ($)"}
        )
        fig_line.update_layout(margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("No historical performance data available for this portfolio.")

# ----------------- Row 3: Holdings Table -----------------
st.subheader("Current Holdings Detail")

display_cols = [
    col for col in [
        "ticker_symbol", "company_name", "sector_name", "quantity", 
        "average_cost_per_share", "current_price", "market_value", 
        "unrealized_pl", "pe_ratio", "dividend_yield"
    ] if col in port_pos.columns
]

if not port_pos.empty:
    st.dataframe(
        port_pos[display_cols],
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No active holdings found for this portfolio.")