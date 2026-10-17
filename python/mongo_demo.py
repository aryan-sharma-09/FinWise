#!/usr/bin/env python3
"""Interactive MongoDB demo for FinWise - CRUD plus aggregation pipelines.

This is the MongoDB counterpart of python/crud_examples.py. It demonstrates
the full NoSQL toolkit against the read model built by python/load_mongo.py:

  * CREATE  - insert a stock document, add a holding to a portfolio.
  * READ    - list documents, filter by an embedded field, projection.
  * UPDATE  - $set fundamentals, $addToSet / $pull tags, $push / $pull
              array elements.
  * DELETE  - remove a document / array element.
  * UPSERT  - idempotent snapshot write (mirrors sp_create_snapshot).
  * AGGREGATE - five advanced pipelines (pipeline_* functions below):
                1. sector allocation          ($unwind + $lookup + $group)
                2. top-N positions            ($setWindowFields $rank)
                3. period-over-period returns ($setWindowFields $shift)
                4. running invested capital   ($setWindowFields running sum)
                5. portfolio dashboard        ($facet + $bucket)

SAFETY: this demo writes ONLY to MongoDB. It never touches MySQL, which
stays the single source of truth. Any local changes can be reset by
re-running:  python python/load_mongo.py --yes

Run with:  python python/mongo_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mongo_db  # noqa: E402


# ---------------------------------------------------------------------------
# Aggregation pipelines (pure functions over a MongoDB database handle).
# These are imported by verify_mongo.py and by the test suite, so they are
# the single source of truth for the "advanced aggregation" deliverable.
# ---------------------------------------------------------------------------
def pipeline_sector_allocation(database) -> list[dict]:
    """1. Sector money and weight per portfolio.

    Mirrors MySQL's v_sector_allocation: $unwind the embedded holdings
    array, $lookup each holding's stock to fetch its sector, aggregate the
    sector value, then compute the weight inside the portfolio.
    """
    pipeline = [
        {"$unwind": "$holdings"},
        {"$lookup": {
            "from": "stock_fundamentals",
            "localField": "holdings.stock_id",
            "foreignField": "_id",
            "as": "stock",
        }},
        {"$unwind": "$stock"},
        {"$group": {
            "_id": {"portfolio_id": "$_id", "sector": "$stock.sector.name"},
            "portfolio_name": {"$first": "$portfolio_name"},
            "sector_value": {"$sum": "$holdings.market_value"},
        }},
        {"$group": {
            "_id": "$_id.portfolio_id",
            "portfolio_name": {"$first": "$portfolio_name"},
            "portfolio_total_value": {"$sum": "$sector_value"},
            "sectors": {"$push": {
                "sector_name": "$_id.sector",
                "sector_value": "$sector_value",
            }},
        }},
        {"$unwind": "$sectors"},
        {"$addFields": {
            "sector_weight_percent": {"$round": [{"$multiply": [
                {"$divide": ["$sectors.sector_value",
                             "$portfolio_total_value"]}, 100]}, 2]},
        }},
        {"$project": {
            "_id": 0,
            "portfolio_id": "$_id",
            "portfolio_name": 1,
            "sector_name": "$sectors.sector_name",
            "sector_value": "$sectors.sector_value",
            "portfolio_total_value": 1,
            "sector_weight_percent": 1,
        }},
        {"$sort": {"portfolio_id": 1, "sector_weight_percent": -1}},
    ]
    return list(database["portfolios"].aggregate(pipeline))


def pipeline_top_positions(database, n: int = 3) -> list[dict]:
    """2. Top-N positions by weight within each portfolio.

    Mirrors analytics query 12: $unwind then rank with $setWindowFields.
    """
    pipeline = [
        {"$unwind": "$holdings"},
        {"$setWindowFields": {
            "partitionBy": "$_id",
            "sortBy": {"holdings.market_value": -1},
            "output": {"weight_rank": {"$rank": {}}},
        }},
        {"$match": {"weight_rank": {"$lte": n}}},
        {"$project": {
            "_id": 0,
            "portfolio_id": "$_id",
            "portfolio_name": 1,
            "ticker": "$holdings.ticker",
            "market_value": "$holdings.market_value",
            "weight_percent": "$holdings.weight_percent",
            "weight_rank": 1,
        }},
        {"$sort": {"portfolio_id": 1, "weight_rank": 1}},
    ]
    return list(database["portfolios"].aggregate(pipeline))


def pipeline_period_returns(database, portfolio_id: int | None = None) -> list[dict]:
    """3. Period-over-period snapshot returns.

    Mirrors v_portfolio_performance: $setWindowFields $shift is the NoSQL
    equivalent of SQL LAG(). change_value/change_percent are null for a
    portfolio's first snapshot.
    """
    match = {} if portfolio_id is None else {"portfolio_id": portfolio_id}
    pipeline = [
        {"$match": match},
        {"$setWindowFields": {
            "partitionBy": "$portfolio_id",
            "sortBy": {"snapshot_date": 1},
            "output": {"previous_market_value": {
                "$shift": {"output": "$total_market_value", "by": -1}}},
        }},
        {"$addFields": {
            "change_value": {"$round": [{"$subtract": [
                "$total_market_value", "$previous_market_value"]}, 2]},
            "change_percent": {"$cond": [
                {"$or": [
                    {"$eq": ["$previous_market_value", None]},
                    {"$eq": ["$previous_market_value", 0]},
                ]},
                None,
                {"$round": [{"$multiply": [{"$divide": [
                    {"$subtract": ["$total_market_value",
                                   "$previous_market_value"]},
                    "$previous_market_value"]}, 100]}, 2]},
            ]},
        }},
        {"$project": {
            "_id": 0,
            "portfolio_id": 1,
            "snapshot_date": 1,
            "total_market_value": 1,
            "previous_market_value": 1,
            "change_value": 1,
            "change_percent": 1,
        }},
        {"$sort": {"portfolio_id": 1, "snapshot_date": 1}},
    ]
    return list(database["portfolio_snapshots"].aggregate(pipeline))


def pipeline_running_invested_capital(database,
                                      portfolio_id: int | None = None) -> list[dict]:
    """4. Running invested capital per portfolio.

    Mirrors analytics query 13: a cumulative sum window over BUY trades.
    """
    match: dict = {"transaction_type": "BUY"}
    if portfolio_id is not None:
        match["portfolio_id"] = portfolio_id
    pipeline = [
        {"$match": match},
        {"$setWindowFields": {
            "partitionBy": "$portfolio_id",
            "sortBy": {"transaction_date": 1, "_id": 1},
            "output": {"running_invested_capital": {
                "$sum": {"$multiply": ["$quantity", "$price_per_unit"]},
                "window": {"documents": ["unbounded", "current"]}}},
        }},
        {"$addFields": {"running_invested_capital": {
            "$round": ["$running_invested_capital", 2]}}},
        {"$project": {
            "_id": 0,
            "portfolio_id": 1,
            "ticker": 1,
            "quantity": 1,
            "price_per_unit": 1,
            "transaction_date": 1,
            "running_invested_capital": 1,
        }},
        {"$sort": {"portfolio_id": 1, "transaction_date": 1}},
    ]
    return list(database["transactions"].aggregate(pipeline))


def pipeline_portfolio_dashboard(database) -> dict:
    """5. One-pass portfolio dashboard.

    Mirrors the CASE/CTE report (query 14) with $facet: platform totals,
    $bucket concentration bands, and the largest portfolios all computed in
    a single pass over the data.
    """
    pipeline = [
        {"$unwind": "$holdings"},
        {"$group": {
            "_id": "$_id",
            "portfolio_name": {"$first": "$portfolio_name"},
            "total_value": {"$sum": "$holdings.market_value"},
            "positions": {"$sum": 1},
            "largest_position": {"$max": "$holdings.market_value"},
        }},
        {"$facet": {
            "totals": [
                {"$group": {
                    "_id": None,
                    "portfolios": {"$sum": 1},
                    "grand_total_value": {"$sum": "$total_value"},
                    "average_portfolio_value": {"$avg": "$total_value"},
                }},
                {"$project": {"_id": 0}},
            ],
            "concentration_buckets": [
                {"$bucket": {
                    "groupBy": "$total_value",
                    "boundaries": [0, 10000, 25000, 50000, 100000],
                    "default": "100000+",
                    "output": {"portfolio_count": {"$sum": 1}},
                }},
            ],
            "largest_portfolios": [
                {"$sort": {"total_value": -1}},
                {"$limit": 3},
                {"$project": {
                    "_id": 0,
                    "portfolio_id": "$_id",
                    "portfolio_name": 1,
                    "total_value": 1,
                }},
            ],
        }},
    ]
    result = list(database["portfolios"].aggregate(pipeline))
    return result[0] if result else {}


# ---------------------------------------------------------------------------
# Small input / output helpers (mirrors python/crud_examples.py)
# ---------------------------------------------------------------------------
def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def ask_int(prompt: str) -> int:
    while True:
        try:
            return int(ask(prompt))
        except ValueError:
            print("  Please enter a whole number.")


def ask_float(prompt: str, default: float | None = None) -> float | None:
    default_str = "" if default is None else str(default)
    while True:
        raw = ask(prompt, default_str or None)
        if raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number (or leave blank for none).")


def print_table(rows: list[dict], columns: list[str]) -> None:
    """Tiny row printer - enough for a demo, no external dependencies."""
    if not rows:
        print("  (no rows)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  " + " | ".join(c.ljust(widths[c]) for c in columns))
    print("  " + "-+-".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  " + " | ".join(str(row.get(c, "")).ljust(widths[c])
                                 for c in columns))


def show_error(exc: Exception) -> None:
    print(f"  MongoDB operation failed: {exc}")


def _require_data(database) -> bool:
    """Return False (with a hint) when the read model has not been loaded."""
    if mongo_db.count(database["stock_fundamentals"]) == 0:
        print("  The MongoDB read model is empty. Load it first with:")
        print("    python python/load_mongo.py --yes")
        return False
    return True


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------
def list_fundamentals(database) -> None:
    if not _require_data(database):
        return
    rows = mongo_db.find_all(
        database["stock_fundamentals"],
        projection={"_id": 0, "ticker": 1, "company_name": 1,
                    "sector.name": 1, "fundamentals.price": 1,
                    "fundamentals.pe_ratio": 1, "fundamentals.dividend_yield": 1},
        sort=[("ticker", 1)],
    )
    flat = [{
        "ticker": r["ticker"],
        "company_name": r["company_name"],
        "sector": r["sector"]["name"],
        "price": r["fundamentals"]["price"],
        "pe_ratio": r["fundamentals"]["pe_ratio"],
        "dividend_yield": r["fundamentals"]["dividend_yield"],
    } for r in rows]
    print_table(flat, ["ticker", "company_name", "sector", "price",
                       "pe_ratio", "dividend_yield"])


def find_by_sector(database) -> None:
    if not _require_data(database):
        return
    sector = ask("Sector name (e.g. Technology)")
    rows = mongo_db.find_all(
        database["stock_fundamentals"],
        query={"sector.name": sector},
        projection={"_id": 0, "ticker": 1, "company_name": 1,
                    "fundamentals.price": 1},
        sort=[("ticker", 1)],
    )
    flat = [{"ticker": r["ticker"], "company_name": r["company_name"],
             "price": r["fundamentals"]["price"]} for r in rows]
    print_table(flat, ["ticker", "company_name", "price"])


def add_stock(database) -> None:
    if not _require_data(database):
        return
    last = mongo_db.find_all(database["stock_fundamentals"],
                             sort=[("_id", -1)], limit=1)
    next_id = int(last[0]["_id"]) + 1 if last else 1
    doc = {
        "_id": next_id,
        "ticker": ask("Ticker (e.g. TEST)").upper(),
        "company_name": ask("Company name"),
        "sector": {"name": ask("Sector name", "Technology"),
                   "description": ask("Sector description", "")},
        "fundamentals": {
            "price": ask_float("Price"),
            "market_cap_millions": ask_float("Market cap (millions)"),
            "pe_ratio": ask_float("P/E ratio (blank = none)"),
            "dividend_yield": ask_float("Dividend yield % (blank = none)"),
            "price_as_of": None,
        },
        "tags": [],
    }
    try:
        mongo_db.insert_one(database["stock_fundamentals"], doc)
        print(f"  Inserted document _id={next_id}.")
    except Exception as exc:
        show_error(exc)


def update_fundamentals(database) -> None:
    if not _require_data(database):
        return
    ticker = ask("Ticker to update").upper()
    update = {"$set": {
        "fundamentals.price": ask_float("New price"),
        "fundamentals.pe_ratio": ask_float("New P/E (blank = none)"),
    }}
    result = mongo_db.update_one(database["stock_fundamentals"],
                                 {"ticker": ticker}, update)
    print(f"  Modified {result.modified_count} document(s).")


def manage_tags(database) -> None:
    if not _require_data(database):
        return
    ticker = ask("Ticker").upper()
    if ask("Add or remove? (add/remove)", "add").lower().startswith("r"):
        tag = ask("Tag to remove")
        result = mongo_db.update_one(database["stock_fundamentals"],
                                     {"ticker": ticker}, {"$pull": {"tags": tag}})
    else:
        tag = ask("Tag to add")
        result = mongo_db.update_one(database["stock_fundamentals"],
                                     {"ticker": ticker},
                                     {"$addToSet": {"tags": tag}})
    print(f"  Modified {result.modified_count} document(s).")


def add_holding(database) -> None:
    if not _require_data(database):
        return
    pid = ask_int("Portfolio id")
    ticker = ask("Stock ticker to add").upper()
    qty = ask_float("Quantity", 1.0)
    stock = mongo_db.find_one(database["stock_fundamentals"], {"ticker": ticker})
    if stock is None:
        print(f"  No stock with ticker {ticker}.")
        return
    holding = {
        "stock_id": stock["_id"],
        "ticker": stock["ticker"],
        "company_name": stock["company_name"],
        "sector": stock["sector"]["name"],
        "quantity": qty,
        "avg_cost": stock["fundamentals"]["price"],
        "current_price": stock["fundamentals"]["price"],
        "market_value": (qty or 0) * stock["fundamentals"]["price"],
        "unrealized_pl": 0.0,
        "weight_percent": None,
    }
    result = mongo_db.update_one(database["portfolios"], {"_id": pid},
                                 {"$push": {"holdings": holding}})
    print(f"  Modified {result.modified_count} document(s).")


def remove_holding(database) -> None:
    if not _require_data(database):
        return
    pid = ask_int("Portfolio id")
    ticker = ask("Stock ticker to remove").upper()
    result = mongo_db.update_one(database["portfolios"], {"_id": pid},
                                 {"$pull": {"holdings": {"ticker": ticker}}})
    print(f"  Modified {result.modified_count} document(s).")


def delete_stock(database) -> None:
    if not _require_data(database):
        return
    ticker = ask("Ticker to delete").upper()
    confirm = ask(f"Type YES to delete the {ticker} document from MongoDB")
    if confirm != "YES":
        print("  Cancelled.")
        return
    result = mongo_db.delete_one(database["stock_fundamentals"],
                                 {"ticker": ticker})
    print(f"  Deleted {result.deleted_count} document(s).")


def upsert_snapshot(database) -> None:
    if not _require_data(database):
        return
    pid = ask_int("Portfolio id")
    when = ask("Snapshot date (YYYY-MM-DD)")
    from datetime import datetime
    try:
        snap_date = datetime.strptime(when, "%Y-%m-%d")
    except ValueError:
        print("  Please use YYYY-MM-DD.")
        return
    # Recompute the portfolio's market value from its embedded holdings,
    # then UPSERT a snapshot keyed by (portfolio_id, snapshot_date).
    portfolio = mongo_db.find_one(database["portfolios"], {"_id": pid})
    if portfolio is None:
        print(f"  No portfolio with id {pid}.")
        return
    total = sum((h.get("market_value") or 0) for h in portfolio.get("holdings", []))
    key = f"{pid}:{snap_date.date().isoformat()}"
    doc = {
        "_id": key,
        "portfolio_id": pid,
        "snapshot_date": snap_date,
        "total_market_value": round(total, 2),
        "total_cost_basis": None,
        "holdings_count": len(portfolio.get("holdings", [])),
    }
    mongo_db.upsert(database["portfolio_snapshots"],
                    {"_id": key}, doc)
    print(f"  Upserted snapshot {key} (idempotent - re-running updates it).")


# ---------------------------------------------------------------------------
# Aggregation operations
# ---------------------------------------------------------------------------
def show_sector_allocation(database) -> None:
    if not _require_data(database):
        return
    rows = pipeline_sector_allocation(database)
    print_table(rows, ["portfolio_id", "portfolio_name", "sector_name",
                       "sector_value", "sector_weight_percent"])


def show_top_positions(database) -> None:
    if not _require_data(database):
        return
    n = ask_int("How many top positions per portfolio? (e.g. 3)")
    rows = pipeline_top_positions(database, n)
    print_table(rows, ["portfolio_id", "portfolio_name", "weight_rank",
                       "ticker", "market_value", "weight_percent"])


def show_period_returns(database) -> None:
    if not _require_data(database):
        return
    pid = ask_int("Portfolio id (0 = all)")
    rows = pipeline_period_returns(database, None if pid == 0 else pid)
    print_table(rows, ["portfolio_id", "snapshot_date", "total_market_value",
                       "previous_market_value", "change_value", "change_percent"])


def show_running_capital(database) -> None:
    if not _require_data(database):
        return
    pid = ask_int("Portfolio id (0 = all)")
    rows = pipeline_running_invested_capital(database, None if pid == 0 else pid)
    print_table(rows, ["portfolio_id", "transaction_date", "ticker",
                       "quantity", "price_per_unit", "running_invested_capital"])


def show_dashboard(database) -> None:
    if not _require_data(database):
        return
    result = pipeline_portfolio_dashboard(database)
    totals = (result.get("totals") or [{}])[0]
    print("\n  Platform totals:")
    for k, v in totals.items():
        print(f"    {k}: {v}")
    print("\n  Concentration buckets:")
    print_table(result.get("concentration_buckets", []),
                ["_id", "portfolio_count"])
    print("\n  Largest portfolios:")
    print_table(result.get("largest_portfolios", []),
                ["portfolio_id", "portfolio_name", "total_value"])


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
MENU = """
============ FinWise MongoDB demo (read model) ============
  1) List stock fundamentals                     [READ]
  2) Find stocks by sector                       [READ]
  3) Add a stock document                        [CREATE]
  4) Update a stock's price / P/E                [UPDATE $set]
  5) Add / remove a tag                          [UPDATE $addToSet/$pull]
  6) Add a holding to a portfolio                [UPDATE $push]
  7) Remove a holding from a portfolio           [UPDATE $pull]
  8) Delete a stock document                     [DELETE]
  9) Upsert a portfolio snapshot                 [UPSERT]
 10) Sector allocation            [$unwind+$lookup+$group]
 11) Top-N positions              [$setWindowFields $rank]
 12) Period-over-period returns   [$setWindowFields $shift]
 13) Running invested capital     [$setWindowFields running sum]
 14) Portfolio dashboard          [$facet + $bucket]
  0) Exit
