"""Reconciliation and consistency tests.

These are the "database validation" layer of the project: they prove that
  1. the seeded holdings exactly match the transaction log (the seed
     materializes holdings via sp_rebuild_holdings, so this must hold),
  2. replaying the ENTIRE history with sp_rebuild_holdings reproduces the
     maintained holdings bit-for-bit (the weighted-average cost rules in
     the two code paths agree),
  3. the contract views are internally consistent (weights sum to 100%,
     view totals match direct computation, users without portfolios
     appear with zeros, performance rows link consecutive snapshots).

If any of these tests fail after someone changed data outside the
procedures, that is exactly the drift the reconciliation view exists to
catch.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import q, q1, scalar, stock_id_by_ticker

import db as _db


def test_seed_reconciliation_is_empty(pristine_db):
    """The master invariant: stored holdings == transaction-derived holdings."""
    rows = q(pristine_db, "SELECT * FROM v_holdings_reconciliation")
    assert rows == [], (
        f"holdings and transactions drifted out of sync: {rows}"
    )


def test_seed_row_counts(pristine_db):
    """The documented seed shape (also asserted by verify_setup.py)."""
    expected = {
        "users": 6,
        "portfolios": 7,
        "sectors": 8,
        "stocks": 26,
        "holdings": 38,
        "transactions": 48,
        "portfolio_snapshots": 52,
    }
    for table, count in expected.items():
        actual = int(scalar(pristine_db, f"SELECT COUNT(*) FROM {table}"))
        assert actual == count, f"{table}: expected {count}, found {actual}"


def test_full_exit_has_no_holding_row(db_conn):
    """P1 fully exited BA (sold all 15 shares on 2026-07-22): the transaction
    history exists but no holding row remains (qty would be 0)."""
    stock_id = stock_id_by_ticker(db_conn, "BA")
    tx = int(scalar(db_conn,
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE portfolio_id = 1 AND stock_id = %s", (stock_id,)))
    assert tx == 2  # the BUY and the full-exit SELL
    assert q1(db_conn, "SELECT * FROM holdings WHERE portfolio_id = 1 "
                       "AND stock_id = %s", (stock_id,)) is None


def test_rebuild_reproduces_maintained_holdings(db_conn):
    """sp_rebuild_holdings(1) must reproduce portfolio 1's holdings EXACTLY -
    same stocks, quantities, and weighted-average costs - because the
    procedure and the rebuild apply identical cost rules."""
    before = q(db_conn,
               "SELECT stock_id, quantity, average_cost_per_unit "
               "FROM holdings WHERE portfolio_id = 1 ORDER BY stock_id")
    assert len(before) == 10  # P1 holds 10 positions after the full BA exit

    cur = db_conn.cursor()
    try:
        cur.callproc("sp_rebuild_holdings", [1])
        db_conn.commit()
    finally:
        cur.close()

    after = q(db_conn,
              "SELECT stock_id, quantity, average_cost_per_unit "
              "FROM holdings WHERE portfolio_id = 1 ORDER BY stock_id")
    assert [(r["stock_id"], r["quantity"], r["average_cost_per_unit"])
            for r in after] == \
           [(r["stock_id"], r["quantity"], r["average_cost_per_unit"])
            for r in before]

    # And the invariant still holds afterwards.
    assert q(db_conn, "SELECT * FROM v_holdings_reconciliation") == []


def test_sector_weights_sum_to_100(db_conn):
    """For every portfolio, sector weights from v_sector_allocation must
    total ~100% (small rounding tolerance)."""
    rows = q(db_conn,
             "SELECT portfolio_id, "
             "       SUM(sector_weight_percent) AS total_weight "
             "FROM v_sector_allocation GROUP BY portfolio_id")
    assert rows, "expected sector allocation rows"
    for row in rows:
        assert abs(row["total_weight"] - Decimal("100")) < Decimal("0.10"), \
            f"portfolio {row['portfolio_id']} weights sum to {row['total_weight']}"


def test_positions_view_matches_direct_computation(db_conn):
    """v_portfolio_positions totals equal a direct holdings x price query.

    The direct query mirrors the view's per-position money formulas
    (ROUND(..., 2) per holding) - the view presents money in cents, and
    with 6-decimal average costs the raw products can carry fractions
    of a cent that the view rounds away per position.
    """
    view_rows = q(db_conn,
                  "SELECT portfolio_id, SUM(market_value) AS view_value, "
                  "       SUM(cost_basis) AS view_cost "
                  "FROM v_portfolio_positions GROUP BY portfolio_id")
    direct_rows = q(db_conn,
                    "SELECT h.portfolio_id, "
                    "        SUM(ROUND(h.quantity * s.current_price, 2)) AS direct_value, "
                    "        SUM(ROUND(h.quantity * h.average_cost_per_unit, 2)) AS direct_cost "
                    "FROM holdings h JOIN stocks s ON s.stock_id = h.stock_id "
                    "GROUP BY h.portfolio_id")
    direct = {r["portfolio_id"]: r for r in direct_rows}
    for row in view_rows:
        d = direct[row["portfolio_id"]]
        assert row["view_value"] == d["direct_value"]
        assert row["view_cost"] == d["direct_cost"]


def test_users_without_portfolios_have_zero_summary(db_conn):
    """li_wei and emma_johnson own nothing: LEFT JOINs must keep them with
    zero totals rather than dropping them."""
    for username in ("li_wei", "emma_johnson"):
        row = q1(db_conn,
                 "SELECT portfolio_count, position_count, total_market_value, "
                 "       total_cost_basis, total_unrealized_pl "
                 "FROM v_user_summary WHERE username = %s", (username,))
        assert row is not None, f"{username} missing from v_user_summary"
        assert row["portfolio_count"] == 0
        assert row["position_count"] == 0
        assert row["total_market_value"] == 0
        assert row["total_cost_basis"] == 0
        assert row["total_unrealized_pl"] == 0


def test_performance_view_links_consecutive_snapshots(db_conn):
    """v_portfolio_performance must produce exactly one row per snapshot;
    the first is unanchored (NULL previous) and all others reference the
    preceding snapshot's value."""
    snap_count = int(scalar(db_conn,
                            "SELECT COUNT(*) FROM portfolio_snapshots "
                            "WHERE portfolio_id = 1"))
    perf = q(db_conn,
             "SELECT snapshot_date, total_market_value, previous_market_value "
             "FROM v_portfolio_performance WHERE portfolio_id = 1 "
             "ORDER BY snapshot_date")
    assert len(perf) == snap_count == 13  # 12 handcrafted + 1 computed
    assert perf[0]["previous_market_value"] is None
    for prev, cur in zip(perf, perf[1:]):
        assert cur["previous_market_value"] == prev["total_market_value"]


def test_latest_snapshot_matches_current_positions(pristine_db):
    """The 2026-10-10 snapshot (created by sp_create_snapshot from seeded
    holdings x current prices) must equal the live positions view total for
    every portfolio - the computed present is consistent with holdings."""
    snapshots = {r["portfolio_id"]: r for r in q(
        pristine_db,
        "SELECT portfolio_id, total_market_value FROM portfolio_snapshots "
        "WHERE snapshot_date = '2026-10-10'")}
    live = q(pristine_db,
             "SELECT portfolio_id, SUM(market_value) AS total "
             "FROM v_portfolio_positions GROUP BY portfolio_id")
    assert len(snapshots) == 7
    for row in live:
        assert snapshots[row["portfolio_id"]]["total_market_value"] == \
            row["total"], f"portfolio {row['portfolio_id']} snapshot drift"
