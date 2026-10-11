"""Regression tests for signed arithmetic in the contract views.

MySQL types ``UNSIGNED DECIMAL - UNSIGNED DECIMAL`` as UNSIGNED, so a
difference that goes negative (a losing position, a portfolio value
decrease, a net-loss user) raises

    Error 1690 (22003): DECIMAL UNSIGNED value is out of range

unless the operands are explicitly CAST to signed DECIMAL. The seed
data contains real triggers (portfolio 1's value decreases twice,
portfolio 5 holds NKE below cost), and the views must report those
negatives instead of raising.

Every test here builds the negative scenario explicitly (or uses the
pristine seed where noted) and asserts the view returns the expected
NEGATIVE value. These tests fail with DataError 1690 before the CAST
fix and pass after it.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import new_portfolio, new_user, q1, stock_id_by_ticker

import db as _db

D1 = "2027-03-01"
D2 = "2027-03-02"
D3 = "2027-03-03"


def _fresh_portfolio(conn):
    user_id = new_user(conn, "signed")
    portfolio_id = new_portfolio(conn, user_id)
    return portfolio_id, stock_id_by_ticker(conn, "AAPL")


# ---------------------------------------------------------------------------
# v_portfolio_performance: decreasing / unchanged / zero-previous values
# ---------------------------------------------------------------------------
def test_performance_view_reports_value_decrease(db_conn):
    """A portfolio whose market value DROPS must yield a negative
    change_value / change_percent, not error 1690."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 100.00, "2027-03-01 09:00:00")
    _db.create_snapshot(db_conn, portfolio_id, D1)   # 10 x 245.50 = 2455.00
    _db.record_transaction(db_conn, portfolio_id, stock_id, "SELL",
                            9, 245.50, "2027-03-01 10:00:00")
    _db.create_snapshot(db_conn, portfolio_id, D2)   # 1 x 245.50 = 245.50

    row = q1(db_conn,
             "SELECT change_value, change_percent "
             "FROM v_portfolio_performance "
             "WHERE portfolio_id = %s AND snapshot_date = %s",
             (portfolio_id, D2))
    assert row["change_value"] == Decimal("-2209.50")
    assert row["change_percent"] == Decimal("-90.00")


def test_performance_view_seed_portfolio_1_has_negative_changes(pristine_db):
    """The reported production bug: seeded portfolio 1 decreases twice
    (2026-04-10: 67500 -> 64800 and 2026-08-10: 70400 -> 69200). Reading
    change_value must work and return those negatives."""
    rows = q1(pristine_db,
              "SELECT change_value FROM v_portfolio_performance "
              "WHERE portfolio_id = 1 AND snapshot_date = '2026-04-10'")
    assert rows["change_value"] == Decimal("-2700.00")
    rows = q1(pristine_db,
              "SELECT change_value, change_percent "
              "FROM v_portfolio_performance "
              "WHERE portfolio_id = 1 AND snapshot_date = '2026-08-10'")
    assert rows["change_value"] == Decimal("-1200.00")
    assert rows["change_percent"] == Decimal("-1.70")  # -1200/70400 = -1.7045


def test_performance_view_unchanged_value(db_conn):
    """Two snapshots with the same value: change 0.00, percent 0.00."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 100.00, "2027-03-01 09:00:00")
    _db.create_snapshot(db_conn, portfolio_id, D1)
    _db.create_snapshot(db_conn, portfolio_id, D2)   # nothing changed

    row = q1(db_conn,
             "SELECT change_value, change_percent "
             "FROM v_portfolio_performance "
             "WHERE portfolio_id = %s AND snapshot_date = %s",
             (portfolio_id, D2))
    assert row["change_value"] == Decimal("0.00")
    assert row["change_percent"] == Decimal("0.00")


def test_performance_view_first_snapshot_has_null_change(db_conn):
    """A portfolio's only snapshot has no previous: NULL change columns."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 100.00, "2027-03-01 09:00:00")
    _db.create_snapshot(db_conn, portfolio_id, D1)

    row = q1(db_conn,
             "SELECT change_value, change_percent, previous_market_value "
             "FROM v_portfolio_performance WHERE portfolio_id = %s",
             (portfolio_id,))
    assert row["previous_market_value"] is None
    assert row["change_value"] is None
    assert row["change_percent"] is None


