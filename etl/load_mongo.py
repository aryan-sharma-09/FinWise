#!/usr/bin/env python3
"""Load the FinWise MongoDB collections from MySQL - a small ETL script.

This is the INTEGRATION part of Person 3's work. It copies data out of
Member 1's MySQL database into the MongoDB collections.

ETL stands for Extract, Transform, Load:
  * Extract   - read the data out of MySQL (four SELECTs).
  * Transform - turn each SQL row into a MongoDB document (a Python dict).
  * Load      - write those documents into the MongoDB collections.

MySQL is the single source of truth. This script only ever READS MySQL and
WRITES MongoDB, so it is safe to run again at any time and cannot corrupt
MySQL. Running it twice gives exactly the same result as running it once.

Run it with:

    python etl/load_mongo.py

Every value is synthetic sample data - not real financial information.

Contents
  Q_STOCK_FUNDAMENTALS  - stocks, joined to their sector
  Q_PORTFOLIOS          - portfolios, joined to their owner
  Q_TRANSACTIONS        - transactions, joined to their ticker symbol
  Q_SNAPSHOTS           - portfolio snapshot rows
  to_float, to_text     - turn MySQL values into MongoDB-friendly values
  build_*_documents     - turn rows into documents, one function per collection
  load_collection       - replace one collection with a list of documents
  main                  - runs Extract, then Transform + Load
"""

import sys
from pathlib import Path

# Let this script import db.py (Member 1's MySQL helpers, in python/) and
# mongo_db.py (the MongoDB connection helper, in mongodb/).
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(PROJECT_ROOT / "mongodb"))

import db
import mongo_db

# ---------------------------------------------------------------------------
# EXTRACT - one plain SELECT per collection. Each one only reads MySQL.
# ---------------------------------------------------------------------------
Q_STOCK_FUNDAMENTALS = """
    SELECT s.stock_id,
           s.ticker_symbol,
           s.company_name,
           sec.sector_name,
           s.current_price,
           s.market_cap_millions,
           s.pe_ratio,
           s.dividend_yield,
           s.price_as_of
    FROM stocks AS s
    JOIN sectors AS sec ON sec.sector_id = s.sector_id
    ORDER BY s.stock_id
"""

Q_PORTFOLIOS = """
    SELECT p.portfolio_id,
           p.portfolio_name,
           u.user_id,
           u.username,
           u.full_name
    FROM portfolios AS p
    JOIN users AS u ON u.user_id = p.user_id
    ORDER BY p.portfolio_id
"""

Q_TRANSACTIONS = """
    SELECT t.transaction_id,
           t.portfolio_id,
           s.ticker_symbol,
           t.transaction_type,
           t.quantity,
           t.price_per_unit,
           t.transaction_date,
           t.notes
    FROM transactions AS t
    JOIN stocks AS s ON s.stock_id = t.stock_id
    ORDER BY t.transaction_id
"""

Q_SNAPSHOTS = """
    SELECT snapshot_id,
           portfolio_id,
           snapshot_date,
           total_market_value,
           total_cost_basis,
           holdings_count
    FROM portfolio_snapshots
    ORDER BY snapshot_id
"""


# ---------------------------------------------------------------------------
# TRANSFORM - tiny value converters used by the build functions below.
# ---------------------------------------------------------------------------
def to_float(value):
    """Turn a MySQL DECIMAL into a plain float (or None).

    MongoDB stores numbers fine; using float keeps this demo simple. This is
    a copy of the MySQL data, so losing a little DECIMAL precision is fine.
    """
    if value is None:
        return None
    return float(value)


def to_text(value):
    """Turn a value (such as a DATE) into text (or None).

    PyMongo cannot store a date object directly, so dates become strings
    such as "2025-03-14".
    """
    if value is None:
        return None
    return str(value)


