#!/usr/bin/env python3
"""Read-only ETL: mirror the FinWise MySQL read model into MongoDB.

Why a separate loader?
  * MySQL stays the SINGLE SOURCE OF TRUTH. This script only ever SELECTs
    from MySQL (through python/db.py) and writes the result into MongoDB;
    nothing is written back. The MongoDB collections are a denormalized,
    semi-structured read model for analytics and NoSQL demonstrations.

What it builds (see docs/mongodb_module.md):
  * stock_fundamentals   - one document per stock; embedded `sector` and
                           `fundamentals` sub-documents plus a `tags` array
                           (the semi-structured financial data).
  * portfolios           - one document per portfolio with an embedded
                           `holdings[]` array (denormalized positions).
  * transactions         - append-only BUY/SELL event log.
  * portfolio_snapshots  - point-in-time valuation records (time series).

Idempotency / duplicate prevention
  * Every document has a DETERMINISTIC _id derived from the MySQL primary
    key (snapshots use a composite "portfolio:date" key), so re-running the
    loader replaces documents instead of duplicating them.
  * Documents whose source row disappeared are pruned, so the mirror always
    matches MySQL exactly.

Safety
  * Source data is validated before it is written; rows missing required
    fields are skipped and reported, and an entirely empty source aborts
    with a clear error.
  * The target MongoDB database is overwritten (documents are replaced), so
    the loader asks for confirmation unless --yes is passed.
  * Credentials come from .env / environment variables (python/mongo_db.py);
    never from the command line.

Usage
  python python/load_mongo.py            # interactive confirmation
  python python/load_mongo.py --yes      # non-interactive
  python python/load_mongo.py --yes --mongo-db finwise
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (local module, path set above)
import mongo_db  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Source queries (MySQL, read-only). Keep these aligned with the database
# contract views/tables so the mirror tracks Member 1's schema.
# ---------------------------------------------------------------------------
Q_STOCKS = """
    SELECT s.stock_id, s.ticker_symbol, s.company_name,
           sec.sector_name, sec.description AS sector_description,
           s.current_price, s.market_cap_millions, s.pe_ratio,
           s.dividend_yield, s.price_as_of
    FROM stocks s
    JOIN sectors sec ON sec.sector_id = s.sector_id
    ORDER BY s.stock_id
"""

Q_POSITIONS = """
    SELECT portfolio_id, portfolio_name, user_id, username,
           stock_id, ticker_symbol, company_name, sector_name,
           quantity, average_cost_per_unit, current_price,
           market_value, unrealized_pl, portfolio_weight_percent,
           portfolio_total_value
    FROM v_portfolio_positions
    ORDER BY portfolio_id, market_value DESC
"""

Q_TRANSACTIONS = """
    SELECT t.transaction_id, t.portfolio_id, t.stock_id, s.ticker_symbol,
           t.transaction_type, t.quantity, t.price_per_unit,
           t.transaction_date, t.notes
    FROM transactions t
    JOIN stocks s ON s.stock_id = t.stock_id
    ORDER BY t.transaction_id
"""

Q_SNAPSHOTS = """
    SELECT snapshot_id, portfolio_id, snapshot_date,
           total_market_value, total_cost_basis, holdings_count
    FROM portfolio_snapshots
    ORDER BY portfolio_id, snapshot_date
"""


# ---------------------------------------------------------------------------
# Value coercion: MySQL returns DECIMAL/date types that BSON cannot encode.
# ---------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    """Coerce DECIMAL/int to float for BSON; preserve None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):  # avoid bool behaving as int 0/1
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)


