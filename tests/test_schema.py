"""Schema-level tests: constraints, foreign keys, and referential actions.

Every test performs an INVALID operation and asserts that MySQL rejects it
AND that nothing changed - which is the database itself enforcing the
integrity rules that sp_record_transaction also guards in application flow.
"""

from __future__ import annotations

import pytest
from conftest import new_portfolio, new_user, q, q1, scalar, stock_id_by_ticker


# ---------------------------------------------------------------------------
# UNIQUE constraints
# ---------------------------------------------------------------------------
def test_duplicate_email_rejected(db_conn):
    import db as _db
    existing = q1(db_conn, "SELECT email FROM users WHERE user_id = 1")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn, "UPDATE users SET email = %s WHERE user_id = 2",
                    (existing["email"],))
    row = q1(db_conn, "SELECT email FROM users WHERE user_id = 2")
    assert row["email"] != existing["email"]  # unchanged


def test_duplicate_username_rejected(db_conn):
    existing = q1(db_conn, "SELECT username FROM users WHERE user_id = 1")
    import db as _db
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn, "UPDATE users SET username = %s WHERE user_id = 2",
                    (existing["username"],))
    row = q1(db_conn, "SELECT username FROM users WHERE user_id = 2")
    assert row["username"] != existing["username"]  # unchanged


def test_duplicate_ticker_rejected(db_conn):
    import db as _db
    aapl = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO stocks (ticker_symbol, company_name, sector_id, "
                    "current_price) VALUES (%s, %s, %s, %s)",
                    ("AAPL", "Duplicate Inc.", 1, 100.00))
    assert scalar(db_conn, "SELECT COUNT(*) FROM stocks WHERE ticker_symbol = 'AAPL'") == 1


def test_same_portfolio_name_allowed_for_different_users(db_conn):
    """The UNIQUE constraint is (user_id, portfolio_name), not global."""
    user_a = new_user(db_conn, "namea")
    user_b = new_user(db_conn, "nameb")
    new_portfolio(db_conn, user_a, name="Shared Name")
    new_portfolio(db_conn, user_b, name="Shared Name")  # must NOT raise
    count = scalar(db_conn,
                   "SELECT COUNT(*) FROM portfolios WHERE portfolio_name = 'Shared Name'")
    assert count == 2


def test_duplicate_portfolio_name_same_user_rejected(db_conn):
    import db as _db
    user_id = new_user(db_conn, "dupname")
    new_portfolio(db_conn, user_id, name="Only One")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO portfolios (user_id, portfolio_name) "
                    "VALUES (%s, %s)", (user_id, "Only One"))


def test_duplicate_snapshot_rejected(db_conn):
    """UNIQUE (portfolio_id, snapshot_date): one snapshot per day."""
    import db as _db
    row = q1(db_conn,
             "SELECT portfolio_id, snapshot_date FROM portfolio_snapshots LIMIT 1")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO portfolio_snapshots (portfolio_id, snapshot_date, "
                    "total_market_value, total_cost_basis, holdings_count) "
                    "VALUES (%s, %s, 1.00, 1.00, 1)",
                    (row["portfolio_id"], row["snapshot_date"]))
    n = scalar(db_conn,
               "SELECT COUNT(*) FROM portfolio_snapshots "
               "WHERE portfolio_id = %s AND snapshot_date = %s",
               (row["portfolio_id"], row["snapshot_date"]))
    assert n == 1  # the original row only


# ---------------------------------------------------------------------------
# CHECK constraints (require MySQL 8.0.16+)
# ---------------------------------------------------------------------------
def test_transaction_zero_quantity_rejected(db_conn):
    import db as _db
    user_id = new_user(db_conn, "chkq")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO transactions (portfolio_id, stock_id, "
                    "transaction_type, quantity, price_per_unit, transaction_date) "
                    "VALUES (%s, %s, 'BUY', %s, %s, '2026-01-05 10:00:00')",
                    (portfolio_id, stock_id, 0, 100.00))
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s", (portfolio_id,)) == 0


def test_transaction_negative_price_rejected(db_conn):
    import db as _db
    user_id = new_user(db_conn, "chkp")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO transactions (portfolio_id, stock_id, "
                    "transaction_type, quantity, price_per_unit, transaction_date) "
                    "VALUES (%s, %s, 'BUY', %s, %s, '2026-01-05 10:00:00')",
                    (portfolio_id, stock_id, 10, -1.00))
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s", (portfolio_id,)) == 0


def test_holdings_zero_quantity_rejected(db_conn):
    """The holdings invariant (quantity > 0) is enforced by a CHECK."""
    import db as _db
    user_id = new_user(db_conn, "chkh")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO holdings (portfolio_id, stock_id, quantity, "
                    "average_cost_per_unit) VALUES (%s, %s, %s, %s)",
                    (portfolio_id, stock_id, 0, 100.00))
    assert scalar(db_conn, "SELECT COUNT(*) FROM holdings "
                           "WHERE portfolio_id = %s", (portfolio_id,)) == 0