def build_stock_documents(rows):
    """Turn stock + sector rows into stock_fundamentals documents."""
    documents = []
    for row in rows:
        documents.append({
            "_id": row["stock_id"],
            "ticker": row["ticker_symbol"],
            "company_name": row["company_name"],
            "sector": row["sector_name"],
            "price": to_float(row["current_price"]),
            "market_cap_millions": to_float(row["market_cap_millions"]),
            "pe_ratio": to_float(row["pe_ratio"]),
            "dividend_yield": to_float(row["dividend_yield"]),
            "price_as_of": to_text(row["price_as_of"]),
        })
    return documents


def build_portfolio_documents(rows):
    """Turn portfolio + owner rows into portfolios documents."""
    documents = []
    for row in rows:
        documents.append({
            "_id": row["portfolio_id"],
            "portfolio_name": row["portfolio_name"],
            "user_id": row["user_id"],
            "username": row["username"],
            "owner_full_name": row["full_name"],
        })
    return documents


def build_transaction_documents(rows):
    """Turn transaction + stock rows into transactions documents."""
    documents = []
    for row in rows:
        documents.append({
            "_id": row["transaction_id"],
            "portfolio_id": row["portfolio_id"],
            "ticker": row["ticker_symbol"],
            "transaction_type": row["transaction_type"],
            "quantity": to_float(row["quantity"]),
            "price_per_unit": to_float(row["price_per_unit"]),
            "transaction_date": row["transaction_date"],
            "notes": row["notes"],
        })
    return documents


def build_snapshot_documents(rows):
    """Turn snapshot rows into portfolio_snapshots documents."""
    documents = []
    for row in rows:
        documents.append({
            "_id": row["snapshot_id"],
            "portfolio_id": row["portfolio_id"],
            "snapshot_date": to_text(row["snapshot_date"]),
            "total_market_value": to_float(row["total_market_value"]),
            "total_cost_basis": to_float(row["total_cost_basis"]),
            "holdings_count": row["holdings_count"],
        })
    return documents


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
def load_collection(database, name, documents):
    """Replace one collection's documents, and return how many were stored.

    We delete everything first and then insert, so running the ETL twice
    gives exactly the same result as running it once (no duplicates).
    """
    collection = database[name]
    collection.delete_many({})
    if documents:
        collection.insert_many(documents)
    return collection.count_documents({})


def main():
    """Run the ETL: read MySQL, then write the MongoDB collections."""
    if not mongo_db.server_available():
        print("Cannot reach MongoDB. Is mongod running?")
        print("See docs/mongodb_module.md for setup steps.")
        return 1

    print("=" * 62)
    print("FinWise MongoDB ETL  (MySQL -> MongoDB)")
    print("=" * 62)
    print("!! WARNING: this REPLACES the documents in these collections:")
    print("!!   " + ", ".join(mongo_db.COLLECTIONS))
    print("!! MySQL is only read - it is never modified.")
    print()

    # ---- Extract: read everything from MySQL first ------------------------
    # Reading first means a MySQL error cannot leave MongoDB half-updated.
    conn = db.get_connection()
    try:
        stock_rows = db.fetch_all(conn, Q_STOCK_FUNDAMENTALS)
        portfolio_rows = db.fetch_all(conn, Q_PORTFOLIOS)
        transaction_rows = db.fetch_all(conn, Q_TRANSACTIONS)
        snapshot_rows = db.fetch_all(conn, Q_SNAPSHOTS)
    finally:
        conn.close()

    # ---- Transform + Load: one collection at a time -----------------------
    database = mongo_db.get_database()
    print("Loaded into MongoDB database '" + database.name + "':")

    stored = load_collection(database, "stock_fundamentals",
                             build_stock_documents(stock_rows))
    print("  stock_fundamentals: " + str(stored) + " document(s)")

    stored = load_collection(database, "portfolios",
                             build_portfolio_documents(portfolio_rows))
    print("  portfolios: " + str(stored) + " document(s)")

    stored = load_collection(database, "transactions",
                             build_transaction_documents(transaction_rows))
    print("  transactions: " + str(stored) + " document(s)")

    stored = load_collection(database, "portfolio_snapshots",
                             build_snapshot_documents(snapshot_rows))
    print("  portfolio_snapshots: " + str(stored) + " document(s)")

    print()
    print("Sample data only - not real financial information.")
    print("Next step:  python mongodb/mongo_demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