def _dt(value: Any) -> Optional[datetime]:
    """Coerce date/datetime to a BSON datetime; preserve None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return value


def _text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# Pure document builders (no I/O) - unit-testable and reused by the tests.
# ---------------------------------------------------------------------------
def build_stock_fundamentals(rows: list[dict]) -> list[dict]:
    """Build stock_fundamentals documents from joined stocks+sectors rows."""
    docs = []
    for r in rows:
        docs.append({
            "_id": int(r["stock_id"]),
            "ticker": r["ticker_symbol"],
            "company_name": r["company_name"],
            # Embedded sub-document (semi-structured): the fixed MySQL
            # schema is denormalized into a nested object here.
            "sector": {
                "name": r["sector_name"],
                "description": _text(r.get("sector_description")),
            },
            "fundamentals": {
                "price": _num(r["current_price"]),
                "market_cap_millions": _num(r.get("market_cap_millions")),
                # Optional / not-meaningful values stay null rather than
                # being invented - PFE and BA have no P/E in the seed.
                "pe_ratio": _num(r.get("pe_ratio")),
                "dividend_yield": _num(r.get("dividend_yield")),
                "price_as_of": _dt(r.get("price_as_of")),
            },
            # Arrays are native in MongoDB; used by the demo's tag CRUD.
            "tags": [],
        })
    return docs


def build_portfolios(position_rows: list[dict]) -> list[dict]:
    """Build portfolio documents with an embedded holdings[] array.

    ``position_rows`` are the rows of the v_portfolio_positions view; they
    are grouped by portfolio so each portfolio becomes ONE document.
    """
    grouped: dict[int, dict] = {}
    for r in position_rows:
        pid = int(r["portfolio_id"])
        doc = grouped.get(pid)
        if doc is None:
            doc = {
                "_id": pid,
                "portfolio_name": r["portfolio_name"],
                "user": {
                    "user_id": int(r["user_id"]),
                    "username": r["username"],
                },
                "total_value": _num(r.get("portfolio_total_value")),
                "holdings": [],
            }
            grouped[pid] = doc
        doc["holdings"].append({
            "stock_id": int(r["stock_id"]),
            "ticker": r["ticker_symbol"],
            "company_name": r["company_name"],
            "sector": r["sector_name"],
            "quantity": _num(r["quantity"]),
            "avg_cost": _num(r["average_cost_per_unit"]),
            "current_price": _num(r["current_price"]),
            "market_value": _num(r["market_value"]),
            "unrealized_pl": _num(r["unrealized_pl"]),
            "weight_percent": _num(r.get("portfolio_weight_percent")),
        })
    return list(grouped.values())


def build_transactions(rows: list[dict]) -> list[dict]:
    """Build append-only transaction documents."""
    return [{
        "_id": int(r["transaction_id"]),
        "portfolio_id": int(r["portfolio_id"]),
        "stock_id": int(r["stock_id"]),
        "ticker": r["ticker_symbol"],
        "transaction_type": r["transaction_type"],
        "quantity": _num(r["quantity"]),
        "price_per_unit": _num(r["price_per_unit"]),
        "transaction_date": _dt(r["transaction_date"]),
        "notes": _text(r.get("notes")),
    } for r in rows]


def build_snapshots(rows: list[dict]) -> list[dict]:
    """Build snapshot documents keyed by snapshot_id."""
    return [{
        "_id": int(r["snapshot_id"]),
        "portfolio_id": int(r["portfolio_id"]),
        "snapshot_date": _dt(r["snapshot_date"]),
        "total_market_value": _num(r["total_market_value"]),
        "total_cost_basis": _num(r["total_cost_basis"]),
        "holdings_count": int(r["holdings_count"]),
    } for r in rows]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class ETLValidationError(RuntimeError):
    """Raised when the source data cannot produce a usable read model."""


def _validate(docs: list[dict], required: list[str], kind: str) -> list[dict]:
    """Return the documents that contain every required top-level field.

    Rows missing a required field are skipped (and counted) rather than
    crashing the whole load; an entirely empty result is an error.
    """
    valid, skipped = [], 0
    for d in docs:
        if all(k in d and d[k] is not None for k in required):
            valid.append(d)
        else:
            skipped += 1
    if skipped:
        print(f"  ! {kind}: skipped {skipped} row(s) with missing fields")
    if not valid:
        raise ETLValidationError(
            f"{kind}: the MySQL source returned no usable rows. "
            "Is the FinWise database loaded? Run python/load_mongo.py "
            "after python/load_database.py."
        )
    return valid


# ---------------------------------------------------------------------------
# Synchronization (idempotent: upsert by _id, prune vanished documents)
# ---------------------------------------------------------------------------
def ensure_indexes(database, verbose: bool = True) -> None:
    """Create the indexes the read model and pipelines rely on."""
    indexes = {
        "stock_fundamentals": [("ticker", True)],
        "portfolios": [("user.user_id", False)],
        "transactions": [
            ([("portfolio_id", 1), ("transaction_date", 1)], False),
            ("stock_id", False),
        ],
        "portfolio_snapshots": [
            ([("portfolio_id", 1), ("snapshot_date", 1)], False),
        ],
    }
    for name, specs in indexes.items():
        coll = database[name]
        for keys, unique in specs:
            key_list = keys if isinstance(keys, list) else [(keys, 1)]
            coll.create_index(key_list, unique=unique)
        if verbose:
            print(f"  - {name}: {len(specs)} index(es) ensured")


def sync_collection(collection, documents: list[dict]) -> int:
    """Upsert every document by _id and prune any that no longer exist.

    Works for any collection whose documents carry a deterministic _id.
    Returns the number of documents written.
    """
    ids = [d["_id"] for d in documents]
    # Prune documents whose source row disappeared (keeps the mirror exact).
    collection.delete_many({"_id": {"$nin": ids}})
    for doc in documents:
        collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return len(documents)


def sync_all(mysql_conn, mongo_database, verbose: bool = True) -> dict[str, int]:
    """Read every source from MySQL and refresh the MongoDB read model.

    Returns a mapping of collection name -> documents written. This is the
    only function that touches both databases, and it only READS MySQL.
    """
    fundamentals = _validate(
        build_stock_fundamentals(db.fetch_all(mysql_conn, Q_STOCKS)),
        ["_id", "ticker", "sector", "fundamentals"],
        "stock_fundamentals",
    )
    portfolios = _validate(
        build_portfolios(db.fetch_all(mysql_conn, Q_POSITIONS)),
        ["_id", "portfolio_name", "user"],
        "portfolios",
    )
    transactions = _validate(
        build_transactions(db.fetch_all(mysql_conn, Q_TRANSACTIONS)),
        ["_id", "portfolio_id", "transaction_type"],
        "transactions",
    )
    snapshots = _validate(
        build_snapshots(db.fetch_all(mysql_conn, Q_SNAPSHOTS)),
        ["_id", "portfolio_id", "snapshot_date"],
        "portfolio_snapshots",
    )

    ensure_indexes(mongo_database, verbose=verbose)

    written = {}
    for name, docs in (
        ("stock_fundamentals", fundamentals),
        ("portfolios", portfolios),
        ("transactions", transactions),
        ("portfolio_snapshots", snapshots),
    ):
        written[name] = sync_collection(mongo_database[name], docs)
        if verbose:
            print(f"  - {name}: {written[name]} document(s) synced")
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _connect_mysql(database: Optional[str]):
    try:
        return db.get_connection(database=database)
    except Exception as exc:  # driver missing, password missing, server down
        print(f"Could not connect to MySQL: {exc}")
        print("Hint: start MySQL, copy .env.example to .env, set "
              "FINWISE_DB_PASSWORD, then run python python/load_database.py.")
        return None


def _check_mongo(uri: Optional[str]) -> bool:
    if mongo_db.pymongo is None:
        print("pymongo is not installed. Run: pip install -r requirements.txt")
        return False
    if not mongo_db.server_available(uri):
        target = uri or mongo_db.DEFAULTS["FINWISE_MONGO_URI"]
        print(f"Could not reach MongoDB at {target}.")
        print("Hint: install MongoDB Community Server and start it, or point")
        print("FINWISE_MONGO_URI in .env at a MongoDB Atlas cluster "
              "(mongodb+srv://...). See docs/mongodb_module.md.")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database", default=None,
        help="MySQL source database (default: FINWISE_DB_NAME, or 'finwise')",
    )
    parser.add_argument(
        "--mongo-db", default=None,
        help="MongoDB target database (default: FINWISE_MONGO_DB, or 'finwise')",
    )
    parser.add_argument(
        "--uri", default=None,
        help="MongoDB connection string (default: FINWISE_MONGO_URI)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt",
    )
    args = parser.parse_args(argv)

    mysql_db = args.database or db.DEFAULTS["FINWISE_DB_NAME"]
    mongo_db_name = args.mongo_db or mongo_db.DEFAULTS["FINWISE_MONGO_DB"]

    print("=" * 70)
    print("FinWise MySQL -> MongoDB read-model loader")
    print("=" * 70)
    print(f"MySQL source    : {mysql_db}")
    print(f"MongoDB target  : {mongo_db_name}")
    print()
    print("!! MongoDB collections are REPLACED with the current MySQL read")
    print("!! model (MySQL itself is never modified).")
    print()

    if not args.yes:
        reply = input(f"Type the MongoDB database name '{mongo_db_name}' to "
                      "continue: ")
        if reply.strip() != mongo_db_name:
            print("Aborted - nothing was changed.")
            return 1

    if not _check_mongo(args.uri):
        return 1

    mysql_conn = _connect_mysql(args.database)
    if mysql_conn is None:
        return 1

    client = mongo_db.get_client(args.uri)
    try:
        print()
        print("Syncing collections (idempotent)...")
        written = sync_all(mysql_conn, client[mongo_db_name])
    except ETLValidationError as exc:
        print(f"\nLoad failed: {exc}")
        return 1
    finally:
        mysql_conn.close()
        client.close()

    print()
    print(f"Done. MongoDB database '{mongo_db_name}' now mirrors MySQL:")
    for name, n in written.items():
        print(f"  {name:<22} {n} documents")
    print()
    print("Next steps:")
    print("  python python/verify_mongo.py   # health check")
    print("  python python/mongo_demo.py     # CRUD + aggregation demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
