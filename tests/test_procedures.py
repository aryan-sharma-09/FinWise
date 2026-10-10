"""Behavioral tests for the stored procedures.

The weighted-average cost rules tested here are the ones DOCUMENTED in
docs/database_contract.md and implemented by sp_record_transaction /
sp_rebuild_holdings:

    BUY : new_avg = (held_qty * held_avg + qty * price) / (held_qty + qty)
          rounded to 2 decimals.
    SELL: average cost per unit is unchanged; quantity is reduced; a full
          sell-out removes the holding row entirely.

Every rejected-call test also asserts the NO-PARTIAL-STATE guarantee: the
transactions table and the holdings table are exactly what they were before
the failed call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import (holding, new_portfolio, new_user, q1, scalar,
                      stock_id_by_ticker)

import db as _db

DATE = "2026-01-05 10:00:00"


@pytest.fixture()
def fresh_portfolio(db_conn):
    """A user + empty portfolio + the AAPL stock id (from the seed)."""
    user_id = new_user(db_conn, "proc")
    portfolio_id = new_portfolio(db_conn, user_id)
    return portfolio_id, stock_id_by_ticker(db_conn, "AAPL")


def tx_count(db_conn, portfolio_id) -> int:
    return int(scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                               "WHERE portfolio_id = %s", (portfolio_id,)))


# ---------------------------------------------------------------------------
# The documented weighted-average cost sequence
# ---------------------------------------------------------------------------
def test_documented_weighted_average_sequence(db_conn, fresh_portfolio):
    """The full documented example from the database contract:

    BUY  10 @ 100.00  -> qty 10, avg 100.00
    BUY   5 @ 130.00  -> qty 15, avg 110.00   (weighted average of lots)
    SELL  3 @ 150.00  -> qty 12, avg 110.00   (avg unchanged by a sale)
    BUY   6 @  95.00  -> qty 18, avg 105.00   ((12*110 + 6*95) / 18)
    SELL 18 @ 120.00  -> holding row deleted   (full exit)
    """
    portfolio_id, stock_id = fresh_portfolio

    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 100.00, DATE)
    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("10")
    assert row["average_cost_per_unit"] == Decimal("100.00")

    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           5, 130.00, DATE)
    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("15")
    assert row["average_cost_per_unit"] == Decimal("110.00")

    _db.record_transaction(db_conn, portfolio_id, stock_id, "SELL",
                           3, 150.00, DATE)
    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("12")
    assert row["average_cost_per_unit"] == Decimal("110.00")

    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           6, 95.00, DATE)
    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("18")
    assert row["average_cost_per_unit"] == Decimal("105.00")

    _db.record_transaction(db_conn, portfolio_id, stock_id, "SELL",
                           18, 120.00, DATE)
    assert holding(db_conn, portfolio_id, stock_id) is None
    assert tx_count(db_conn, portfolio_id) == 5


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_buy_creates_holding_and_transaction(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    tx_id = _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                                  10, 100.00, DATE, "test note")
    assert tx_id > 0

    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("10")
    assert row["average_cost_per_unit"] == Decimal("100.00")

    tx = q1(db_conn,
            "SELECT transaction_type, quantity, price_per_unit, notes "
            "FROM transactions WHERE transaction_id = %s", (tx_id,))
    assert tx["transaction_type"] == "BUY"
    assert tx["quantity"] == Decimal("10.0000")
    assert tx["price_per_unit"] == Decimal("100.00")
    assert tx["notes"] == "test note"


def test_fractional_shares_supported(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           2.5, 100.00, DATE)
    row = holding(db_conn, portfolio_id, stock_id)
    assert row["quantity"] == Decimal("2.5")


# ---------------------------------------------------------------------------
# Rejections - each must leave NO partial state
# ---------------------------------------------------------------------------
def assert_nothing_changed(db_conn, portfolio_id, stock_id,
                           expected_qty, expected_avg, expected_tx_count):
    row = holding(db_conn, portfolio_id, stock_id)
    if expected_qty is None:
        assert row is None
    else:
        assert row["quantity"] == Decimal(str(expected_qty))
        assert row["average_cost_per_unit"] == Decimal(str(expected_avg))
    assert tx_count(db_conn, portfolio_id) == expected_tx_count


def test_oversell_rejected_with_no_partial_state(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 100.00, DATE)

    with pytest.raises(_db.MySQLError, match="exceeds"):
        _db.record_transaction(db_conn, portfolio_id, stock_id, "SELL",
                               20, 150.00, DATE)

    assert_nothing_changed(db_conn, portfolio_id, stock_id, 10, "100.00", 1)


def test_sell_without_holdings_rejected(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    with pytest.raises(_db.MySQLError, match="no holdings"):
        _db.record_transaction(db_conn, portfolio_id, stock_id, "SELL",
                               1, 100.00, DATE)
    assert_nothing_changed(db_conn, portfolio_id, stock_id,
                           None, None, 0)


def test_invalid_transaction_type_rejected(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    with pytest.raises(_db.MySQLError, match="BUY or SELL"):
        _db.record_transaction(db_conn, portfolio_id, stock_id, "TRADE",
                               10, 100.00, DATE)
    assert_nothing_changed(db_conn, portfolio_id, stock_id, None, None, 0)


@pytest.mark.parametrize("bad_quantity", [0, -5])
def test_non_positive_quantity_rejected(db_conn, fresh_portfolio, bad_quantity):
    portfolio_id, stock_id = fresh_portfolio
    with pytest.raises(_db.MySQLError, match="[Qq]uantity"):
        _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                               bad_quantity, 100.00, DATE)
    assert_nothing_changed(db_conn, portfolio_id, stock_id, None, None, 0)


@pytest.mark.parametrize("bad_price", [0, -1.5])
def test_non_positive_price_rejected(db_conn, fresh_portfolio, bad_price):
    portfolio_id, stock_id = fresh_portfolio
    with pytest.raises(_db.MySQLError, match="[Pp]rice"):
        _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                               10, bad_price, DATE)
    assert_nothing_changed(db_conn, portfolio_id, stock_id, None, None, 0)


def test_unknown_stock_rejected(db_conn, fresh_portfolio):
    portfolio_id, _ = fresh_portfolio
    with pytest.raises(_db.MySQLError, match="Stock does not exist"):
        _db.record_transaction(db_conn, portfolio_id, 999999, "BUY",
                               10, 100.00, DATE)
    assert_nothing_changed(db_conn, portfolio_id, 999999, None, None, 0)


def test_unknown_portfolio_rejected(db_conn):
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError, match="Portfolio does not exist"):
        _db.record_transaction(db_conn, 999999, stock_id, "BUY",
                               10, 100.00, DATE)


# ---------------------------------------------------------------------------
# sp_create_snapshot
# ---------------------------------------------------------------------------
def test_snapshot_values_match_holdings(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 100.00, DATE)

    price = float(q1(db_conn, "SELECT current_price FROM stocks "
                              "WHERE stock_id = %s", (stock_id,))["current_price"])
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-10")

    snap = q1(db_conn,
              "SELECT total_market_value, total_cost_basis, holdings_count "
              "FROM portfolio_snapshots WHERE portfolio_id = %s "
              "AND snapshot_date = '2026-01-10'", (portfolio_id,))
    assert snap["total_market_value"] == Decimal(str(round(10 * price, 2)))
    assert snap["total_cost_basis"] == Decimal("1000.00")
    assert snap["holdings_count"] == 1


def test_snapshot_same_day_is_idempotent_upsert(db_conn, fresh_portfolio):
    portfolio_id, stock_id = fresh_portfolio
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 100.00, DATE)
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-10")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           5, 120.00, DATE)
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-10")  # refresh same day

    n = int(scalar(db_conn,
                   "SELECT COUNT(*) FROM portfolio_snapshots "
                   "WHERE portfolio_id = %s AND snapshot_date = '2026-01-10'",
                   (portfolio_id,)))
    assert n == 1  # updated, not duplicated

    snap = q1(db_conn,
              "SELECT total_cost_basis FROM portfolio_snapshots "
              "WHERE portfolio_id = %s AND snapshot_date = '2026-01-10'",
              (portfolio_id,))
    # 10*100 + 5*120 = 1600
    assert snap["total_cost_basis"] == Decimal("1600.00")


def test_snapshot_empty_portfolio_records_zeros(db_conn):
    user_id = new_user(db_conn, "empty")
    portfolio_id = new_portfolio(db_conn, user_id)
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-10")
    snap = q1(db_conn,
              "SELECT total_market_value, total_cost_basis, holdings_count "
              "FROM portfolio_snapshots WHERE portfolio_id = %s",
              (portfolio_id,))
    assert snap["total_market_value"] == Decimal("0.00")
    assert snap["total_cost_basis"] == Decimal("0.00")
    assert snap["holdings_count"] == 0
