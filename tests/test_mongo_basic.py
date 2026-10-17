"""Basic tests for the FinWise MongoDB read model.

Following the rest of the suite, these tests SKIP (never fail) when pymongo
is not installed or no MongoDB server is reachable, so a teammate with only
MySQL can still run `pytest`.

They always work in a throwaway database whose name contains "test"
(finwise_test_mongo by default) and drop it before and after each test, so
the real read-model database is never touched.
"""

from __future__ import annotations

import os

import pytest

import mongo_db

TEST_DB = os.environ.get(
    "FINWISE_MONGO_TEST_DB", mongo_db.DEFAULTS["FINWISE_MONGO_TEST_DB"]
)


@pytest.fixture()
def mongo_test_db():
    """A clean throwaway MongoDB database, dropped before and after."""
    if mongo_db.MongoClient is None:
        pytest.skip("pymongo is not installed "
                    "(run: pip install -r requirements.txt)")
    if not mongo_db.server_available():
        pytest.skip("MongoDB is not reachable - start mongod "
                    "(see docs/mongodb_module.md)")

    mongo_db.require_test_db_name(TEST_DB)
    client = mongo_db.get_client()
    client.drop_database(TEST_DB)
    try:
        yield mongo_db.get_database(TEST_DB, client=client)
    finally:
        client.drop_database(TEST_DB)
        client.close()


def test_insert_one_and_find_one(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    new_id = mongo_db.insert_one(stocks, {"ticker": "TEST", "price": 10.0})

    document = mongo_db.find_one(stocks, {"_id": new_id})
    assert document is not None
    assert document["ticker"] == "TEST"
    assert mongo_db.count(stocks) == 1


def test_find_with_comparison_filter(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    mongo_db.insert_many(stocks, [
        {"ticker": "CHEAP", "price": 10.0},
        {"ticker": "PRICEY", "price": 500.0},
    ])

    pricey = mongo_db.find_all(stocks, {"price": {"$gt": 100}})
    assert [d["ticker"] for d in pricey] == ["PRICEY"]


def test_update_one(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    mongo_db.insert_one(stocks, {"ticker": "UPD", "price": 10.0})

    result = mongo_db.update_one(stocks, {"ticker": "UPD"}, {"price": 25.0})

    assert result.modified_count == 1
    assert mongo_db.find_one(stocks, {"ticker": "UPD"})["price"] == \
        pytest.approx(25.0)


def test_delete_one(mongo_test_db):
    stocks = mongo_test_db["stock_fundamentals"]
    mongo_db.insert_many(stocks, [
        {"ticker": "KEEP"},
        {"ticker": "DROP"},
    ])

    mongo_db.delete_one(stocks, {"ticker": "DROP"})

    assert mongo_db.count(stocks) == 1
    assert mongo_db.find_one(stocks, {"ticker": "DROP"}) is None


def test_group_aggregation(mongo_test_db):
    transactions = mongo_test_db["transactions"]
    mongo_db.insert_many(transactions, [
        {"portfolio_id": 1, "quantity": 10, "price_per_unit": 100.0},  # 1000
        {"portfolio_id": 1, "quantity": 5, "price_per_unit": 60.0},   # 300
        {"portfolio_id": 2, "quantity": 2, "price_per_unit": 100.0},  # 200
    ])

    pipeline = [
        {"$group": {"_id": "$portfolio_id",
                    "total": {"$sum": {"$multiply":
                                       ["$quantity", "$price_per_unit"]}}}},
        {"$sort": {"_id": 1}},
    ]
    totals = {row["_id"]: row["total"]
              for row in mongo_db.aggregate(transactions, pipeline)}

    assert totals[1] == pytest.approx(1300.0)
    assert totals[2] == pytest.approx(200.0)


def test_require_test_db_name_rejects_unsafe_names():
    assert mongo_db.require_test_db_name("finwise_test_mongo") == \
        "finwise_test_mongo"
    with pytest.raises(ValueError):
        mongo_db.require_test_db_name("finwise_mongo")