def test_performance_view_zero_previous_value(db_conn):
    """Previous snapshot was an empty portfolio (value 0): the absolute
    change is the full value, and the percent change is NULL (division
    by zero is guarded, per the view's CASE)."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.create_snapshot(db_conn, portfolio_id, D1)   # empty portfolio: 0.00
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 100.00, "2027-03-02 09:00:00")
    _db.create_snapshot(db_conn, portfolio_id, D2)   # 1 x 245.50

    row = q1(db_conn,
             "SELECT change_value, change_percent "
             "FROM v_portfolio_performance "
             "WHERE portfolio_id = %s AND snapshot_date = %s",
             (portfolio_id, D2))
    assert row["change_value"] == Decimal("245.50")
    assert row["change_percent"] is None


# ---------------------------------------------------------------------------
# v_portfolio_positions: losing positions
# ---------------------------------------------------------------------------
def test_positions_view_reports_losing_position(db_conn):
    """A position bought above the current price (a loss) must yield a
    negative unrealized_pl / pl_percent, not error 1690."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 300.00, "2027-03-01 09:00:00")
    # current AAPL price in the seed is 245.50 -> loss of 54.50 per share

    row = q1(db_conn,
             "SELECT unrealized_pl, pl_percent "
             "FROM v_portfolio_positions "
             "WHERE portfolio_id = %s AND stock_id = %s",
             (portfolio_id, stock_id))
    assert row["unrealized_pl"] == Decimal("-54.50")
    assert row["pl_percent"] == Decimal("-18.17")  # 100 * -54.50 / 300


def test_positions_view_seed_portfolio_5_nke_is_underwater(pristine_db):
    """The seeded underwater position: portfolio 5 bought NKE at 84.20,
    its illustrative price is 78.45. The view must report the loss."""
    nke = stock_id_by_ticker(pristine_db, "NKE")
    row = q1(pristine_db,
             "SELECT unrealized_pl, pl_percent "
             "FROM v_portfolio_positions "
             "WHERE portfolio_id = 5 AND stock_id = %s", (nke,))
    # 60 shares * (78.45 - 84.20) = -345.00
    assert row["unrealized_pl"] == Decimal("-345.00")
    assert row["pl_percent"] == Decimal("-6.83")  # 100 * -5.75 / 84.20


# ---------------------------------------------------------------------------
# v_user_summary: net-loss users
# ---------------------------------------------------------------------------
def test_user_summary_reports_net_loss(db_conn):
    """A user whose only position is underwater must show a negative
    total_unrealized_pl, not error 1690."""
    user_id = new_user(db_conn, "netloss")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 300.00, "2027-03-01 09:00:00")
    # market value 245.50 vs cost 300.00 -> net -54.50

    row = q1(db_conn,
             "SELECT total_market_value, total_cost_basis, total_unrealized_pl "
             "FROM v_user_summary WHERE user_id = %s", (user_id,))
    assert row["total_market_value"] == Decimal("245.50")
    assert row["total_cost_basis"] == Decimal("300.00")
    assert row["total_unrealized_pl"] == Decimal("-54.50")


def test_positions_view_profitable_position_unchanged(db_conn):
    """Guard against over-correction: a profitable position still reports
    positive P/L after the CAST fix."""
    portfolio_id, stock_id = _fresh_portfolio(db_conn)
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           1, 100.00, "2027-03-01 09:00:00")
    row = q1(db_conn,
             "SELECT unrealized_pl, pl_percent "
             "FROM v_portfolio_positions "
             "WHERE portfolio_id = %s AND stock_id = %s",
             (portfolio_id, stock_id))
    assert row["unrealized_pl"] == Decimal("145.50")   # 245.50 - 100
    assert row["pl_percent"] == Decimal("145.50")      # 100 * 145.50 / 100
