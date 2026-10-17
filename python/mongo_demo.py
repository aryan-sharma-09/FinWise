#!/usr/bin/env python3
"""A short, read-only tour of the FinWise MongoDB read model.

Run it after loading the data:

    python python/mongo_demo.py

The queries are deliberately simple: plain filters, one comparison operator,
and two small aggregation pipelines. The final section shows insert / read /
update / delete on a scratch collection that is cleaned up afterwards, so the
read model is never left in a strange state.

All figures come from synthetic sample data - not real financial information.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mongo_db  # noqa: E402


def print_documents(title: str, documents: list[dict], fields: list[str]) -> None:
    """Print one line per document, showing only the chosen fields."""
    print()
    print(title)
    print("-" * len(title))
    if not documents:
        print("  (no documents)")
        return
    for document in documents:
        parts = [f"{field}={document.get(field)}" for field in fields]
        print("  " + ", ".join(parts))


def show_collection_counts(database) -> None:
    print()
    print("Documents per collection")
    print("-" * 23)
    for name in mongo_db.COLLECTIONS:
        print(f"  {name}: {mongo_db.count(database[name])}")


def show_technology_stocks(database) -> None:
    """find() with a simple equality filter, limited to 5 documents."""
    query = {"sector": "Technology"}
    documents = mongo_db.find_all(database["stock_fundamentals"], query, limit=5)
    print_documents("Five Technology stocks (filter: sector = 'Technology')",
                    documents, ["ticker", "company_name", "price"])


def show_expensive_stocks(database) -> None:
    """find() with a comparison operator: price greater than 400."""
    query = {"price": {"$gt": 400}}
    documents = mongo_db.find_all(database["stock_fundamentals"], query)
    print_documents("Stocks priced above 400 (filter: price > 400)",
                    documents, ["ticker", "company_name", "price"])


def show_portfolio_trades(database, portfolio_id: int) -> None:
    """find() filtered by one field - the trades of a single portfolio."""
    query = {"portfolio_id": portfolio_id}
    documents = mongo_db.find_all(database["transactions"], query, limit=5)
    print_documents(f"First five trades in portfolio {portfolio_id}",
                    documents,
                    ["ticker", "transaction_type", "quantity", "price_per_unit"])


def show_total_invested_per_portfolio(database) -> None:
    """Aggregation: total money traded per portfolio.

    The pipeline has three stages:
      * $group    - one output row per portfolio_id, adding up the values
      * $multiply - quantity * price_per_unit, the arithmetic inside $sum
      * $sort     - order the result so the output is stable
    """
    pipeline = [
        {
            "$group": {
                "_id": "$portfolio_id",
                "total_invested": {
                    "$sum": {"$multiply": ["$quantity", "$price_per_unit"]},
                },
                "trades": {"$sum": 1},
            },
        },
        {"$sort": {"_id": 1}},
    ]
    results = mongo_db.aggregate(database["transactions"], pipeline)

    print()
    print("Total invested per portfolio ($group)")
    print("-" * 35)
    for row in results:
        print(f"  portfolio {row['_id']}: {row['total_invested']:.2f} "
              f"across {row['trades']} trade(s)")


def show_trades_per_ticker(database) -> None:
    """Aggregation: how many trades touched each ticker, busiest first."""
    pipeline = [
        {"$group": {"_id": "$ticker", "trades": {"$sum": 1}}},
        {"$sort": {"trades": -1, "_id": 1}},
    ]
    results = mongo_db.aggregate(database["transactions"], pipeline)

    print()
    print("Trades per ticker ($group + $sort)")
    print("-" * 34)
    for row in results:
        print(f"  {row['_id']}: {row['trades']}")


def demo_crud(database) -> None:
    """Insert, read, update and delete one document in a scratch collection.

    We use a separate 'demo_scratch' collection and drop it again at the end
    with a try/finally, so it is removed even if the demo hits an error. The
    four real read-model collections are never touched and nothing is left
    behind.
    """
    print()
    print("CRUD demo (scratch collection 'demo_scratch')")
    print("-" * 44)
    scratch = database["demo_scratch"]
    try:
        new_id = mongo_db.insert_one(scratch, {"name": "demo", "value": 10})
        print(f"  insert -> new _id = {new_id}")

        document = mongo_db.find_one(scratch, {"_id": new_id})
        print(f"  read   -> {document}")

        mongo_db.update_one(scratch, {"_id": new_id}, {"value": 20})
        document = mongo_db.find_one(scratch, {"_id": new_id})
        print(f"  update -> value = {document['value']}")

        mongo_db.delete_one(scratch, {"_id": new_id})
        print(f"  delete -> documents left = {mongo_db.count(scratch)}")
    finally:
        # drop_collection removes the collection itself, not just its
        # documents, so no empty 'demo_scratch' is left in the database.
        database.drop_collection("demo_scratch")


def main() -> int:
    if not mongo_db.server_available():
        print("Cannot reach MongoDB. Is mongod running? "
              "See docs/mongodb_module.md for setup steps.")
        return 1

    database = mongo_db.get_database()
    print(f"FinWise MongoDB demo - database {database.name!r}")

    if mongo_db.count(database["stock_fundamentals"]) == 0:
        print("The read model looks empty. Load it first:")
        print("  python python/load_mongo.py --yes")
        return 1

    show_collection_counts(database)
    show_technology_stocks(database)
    show_expensive_stocks(database)
    show_portfolio_trades(database, 1)
    show_total_invested_per_portfolio(database)
    show_trades_per_ticker(database)
    demo_crud(database)

    print()
    print("Sample data only - not real financial information.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
