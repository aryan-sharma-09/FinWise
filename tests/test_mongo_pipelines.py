"""Aggregation-pipeline + ETL tests for the FinWise MongoDB read model.

Two layers:

  * PIPELINE tests seed a small, deterministic dataset (using the SAME
    builders the ETL uses) into the throwaway MongoDB database, then assert
    the five pipelines produce the expected numbers. They need MongoDB only.

  * The ETL test runs the real read-only load from the MySQL test database
    into MongoDB, and is SKIPPED unless both MySQL and MongoDB are available.
    It also proves the load is idempotent and never writes back to MySQL.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import scalar

import mongo_db
import mongo_demo
import load_mongo


# ---------------------------------------------------------------------------
# Deterministic seed rows, shaped exactly like the MySQL sources the ETL
# reads. They are fed through the real builders, so this also tests the ETL's
# document construction without needing MySQL.
# ---------------------------------------------------------------------------
STOCK_ROWS = [
    {"stock_id": 1, "ticker_symbol": "AAPL", "company_name": "Apple Inc.",
     "sector_name": "Technology", "sector_description": "Hardware + software",
     "current_price": 120.0, "market_cap_millions": 3_000_000.0,
     "pe_ratio": 30.0, "dividend_yield": None, "price_as_of": date(2026, 10, 10)},
    {"stock_id": 2, "ticker_symbol": "JPM", "company_name": "JPMorgan Chase",
     "sector_name": "Financials", "sector_description": "Banks",
     "current_price": 200.0, "market_cap_millions": 700_000.0,
     "pe_ratio": 15.0, "dividend_yield": 2.0, "price_as_of": date(2026, 10, 10)},
    {"stock_id": 3, "ticker_symbol": "XOM", "company_name": "Exxon Mobil",
     "sector_name": "Energy", "sector_description": "Oil and gas",
     "current_price": 100.0, "market_cap_millions": 500_000.0,
     "pe_ratio": 13.0, "dividend_yield": 3.0, "price_as_of": date(2026, 10, 10)},
]

POSITION_ROWS = [
    {"portfolio_id": 1, "portfolio_name": "P1", "user_id": 1, "username": "u1",
     "stock_id": 1, "ticker_symbol": "AAPL", "company_name": "Apple Inc.",
     "sector_name": "Technology", "quantity": 10, "average_cost_per_unit": 100.0,
     "current_price": 120.0, "market_value": 1200.0, "unrealized_pl": 200.0,
     "portfolio_weight_percent": 60.0, "portfolio_total_value": 2000.0},
    {"portfolio_id": 1, "portfolio_name": "P1", "user_id": 1, "username": "u1",
     "stock_id": 2, "ticker_symbol": "JPM", "company_name": "JPMorgan Chase",
     "sector_name": "Financials", "quantity": 4, "average_cost_per_unit": 150.0,
     "current_price": 200.0, "market_value": 800.0, "unrealized_pl": 200.0,
     "portfolio_weight_percent": 40.0, "portfolio_total_value": 2000.0},
    {"portfolio_id": 2, "portfolio_name": "P2", "user_id": 2, "username": "u2",
     "stock_id": 3, "ticker_symbol": "XOM", "company_name": "Exxon Mobil",
     "sector_name": "Energy", "quantity": 50, "average_cost_per_unit": 90.0,
     "current_price": 100.0, "market_value": 5000.0, "unrealized_pl": 500.0,
     "portfolio_weight_percent": 100.0, "portfolio_total_value": 5000.0},
]

TX_ROWS = [
    {"transaction_id": 1, "portfolio_id": 1, "stock_id": 1, "ticker_symbol": "AAPL",
     "transaction_type": "BUY", "quantity": 10, "price_per_unit": 100.0,
     "transaction_date": date(2026, 1, 1), "notes": None},
    {"transaction_id": 2, "portfolio_id": 1, "stock_id": 2, "ticker_symbol": "JPM",
     "transaction_type": "BUY", "quantity": 20, "price_per_unit": 50.0,
     "transaction_date": date(2026, 1, 1), "notes": None},
    {"transaction_id": 3, "portfolio_id": 1, "stock_id": 1, "ticker_symbol": "AAPL",
     "transaction_type": "SELL", "quantity": 3, "price_per_unit": 130.0,
     "transaction_date": date(2026, 1, 3), "notes": None},
    {"transaction_id": 4, "portfolio_id": 1, "stock_id": 1, "ticker_symbol": "AAPL",
     "transaction_type": "BUY", "quantity": 5, "price_per_unit": 120.0,
     "transaction_date": date(2026, 1, 2), "notes": None},
]

SNAP_ROWS = [
    {"snapshot_id": 1, "portfolio_id": 1, "snapshot_date": date(2026, 1, 1),
     "total_market_value": 1000.0, "total_cost_basis": 900.0, "holdings_count": 1},
    {"snapshot_id": 2, "portfolio_id": 1, "snapshot_date": date(2026, 2, 1),
     "total_market_value": 1100.0, "total_cost_basis": 900.0, "holdings_count": 1},
    {"snapshot_id": 3, "portfolio_id": 1, "snapshot_date": date(2026, 3, 1),
     "total_market_value": 1210.0, "total_cost_basis": 900.0, "holdings_count": 1},
]


@pytest.fixture()
def seeded_mongo(mongo_db_conn):
    """Insert the deterministic seed through the real ETL builders."""
    mongo_db.insert_many(mongo_db_conn["stock_fundamentals"],
                         load_mongo.build_stock_fundamentals(STOCK_ROWS))
    mongo_db.insert_many(mongo_db_conn["portfolios"],
                         load_mongo.build_portfolios(POSITION_ROWS))
    mongo_db.insert_many(mongo_db_conn["transactions"],
                         load_mongo.build_transactions(TX_ROWS))
    mongo_db.insert_many(mongo_db_conn["portfolio_snapshots"],
                         load_mongo.build_snapshots(SNAP_ROWS))
    return mongo_db_conn


# ---------------------------------------------------------------------------
# Builder unit tests (no infrastructure required)
# ---------------------------------------------------------------------------
def test_builders_use_deterministic_ids():
    fundamentals = load_mongo.build_stock_fundamentals(STOCK_ROWS)
    assert [d["_id"] for d in fundamentals] == [1, 2, 3]
    assert fundamentals[0]["sector"]["name"] == "Technology"
    # NULL P/E / dividend stays null (semi-structured, unlike a fixed column)
    assert fundamentals[0]["fundamentals"]["dividend_yield"] is None

    transactions = load_mongo.build_transactions(TX_ROWS)
    assert [d["_id"] for d in transactions] == [1, 2, 3, 4]


def test_build_portfolios_groups_holdings_by_portfolio():
    portfolios = load_mongo.build_portfolios(POSITION_ROWS)
    by_id = {d["_id"]: d for d in portfolios}
    assert set(by_id) == {1, 2}
    assert [h["ticker"] for h in by_id[1]["holdings"]] == ["AAPL", "JPM"]
    assert by_id[2]["user"]["username"] == "u2"


def test_validation_rejects_empty_source():
    with pytest.raises(load_mongo.ETLValidationError):
        load_mongo._validate([], ["_id"], "x")


def test_sync_collection_is_idempotent_and_prunes(mongo_db_conn):
    """The ETL writer replaces by _id (no duplicates) and prunes vanished rows."""
    coll = mongo_db_conn["stock_fundamentals"]
    docs = load_mongo.build_stock_fundamentals(STOCK_ROWS)

    assert load_mongo.sync_collection(coll, docs) == 3
    # Re-run with the same source: still exactly 3 documents (idempotent).
    load_mongo.sync_collection(coll, docs)
    assert mongo_db.count(coll) == 3

    # Drop one source row: its document is pruned from the mirror.
    load_mongo.sync_collection(coll, docs[:2])
    assert mongo_db.count(coll) == 2
    assert mongo_db.find_one(coll, {"_id": 3}) is None


def test_ensure_indexes_creates_expected_indexes(mongo_db_conn):
    load_mongo.ensure_indexes(mongo_db_conn, verbose=False)
    keys = [spec["key"] for spec in
            mongo_db_conn["stock_fundamentals"].index_information().values()]
    assert [("ticker", 1)] in keys
    tx_keys = [spec["key"] for spec in
               mongo_db_conn["transactions"].index_information().values()]
    assert [("portfolio_id", 1), ("transaction_date", 1)] in tx_keys


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------
def test_pipeline_sector_allocation_weights_sum_to_100(seeded_mongo):
    rows = mongo_demo.pipeline_sector_allocation(seeded_mongo)
    p1 = [r for r in rows if r["portfolio_id"] == 1]
    assert {r["sector_name"] for r in p1} == {"Technology", "Financials"}
    assert round(sum(r["sector_weight_percent"] for r in p1), 2) == 100.0
    tech = next(r for r in p1 if r["sector_name"] == "Technology")
    assert tech["sector_value"] == 1200.0
    assert tech["sector_weight_percent"] == 60.0


def test_pipeline_top_positions_ranks_within_portfolio(seeded_mongo):
    rows = mongo_demo.pipeline_top_positions(seeded_mongo, 1)
    # One top position per portfolio.
    assert len(rows) == 2
    p1 = next(r for r in rows if r["portfolio_id"] == 1)
    assert p1["ticker"] == "AAPL"      # 1200 > 800
    assert p1["weight_rank"] == 1
    assert all(r["weight_rank"] == 1 for r in rows)


def test_pipeline_period_returns_links_consecutive_snapshots(seeded_mongo):
    rows = mongo_demo.pipeline_period_returns(seeded_mongo, portfolio_id=1)
    assert len(rows) == 3
    assert rows[0]["previous_market_value"] is None
    assert rows[0]["change_value"] is None
    assert rows[0]["change_percent"] is None
    for prev, cur in zip(rows, rows[1:]):
        assert cur["previous_market_value"] == prev["total_market_value"]
    assert rows[1]["change_value"] == 100.0
    assert rows[2]["change_percent"] == 10.0


def test_pipeline_running_invested_capital_is_cumulative_buys(seeded_mongo):
    rows = mongo_demo.pipeline_running_invested_capital(seeded_mongo,
                                                        portfolio_id=1)
    # Only BUY trades appear, cumulative and non-decreasing.
    assert [r["ticker"] for r in rows] == ["AAPL", "JPM", "AAPL"]
    running = [r["running_invested_capital"] for r in rows]
    assert running == sorted(running)
    assert running[-1] == 2600.0      # 10*100 + 20*50 + 5*120


def test_pipeline_dashboard_facet(seeded_mongo):
    result = mongo_demo.pipeline_portfolio_dashboard(seeded_mongo)
    assert set(result) == {"totals", "concentration_buckets", "largest_portfolios"}
    totals = result["totals"][0]
    assert totals["portfolios"] == 2
    assert totals["grand_total_value"] == 7000.0   # 2000 + 5000
    largest = result["largest_portfolios"][0]
    assert largest["portfolio_id"] == 2            # 5000 > 2000


# ---------------------------------------------------------------------------
# Full ETL integration test (needs BOTH MySQL and MongoDB; skipped otherwise)
# ---------------------------------------------------------------------------
def test_etl_from_mysql_is_idempotent_and_read_only(db_conn, mongo_db_conn):
    """Mirror the MySQL test database into MongoDB and verify the contract.

    - exact seed counts land in MongoDB,
    - a second run changes nothing (idempotent, no duplicates),
    - MySQL row counts are identical before and after (read-only).
    """
    mysql_before = {
        t: int(scalar(db_conn, f"SELECT COUNT(*) FROM {t}"))
        for t in ("stocks", "portfolios", "transactions", "portfolio_snapshots")
    }

    written = load_mongo.sync_all(db_conn, mongo_db_conn, verbose=False)
    assert written == {
        "stock_fundamentals": 26,
        "portfolios": 7,
        "transactions": 48,
        "portfolio_snapshots": 52,
    }

    written_again = load_mongo.sync_all(db_conn, mongo_db_conn, verbose=False)
    assert written_again == written
    assert mongo_db.count(mongo_db_conn["stock_fundamentals"]) == 26
    assert mongo_db.count(mongo_db_conn["portfolios"]) == 7
    assert mongo_db.count(mongo_db_conn["transactions"]) == 48
    assert mongo_db.count(mongo_db_conn["portfolio_snapshots"]) == 52

    # The real pipelines must also run against the real mirrored data.
    assert mongo_demo.pipeline_sector_allocation(mongo_db_conn)
    assert mongo_demo.pipeline_portfolio_dashboard(mongo_db_conn)["totals"]

    mysql_after = {
        t: int(scalar(db_conn, f"SELECT COUNT(*) FROM {t}"))
        for t in ("stocks", "portfolios", "transactions", "portfolio_snapshots")
    }
    assert mysql_after == mysql_before, "the ETL must never write back to MySQL"


# ---------------------------------------------------------------------------
# ETL orchestration test with a canned read-API source.
#
# The MySQL-dependent test above skips when MySQL is absent. This test feeds
# sync_all() a deterministic canned source shaped exactly like the read-API
# queries, so the full ETL orchestration (query -> build -> validate -> sync
# -> indexes) and the health-check expectations are exercised EVERYWHERE,
# with MongoDB only.
# ---------------------------------------------------------------------------
def _canned_source():
    sectors = [("Technology", "HW/SW"), ("Financials", "Banks"),
               ("Energy", "Oil"), ("Health Care", "Pharma")]
    stocks = [{
        "stock_id": i, "ticker_symbol": f"TK{i:02d}",
        "company_name": f"Company {i}",
        "sector_name": sectors[i % len(sectors)][0],
        "sector_description": sectors[i % len(sectors)][1],
        "current_price": 100.0 + i, "market_cap_millions": 1_000_000.0 + i,
        "pe_ratio": (None if i % 5 == 0 else 15.0 + i),
        "dividend_yield": (None if i % 3 == 0 else 2.0),
        "price_as_of": date(2026, 10, 10),
    } for i in range(1, 27)]

    positions = []
    for pid in range(1, 8):
        for k in range(3):
            sid = (pid * 3 + k) % 26 + 1
            positions.append({
                "portfolio_id": pid, "portfolio_name": f"P{pid}",
                "user_id": pid, "username": f"u{pid}",
                "stock_id": sid, "ticker_symbol": f"TK{sid:02d}",
                "company_name": f"Company {sid}",
                "sector_name": sectors[sid % len(sectors)][0],
                "quantity": 10.0, "average_cost_per_unit": 90.0,
                "current_price": 100.0, "market_value": 1000.0,
                "unrealized_pl": 100.0, "portfolio_weight_percent": 33.33,
                "portfolio_total_value": 3000.0,
            })

    transactions = [{
        "transaction_id": i, "portfolio_id": ((i - 1) % 7) + 1,
        "stock_id": ((i - 1) % 26) + 1, "ticker_symbol": f"TK{((i - 1) % 26) + 1:02d}",
        "transaction_type": "BUY" if i % 4 else "SELL",
        "quantity": 5.0, "price_per_unit": 100.0,
        "transaction_date": date(2026, 1, (i % 28) + 1), "notes": None,
    } for i in range(1, 49)]

    snapshots = [{
        "snapshot_id": i, "portfolio_id": ((i - 1) % 7) + 1,
        "snapshot_date": date(2026, (i % 12) + 1, 1),
        "total_market_value": 1000.0 + i, "total_cost_basis": 900.0,
        "holdings_count": 3,
    } for i in range(1, 53)]
    return stocks, positions, transactions, snapshots


def test_etl_orchestration_with_canned_source(monkeypatch, mongo_db_conn):
    stocks, positions, transactions, snapshots = _canned_source()

    def fake_fetch_all(_conn, sql, params=()):
        if "FROM stocks" in sql:
            return stocks
        if "v_portfolio_positions" in sql:
            return positions
        if "FROM transactions" in sql:
            return transactions
        if "FROM portfolio_snapshots" in sql:
            return snapshots
        raise AssertionError(f"unexpected ETL query: {sql}")

    monkeypatch.setattr(load_mongo.db, "fetch_all", fake_fetch_all)

    written = load_mongo.sync_all(None, mongo_db_conn, verbose=False)
    assert written == {"stock_fundamentals": 26, "portfolios": 7,
                       "transactions": 48, "portfolio_snapshots": 52}

    # Idempotent: a second pass writes the same documents, no duplicates.
    assert load_mongo.sync_all(None, mongo_db_conn, verbose=False) == written
    assert mongo_db.count(mongo_db_conn["stock_fundamentals"]) == 26

    # Every pipeline evaluates against the canned mirror.
    assert mongo_demo.pipeline_sector_allocation(mongo_db_conn)
    assert mongo_demo.pipeline_top_positions(mongo_db_conn, 2)
    assert mongo_demo.pipeline_period_returns(mongo_db_conn, portfolio_id=1)
    assert mongo_demo.pipeline_running_invested_capital(mongo_db_conn,
                                                        portfolio_id=1)
    assert mongo_demo.pipeline_portfolio_dashboard(mongo_db_conn)["totals"]
