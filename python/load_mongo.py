#!/usr/bin/env python3
"""Load the FinWise MongoDB read model from MySQL - a small ETL script.

ETL stands for Extract, Transform, Load:
  * Extract   - run read-only SELECTs against the FinWise MySQL database.
  * Transform - turn each SQL row into a MongoDB document (a Python dict).
  * Load      - write those documents into the MongoDB collections.

MySQL is the single source of truth. This script only ever READS MySQL and
WRITES MongoDB - it never modifies MySQL. Re-run it any time to rebuild the
read model:

    python python/load_mongo.py --yes

Every value is synthetic sample data - not real financial information.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (local module, path set above)
import mongo_db  # noqa: E402

# ---------------------------------------------------------------------------
# EXTRACT - one plain, parameter-free SELECT per collection. The database
# contract allows custom parameterized SELECTs against base tables like
# these; the views are for the hand-joined analytics we do not need here.
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
# TRANSFORM - small value converters shared by the builders below.
# ---------------------------------------------------------------------------
def to_float(value) -> float | None:
    """Convert a MySQL DECIMAL (a decimal.Decimal) to a plain float.

    MongoDB stores numbers natively, and float() keeps the demo simple. This
    is a read model, so we accept the tiny loss of DECIMAL precision here.
    """
    if value is None:
        return None
    return float(value)


def to_text(value) -> str | None:
    """Convert a value (e.g. a DATE) to text, or None.

    PyMongo cannot store a datetime.date directly, so DATE columns become
    'YYYY-MM-DD' strings.
    """
    if value is None:
        return None
    return str(value)


def build_stock_documents(rows: list[dict]) -> list[dict]:
    """Turn stock + sector rows into `stock_fundamentals` documents."""
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


def build_portfolio_documents(rows: list[dict]) -> list[dict]:
    """Turn portfolio + owner rows into `portfolios` documents."""
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


def build_transaction_documents(rows: list[dict]) -> list[dict]:
    """Turn transaction + stock rows into `transactions` documents."""
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


def build_snapshot_documents(rows: list[dict]) -> list[dict]:
    """Turn snapshot rows into `portfolio_snapshots` documents."""
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
def load_collection(database, name: str, documents: list[dict]) -> int:
    """Replace one collection's contents and return its document count.

    We delete-then-insert so running the ETL twice gives the same result as
    running it once (no duplicate documents).
    """
    collection = mongo_db.get_collection(name, database=database.name)
    mongo_db.delete_many(collection, {})
    if documents:
        mongo_db.insert_many(collection, documents)
    return mongo_db.count(collection)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy the FinWise read model from MySQL into MongoDB.")
    parser.add_argument("--mysql-db", default=None,
                        help="MySQL database to read "
                             "(default: FINWISE_DB_NAME).")
    parser.add_argument("--mongo-db", default=None,
                        help="MongoDB database to write "
                             "(default: FINWISE_MONGO_DB).")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the confirmation prompt.")
    args = parser.parse_args(argv)

    if not mongo_db.server_available():
        print("Cannot reach MongoDB. Is mongod running? "
              "See docs/mongodb_module.md for setup steps.")
        return 1

    target = mongo_db.get_database(args.mongo_db)
    mysql_name = args.mysql_db or db.DEFAULTS["FINWISE_DB_NAME"]

    print("=" * 62)
    print("FinWise MongoDB ETL  (MySQL -> MongoDB)")
    print("=" * 62)
    print(f"MySQL source   : {mysql_name}")
    print(f"MongoDB target : {target.name}")
    print()
    print("!! WARNING: this REPLACES the documents in these collections:")
    print("!!   " + ", ".join(mongo_db.COLLECTIONS))
    print("!! MySQL is only read - it is never modified.")
    print()

    if not args.yes:
        reply = input(f"Type the MongoDB database name '{target.name}' "
                      "to continue: ")
        if reply.strip() != target.name:
            print("Aborted - nothing was changed.")
            return 1

    # EXTRACT: read everything from MySQL first, so a read error cannot
    # leave the MongoDB collections half-updated.
    try:
        conn = db.get_connection(args.mysql_db)
    except Exception as exc:
        print(f"Could not connect to MySQL: {exc}")
        print("Hint: start MySQL and configure .env (see README).")
        return 1
    try:
        stock_rows = db.fetch_all(conn, Q_STOCK_FUNDAMENTALS)
        portfolio_rows = db.fetch_all(conn, Q_PORTFOLIOS)
        transaction_rows = db.fetch_all(conn, Q_TRANSACTIONS)
        snapshot_rows = db.fetch_all(conn, Q_SNAPSHOTS)
    finally:
        conn.close()

    # TRANSFORM + LOAD, one collection at a time.
    counts = {
        "stock_fundamentals": load_collection(
            target, "stock_fundamentals", build_stock_documents(stock_rows)),
        "portfolios": load_collection(
            target, "portfolios", build_portfolio_documents(portfolio_rows)),
        "transactions": load_collection(
            target, "transactions",
            build_transaction_documents(transaction_rows)),
        "portfolio_snapshots": load_collection(
            target, "portfolio_snapshots",
            build_snapshot_documents(snapshot_rows)),
    }

    print(f"Loaded into MongoDB database '{target.name}':")
    for name, total in counts.items():
        print(f"  {name}: {total} document(s)")
    print()
    print("Sample data only - not real financial information.")
    print("Next step:  python python/mongo_demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
