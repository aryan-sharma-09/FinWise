#!/usr/bin/env python3
"""A short, read-only tour of the FinWise MongoDB collections.

Load the data first, then run this:

    python etl/load_mongo.py
    python mongodb/mongo_demo.py

It shows a few simple find() queries, one small aggregation, and finally an
insert / read / update / delete demo on a scratch collection that is removed
again afterwards. Nothing here writes to the four real collections.

All figures come from synthetic sample data - not real financial information.

Contents
  print_documents                   - print selected fields of each document
  show_collection_counts            - how many documents each collection has
  show_technology_stocks            - find() with an equality filter
  show_expensive_stocks             - find() with a comparison operator
  show_trades_in_portfolio          - find() filtered by one field
  show_total_invested_per_portfolio - one aggregation ($group + $sum + $sort)
  demo_crud                         - insert / read / update / delete
  main                              - runs all of the above
"""

import sys
from pathlib import Path

# Let this script import mongo_db.py from the same folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mongo_db


def print_documents(title, documents, fields):
    """Print one line per document, showing only the chosen fields."""
    print()
    print(title)
    print("-" * len(title))
    if not documents:
        print("  (no documents)")
        return
    for document in documents:
        parts = []
        for field in fields:
            parts.append(field + "=" + str(document.get(field)))
        print("  " + ", ".join(parts))


def show_collection_counts(database):
    """How many documents each of the four collections holds."""
    print()
    print("Documents per collection")
    print("-" * 23)
    for name in mongo_db.COLLECTIONS:
        print("  " + name + ": " + str(database[name].count_documents({})))


def show_technology_stocks(database):
    """find() with a simple equality filter, limited to five documents."""
    query = {"sector": "Technology"}
    documents = list(database["stock_fundamentals"].find(query).limit(5))
    print_documents("Five Technology stocks (filter: sector = 'Technology')",
                    documents, ["ticker", "company_name", "price"])


def show_expensive_stocks(database):
    """find() with a comparison operator: price greater than 400."""
    query = {"price": {"$gt": 400}}
    documents = list(database["stock_fundamentals"].find(query))
    print_documents("Stocks priced above 400 (filter: price > 400)",
                    documents, ["ticker", "company_name", "price"])


def show_trades_in_portfolio(database, portfolio_id):
    """find() filtered by one field - the trades of a single portfolio."""
    query = {"portfolio_id": portfolio_id}
    documents = list(database["transactions"].find(query).limit(5))
    print_documents("First five trades in portfolio " + str(portfolio_id),
                    documents,
                    ["ticker", "transaction_type", "quantity",
                     "price_per_unit"])


def show_total_invested_per_portfolio(database):
    """One aggregation: the total money traded per portfolio.

    The pipeline has two stages:
      * $group - makes one output row per portfolio_id. Inside it, $sum adds
                 up quantity * price_per_unit for every trade, and $multiply
                 does the multiplication.
      * $sort  - orders the result by portfolio, so the output is stable.
    """
    pipeline = [
        {
            "$group": {
                "_id": "$portfolio_id",
                "total_invested": {
                    "$sum": {"$multiply": ["$quantity", "$price_per_unit"]},
                },
            },
        },
        {"$sort": {"_id": 1}},
    ]
    results = database["transactions"].aggregate(pipeline)

    print()
    print("Total invested per portfolio ($group)")
    print("-" * 35)
    for row in results:
        print("  portfolio " + str(row["_id"]) + ": "
              + format(row["total_invested"], ".2f"))


def demo_crud(database):
    """Insert, read, update and delete one document in a scratch collection.

    A separate 'demo_scratch' collection is used, and it is dropped again at
    the end (even if something goes wrong), so the four real collections are
    never touched and nothing is left behind.
    """
    print()
    print("CRUD demo (scratch collection 'demo_scratch')")
    print("-" * 44)
    scratch = database["demo_scratch"]
    try:
        new_id = scratch.insert_one({"name": "demo", "value": 10}).inserted_id
        print("  insert -> new _id = " + str(new_id))

        document = scratch.find_one({"_id": new_id})
        print("  read   -> " + str(document))

        scratch.update_one({"_id": new_id}, {"$set": {"value": 20}})
        document = scratch.find_one({"_id": new_id})
        print("  update -> value = " + str(document["value"]))

        scratch.delete_one({"_id": new_id})
        print("  delete -> documents left = "
              + str(scratch.count_documents({})))
    finally:
        # drop_collection removes the collection itself, not just its
        # documents, so no empty 'demo_scratch' is left in the database.
        database.drop_collection("demo_scratch")


def main():
    if not mongo_db.server_available():
        print("Cannot reach MongoDB. Is mongod running?")
        print("See docs/mongodb_module.md for setup steps.")
        return 1

    database = mongo_db.get_database()
    print("FinWise MongoDB demo - database '" + database.name + "'")

    if database["stock_fundamentals"].count_documents({}) == 0:
        print("The collections are empty. Load them from MySQL first:")
        print("  python etl/load_mongo.py")
        return 1

    show_collection_counts(database)
    show_technology_stocks(database)
    show_expensive_stocks(database)
    show_trades_in_portfolio(database, 1)
    show_total_invested_per_portfolio(database)
    demo_crud(database)

    print()
    print("Sample data only - not real financial information.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