==========================================================
"""

ACTIONS = {
    "1": list_fundamentals,
    "2": find_by_sector,
    "3": add_stock,
    "4": update_fundamentals,
    "5": manage_tags,
    "6": add_holding,
    "7": remove_holding,
    "8": delete_stock,
    "9": upsert_snapshot,
    "10": show_sector_allocation,
    "11": show_top_positions,
    "12": show_period_returns,
    "13": show_running_capital,
    "14": show_dashboard,
}


def main() -> int:
    if mongo_db.pymongo is None:
        print("pymongo is not installed. Run: pip install -r requirements.txt")
        return 1
    if not mongo_db.server_available():
        print(f"Could not reach MongoDB at "
              f"{mongo_db.DEFAULTS['FINWISE_MONGO_URI']}.")
        print("Hint: start MongoDB or set FINWISE_MONGO_URI in .env, then run")
        print("python python/load_mongo.py --yes. See docs/mongodb_module.md.")
        return 1

    client = mongo_db.get_client()
    database = client[mongo_db.DEFAULTS["FINWISE_MONGO_DB"]]
    try:
        while True:
            print(MENU)
            choice = input("Choose an option: ").strip()
            if choice == "0":
                print("Bye.")
                return 0
            action = ACTIONS.get(choice)
            if action is None:
                print("  Unknown option.")
                continue
            try:
                action(database)
            except KeyboardInterrupt:
                print("\n  (cancelled)")
            except Exception as exc:
                show_error(exc)
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
