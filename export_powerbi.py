import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Set project paths
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(PROJECT_ROOT / "mongodb"))

import db
import mongo_db
from analytics.risk import calculate_risk_metrics
from analytics.diversification import calculate_diversification
from analytics.literacy import explain_metrics

output_dir = PROJECT_ROOT / "dashboards" / "data"
output_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------------
# 1. Extract Member 1's analytical views from MySQL
# -------------------------------------------------------------------------
print("Connecting to Member 1's MySQL database...")
conn = db.get_connection()
try:
    positions_rows = db.fetch_all(conn, "SELECT * FROM v_portfolio_positions")
    sector_rows = db.fetch_all(conn, "SELECT * FROM v_sector_allocation")
    performance_rows = db.fetch_all(conn, "SELECT * FROM v_portfolio_performance")
    user_rows = db.fetch_all(conn, "SELECT * FROM v_user_summary")
finally:
    conn.close()

df_positions = pd.DataFrame(positions_rows)
df_sectors = pd.DataFrame(sector_rows)
df_performance = pd.DataFrame(performance_rows)
df_users = pd.DataFrame(user_rows)

# -------------------------------------------------------------------------
# 2. Extract Member 3's fundamentals collection from MongoDB
# -------------------------------------------------------------------------
print("Reading Member 3's MongoDB collections...")
if mongo_db.server_available():
    mongo_database = mongo_db.get_database()
    fundamentals_cursor = mongo_database["stock_fundamentals"].find({}, {"_id": 0})
    df_fundamentals = pd.DataFrame(list(fundamentals_cursor))
else:
    print("MongoDB offline: falling back to MySQL stocks table for fundamentals.")
    conn = db.get_connection()
    try:
        stocks_rows = db.fetch_all(conn, "SELECT ticker_symbol AS ticker, company_name, current_price AS price, pe_ratio, dividend_yield FROM stocks")
    finally:
        conn.close()
    df_fundamentals = pd.DataFrame(stocks_rows)

# -------------------------------------------------------------------------
# 3. Process via Member 2's Analytics Engine
# -------------------------------------------------------------------------
print("Calculating Member 2's risk and concentration metrics...")
# Compute HHI per portfolio
hhi_list = []
for pid, group in df_positions.groupby("portfolio_id"):
    hhi_val = round(float((group["portfolio_weight_percent"] ** 2).sum()), 2)
    hhi_list.append({"portfolio_id": pid, "hhi_score": hhi_val})

df_hhi = pd.DataFrame(hhi_list)

# -------------------------------------------------------------------------
# 4. Save tables for Power BI
# -------------------------------------------------------------------------
df_positions.to_csv(output_dir / "pbi_positions.csv", index=False)
df_sectors.to_csv(output_dir / "pbi_sectors.csv", index=False)
df_performance.to_csv(output_dir / "pbi_performance.csv", index=False)
df_fundamentals.to_csv(output_dir / "pbi_fundamentals.csv", index=False)
df_hhi.to_csv(output_dir / "pbi_hhi.csv", index=False)

print("\nSuccess! Exported 5 tables into 'dashboards/data/':")
print("1. pbi_positions.csv    (Member 1 SQL positions)")
print("2. pbi_sectors.csv      (Member 1 Sector distribution)")
print("3. pbi_performance.csv  (Member 1 Snapshot history)")
print("4. pbi_fundamentals.csv (Member 3 Mongo fundamentals)")
print("5. pbi_hhi.csv          (Member 2 Concentration scores)")