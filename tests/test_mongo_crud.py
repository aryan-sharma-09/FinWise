"""CRUD tests for the FinWise MongoDB read model.

These exercise the helpers in python/mongo_db.py against a DISPOSABLE MongoDB
database whose name contains "test" (see the mongo_db_conn fixture). They
need no MySQL, and they SKIP cleanly when pymongo or the server is missing -
exactly like the MySQL tests skip when MySQL is unavailable.
"""

from __future__ import annotations

import pytest

import mongo_db


def test_insert_one_and_find_one(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    inserted = mongo_db.insert_one(coll, {"_id": 1, "ticker": "TEST", "tags": []})
    assert inserted == 1

    doc = mongo_db.find_one(coll, {"ticker": "TEST"})
    assert doc is not None
    assert doc["_id"] == 1
    assert doc["tags"] == []


def test_insert_many_and_count(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    ids = mongo_db.insert_many(coll, [
        {"_id": 1, "ticker": "AAA", "tags": []},
        {"_id": 2, "ticker": "BBB", "tags": []},
        {"_id": 3, "ticker": "CCC", "tags": []},
    ])
    assert ids == [1, 2, 3]
    assert mongo_db.count(coll) == 3
    assert mongo_db.count(coll, {"ticker": {"$in": ["AAA", "BBB"]}}) == 2


def test_find_all_projection_and_sort(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    mongo_db.insert_many(coll, [
        {"_id": 1, "ticker": "ZZZ", "sector": {"name": "Tech"}, "extra": "x"},
        {"_id": 2, "ticker": "AAA", "sector": {"name": "Tech"}, "extra": "y"},
    ])
    rows = mongo_db.find_all(coll, projection={"_id": 0, "ticker": 1},
                             sort=[("ticker", 1)])
    assert rows == [{"ticker": "AAA"}, {"ticker": "ZZZ"}]
    # Nested-field filter
    assert len(mongo_db.find_all(coll, {"sector.name": "Tech"})) == 2


def test_update_set_and_inc(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    mongo_db.insert_one(coll, {"_id": 1, "ticker": "AAA",
                               "fundamentals": {"price": 100.0}, "views": 0})
    mongo_db.update_one(coll, {"ticker": "AAA"},
                        {"$set": {"fundamentals.price": 110.0}})
    mongo_db.update_one(coll, {"_id": 1}, {"$inc": {"views": 1}})
    doc = mongo_db.find_one(coll, {"_id": 1})
    assert doc["fundamentals"]["price"] == 110.0
    assert doc["views"] == 1


def test_add_to_set_and_pull_tags(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    mongo_db.insert_one(coll, {"_id": 1, "ticker": "AAA", "tags": []})
    mongo_db.update_one(coll, {"_id": 1}, {"$addToSet": {"tags": "dividend"}})
    mongo_db.update_one(coll, {"_id": 1}, {"$addToSet": {"tags": "dividend"}})
    assert mongo_db.find_one(coll, {"_id": 1})["tags"] == ["dividend"]
    mongo_db.update_one(coll, {"_id": 1}, {"$pull": {"tags": "dividend"}})
    assert mongo_db.find_one(coll, {"_id": 1})["tags"] == []


def test_push_and_pull_holdings(mongo_db_conn):
    coll = mongo_db_conn["portfolios"]
    mongo_db.insert_one(coll, {"_id": 1, "portfolio_name": "P1", "holdings": []})
    mongo_db.update_one(coll, {"_id": 1},
                        {"$push": {"holdings": {"ticker": "AAA", "quantity": 5}}})
    mongo_db.update_one(coll, {"_id": 1},
                        {"$push": {"holdings": {"ticker": "BBB", "quantity": 2}}})
    assert [h["ticker"] for h in
            mongo_db.find_one(coll, {"_id": 1})["holdings"]] == ["AAA", "BBB"]
    mongo_db.update_one(coll, {"_id": 1},
                        {"$pull": {"holdings": {"ticker": "AAA"}}})
    assert [h["ticker"] for h in
            mongo_db.find_one(coll, {"_id": 1})["holdings"]] == ["BBB"]


def test_delete_one_and_count(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    mongo_db.insert_many(coll, [{"_id": 1, "ticker": "AAA"},
                                {"_id": 2, "ticker": "BBB"}])
    result = mongo_db.delete_one(coll, {"ticker": "AAA"})
    assert result.deleted_count == 1
    assert mongo_db.count(coll) == 1
    mongo_db.delete_many(coll, {})
    assert mongo_db.count(coll) == 0


def test_upsert_is_idempotent(mongo_db_conn):
    """replace_one(upsert=True) by natural key never duplicates documents."""
    coll = mongo_db_conn["portfolio_snapshots"]
    key = {"_id": "1:2026-01-01"}
    mongo_db.upsert(coll, key, {**key, "total_market_value": 100.0})
    mongo_db.upsert(coll, key, {**key, "total_market_value": 250.0})
    assert mongo_db.count(coll) == 1
    assert mongo_db.find_one(coll, key)["total_market_value"] == 250.0


def test_duplicate_id_rejected(mongo_db_conn):
    coll = mongo_db_conn["stock_fundamentals"]
    mongo_db.insert_one(coll, {"_id": 1, "ticker": "AAA"})
    with pytest.raises(mongo_db.PyMongoError):
        mongo_db.insert_one(coll, {"_id": 1, "ticker": "AAA"})
    assert mongo_db.count(coll) == 1


def test_aggregate_helper_runs_pipeline(mongo_db_conn):
    coll = mongo_db_conn["transactions"]
    mongo_db.insert_many(coll, [
        {"_id": 1, "portfolio_id": 1, "transaction_type": "BUY", "quantity": 2},
        {"_id": 2, "portfolio_id": 1, "transaction_type": "BUY", "quantity": 3},
        {"_id": 3, "portfolio_id": 1, "transaction_type": "SELL", "quantity": 1},
    ])
    rows = mongo_db.aggregate(coll, [
        {"$match": {"transaction_type": "BUY"}},
        {"$group": {"_id": None, "total": {"$sum": "$quantity"}}},
    ])
    assert rows == [{"_id": None, "total": 5}]
