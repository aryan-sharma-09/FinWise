"""Small tests for the FinWise MongoDB collections.

If pymongo is not installed, or no MongoDB server is reachable, every test
SKIPS instead of failing - so a teammate who only has MySQL can still run
pytest and get a green result.

The tests work in a throwaway database whose name contains the word "test"
(finwise_test_mongo by default). It is dropped before and after each test,
so the real read-model database is never touched.

All data here is synthetic sample data - not real financial information.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("pymongo")

# conftest.py only adds the python/ folder to sys.path, so add mongodb/ here
# to be able to import mongo_db.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mongodb"))

import mongo_db  # noqa: E402  (imported after the pymongo skip check)

TEST_DB = os.environ.get("FINWISE_MONGO_TEST_DB",
                         mongo_db.DEFAULTS["FINWISE_MONGO_TEST_DB"])


@pytest.fixture()
def mongo_test_db():
    """A clean throwaway MongoDB database, dropped before and after."""
    if not mongo_db.server_available():
        pytest.skip("MongoDB is not reachable - start mongod "
                    "(see docs/mongodb_module.md)")
    mongo_db.require_test_db_name(TEST_DB)

    client = mongo_db.get_client()
    client.drop_database(TEST_DB)
    yield client[TEST_DB]
    client.drop_database(TEST_DB)
    client.close()


def test_insert_and_find(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    new_id = stocks.insert_one({"ticker": "TEST", "price": 10.0}).inserted_id

    document = stocks.find_one({"_id": new_id})
    assert document["ticker"] == "TEST"
    assert stocks.count_documents({}) == 1


def test_find_with_comparison_filter(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    stocks.insert_many([
        {"ticker": "CHEAP", "price": 10.0},
        {"ticker": "PRICEY", "price": 500.0},
    ])

    pricey = list(stocks.find({"price": {"$gt": 100}}))
    assert [document["ticker"] for document in pricey] == ["PRICEY"]


def test_update_and_delete(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    stocks.insert_one({"ticker": "UPD", "price": 10.0})

    stocks.update_one({"ticker": "UPD"}, {"$set": {"price": 25.0}})
    assert stocks.find_one({"ticker": "UPD"})["price"] == 25.0

    stocks.delete_one({"ticker": "UPD"})
    assert stocks.count_documents({}) == 0


def test_group_aggregation(mongo_test_db):
    transactions = mongo_test_db["transactions"]
    transactions.insert_many([
        {"portfolio_id": 1, "quantity": 10, "price_per_unit": 100.0},  # 1000
        {"portfolio_id": 1, "quantity": 5, "price_per_unit": 60.0},    # 300
        {"portfolio_id": 2, "quantity": 2, "price_per_unit": 100.0},   # 200
    ])

    pipeline = [
        {"$group": {"_id": "$portfolio_id",
                    "total": {"$sum": {"$multiply":
                                       ["$quantity", "$price_per_unit"]}}}},
        {"$sort": {"_id": 1}},
    ]
    totals = {}
    for row in transactions.aggregate(pipeline):
        totals[row["_id"]] = row["total"]

    assert totals[1] == 1300.0
    assert totals[2] == 200.0


def test_require_test_db_name_rejects_unsafe_names():
    assert mongo_db.require_test_db_name(TEST_DB) == TEST_DB
    with pytest.raises(ValueError):
        mongo_db.require_test_db_name("finwise_mongo")