def test_stock_zero_price_rejected(db_conn):
    import db as _db
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO stocks (ticker_symbol, company_name, sector_id, "
                    "current_price) VALUES ('ZZZZ', 'Bad Price Inc.', 1, 0)")


def test_stock_dividend_yield_range_checked(db_conn):
    import db as _db
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO stocks (ticker_symbol, company_name, sector_id, "
                    "current_price, dividend_yield) "
                    "VALUES ('ZZZY', 'Yield Out Of Range', 1, 10.00, 250.00)")


# ---------------------------------------------------------------------------
# Foreign keys: invalid references and referential actions
# ---------------------------------------------------------------------------
def test_transaction_unknown_portfolio_rejected(db_conn):
    import db as _db
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO transactions (portfolio_id, stock_id, "
                    "transaction_type, quantity, price_per_unit, transaction_date) "
                    "VALUES (999999, %s, 'BUY', 1, 1.00, '2026-01-05 10:00:00')",
                    (stock_id,))


def test_stock_unknown_sector_rejected(db_conn):
    import db as _db
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn,
                    "INSERT INTO stocks (ticker_symbol, company_name, sector_id, "
                    "current_price) VALUES ('ZZZX', 'Ghost Sector Inc.', 999999, 5.00)")


def test_user_delete_cascades_to_everything(db_conn):
    """ON DELETE CASCADE: removing a user removes their portfolios,
    holdings, transactions, and snapshots."""
    import db as _db
    user_id = new_user(db_conn, "cascade")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "KO")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 50.00, "2026-01-05 10:00:00")
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-06")

    assert scalar(db_conn, "SELECT COUNT(*) FROM portfolios WHERE user_id = %s",
                  (user_id,)) == 1

    _db.execute(db_conn, "DELETE FROM users WHERE user_id = %s", (user_id,))

    assert scalar(db_conn, "SELECT COUNT(*) FROM users WHERE user_id = %s",
                  (user_id,)) == 0
    assert scalar(db_conn, "SELECT COUNT(*) FROM portfolios WHERE user_id = %s",
                  (user_id,)) == 0
    assert scalar(db_conn, "SELECT COUNT(*) FROM holdings WHERE portfolio_id = %s",
                  (portfolio_id,)) == 0
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions WHERE portfolio_id = %s",
                  (portfolio_id,)) == 0
    assert scalar(db_conn,
                  "SELECT COUNT(*) FROM portfolio_snapshots WHERE portfolio_id = %s",
                  (portfolio_id,)) == 0


def test_stock_delete_restricted_while_referenced(db_conn):
    """ON DELETE RESTRICT: a stock referenced by transactions cannot be
    deleted - the audit trail is never silently destroyed."""
    import db as _db
    aapl = stock_id_by_ticker(db_conn, "AAPL")
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn, "DELETE FROM stocks WHERE stock_id = %s", (aapl,))
    assert q1(db_conn, "SELECT ticker_symbol FROM stocks WHERE stock_id = %s",
              (aapl,))["ticker_symbol"] == "AAPL"


def test_portfolio_delete_cascades_to_children(db_conn):
    """ON DELETE CASCADE: removing a PORTFOLIO removes its holdings,
    transactions, and snapshots (the CRUD demo's option 8)."""
    import db as _db
    user_id = new_user(db_conn, "pcascade")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "KO")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           10, 50.00, "2026-01-05 10:00:00")
    _db.create_snapshot(db_conn, portfolio_id, "2026-01-06")

    _db.execute(db_conn, "DELETE FROM portfolios WHERE portfolio_id = %s",
                (portfolio_id,))

    for table in ("portfolios", "holdings", "transactions",
                  "portfolio_snapshots"):
        assert scalar(db_conn, f"SELECT COUNT(*) FROM {table} "
                               f"WHERE portfolio_id = %s",
                      (portfolio_id,)) == 0, table
    # The user survives: the cascade stops at their portfolio.
    assert scalar(db_conn, "SELECT COUNT(*) FROM users WHERE user_id = %s",
                  (user_id,)) == 1


def test_sector_delete_restricted_while_referenced(db_conn):
    """ON DELETE RESTRICT: a sector still referenced by stocks cannot be
    deleted (sectors 1-8 are all referenced by the seed)."""
    import db as _db
    with pytest.raises(_db.MySQLError):
        _db.execute(db_conn, "DELETE FROM sectors WHERE sector_id = 1")
    assert scalar(db_conn, "SELECT COUNT(*) FROM sectors "
                           "WHERE sector_id = 1") == 1
