"""Integration tests that drive the CRUD demo menu with scripted input.

These run ``python/crud_examples.py`` as a subprocess with stdin piped,
exercising exactly the code path a human demo user takes - the same
prompts, the same views and procedures, the same error surfacing.

SAFETY: every test runs against the THROWAWAY test database by setting
FINWISE_DB_NAME in the subprocess environment (which overrides the
.env default without touching the file). The main ``finwise`` database
is NEVER written to from this file; the one test that verifies the
"cannot connect" path never reaches any database at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import TEST_DB, new_portfolio, new_user, q1, scalar, stock_id_by_ticker

import db as _db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO = PROJECT_ROOT / "python" / "crud_examples.py"


def run_menu(inputs: list[str], db_name: str | None = TEST_DB,
             extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the demo, feeding `inputs` as stdin lines; return the result."""
    env = os.environ.copy()
    if db_name is not None:
        env["FINWISE_DB_NAME"] = db_name
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(DEMO)],
        input="\n".join(inputs) + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Option 1 - list users with summary totals
# ---------------------------------------------------------------------------
def test_option1_lists_all_users_including_empty_ones(test_db_name):
    proc = run_menu(["1", "0"])
    assert proc.returncode == 0, proc.stderr
    for username in ("aarav_mehta", "li_wei", "emma_johnson"):
        assert username in proc.stdout, f"{username} missing from option 1"


# ---------------------------------------------------------------------------
# Option 2 - list portfolios of a user
# ---------------------------------------------------------------------------
def test_option2_lists_portfolios_of_user_1(test_db_name):
    proc = run_menu(["2", "1", "0"])
    assert proc.returncode == 0, proc.stderr
    for name in ("Long-Term Growth", "Dividend Income", "Tech Focus"):
        assert name in proc.stdout


def test_option2_user_without_portfolios_shows_no_rows(test_db_name):
    proc = run_menu(["2", "5", "0"])   # li_wei owns nothing
    assert proc.returncode == 0, proc.stderr
    assert "(no rows)" in proc.stdout


def test_option2_nonexistent_user_shows_no_rows(test_db_name):
    proc = run_menu(["2", "999", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "(no rows)" in proc.stdout


def test_option2_reprompts_on_invalid_input(test_db_name):
    proc = run_menu(["2", "abc", "1", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Please enter a whole number." in proc.stdout
    assert "Long-Term Growth" in proc.stdout


# ---------------------------------------------------------------------------
# Option 3 - positions of a portfolio
# ---------------------------------------------------------------------------
def test_option3_positions_of_portfolio_1(test_db_name):
    proc = run_menu(["3", "1", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "AAPL" in proc.stdout


def test_option3_underwater_portfolio_reports_loss(test_db_name):
    """Regression (error 1690): portfolio 5 holds NKE below cost; option 3
    must print the negative unrealized P/L instead of crashing."""
    proc = run_menu(["3", "5", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "-345.00" in proc.stdout   # 60 x (78.45 - 84.20)


def test_option3_nonexistent_portfolio_shows_no_rows(test_db_name):
    proc = run_menu(["3", "999", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "(no rows)" in proc.stdout


# ---------------------------------------------------------------------------
# Option 4 - sector allocation
# ---------------------------------------------------------------------------
def test_option4_sector_allocation_portfolio_1(test_db_name):
    proc = run_menu(["4", "1", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Technology" in proc.stdout


def test_option4_empty_portfolio_shows_no_rows(db_conn, test_db_name):
    user_id = new_user(db_conn, "empty4")
    portfolio_id = new_portfolio(db_conn, user_id)
    proc = run_menu(["4", str(portfolio_id), "0"])
    assert proc.returncode == 0, proc.stderr
    assert "(no rows)" in proc.stdout


# ---------------------------------------------------------------------------
# Option 5 - performance history (the originally reported bug)
# ---------------------------------------------------------------------------
def test_option5_performance_history_portfolio_1(test_db_name):
    """Regression (error 1690): portfolio 1's value decreases twice in the
    seed; option 5 must print the full history including the negatives."""
    proc = run_menu(["5", "1", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "2025-10-10" in proc.stdout
    assert "-2700.00" in proc.stdout   # 2026-04-10: 67500 -> 64800
    assert "-1200.00" in proc.stdout   # 2026-08-10: 70400 -> 69200


def test_option5_nonexistent_portfolio_shows_no_rows(test_db_name):
    proc = run_menu(["5", "999", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "(no rows)" in proc.stdout


# ---------------------------------------------------------------------------
# Option 6 - add a user
# ---------------------------------------------------------------------------
def test_option6_adds_user_then_rejects_duplicate(db_conn, test_db_name):
    proc = run_menu(["6", "menu_aud", "menu.aud@example.test", "Menu Audit",
                     "6", "menu_aud", "menu.aud2@example.test", "Menu Audit 2",
                     "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Created user id" in proc.stdout
    assert "REJECTED by the database" in proc.stdout
    assert scalar(db_conn, "SELECT COUNT(*) FROM users "
                           "WHERE username = 'menu_aud'") == 1


def test_option6_rejects_empty_fields(db_conn, test_db_name):
    proc = run_menu(["6", "", "", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "All fields are required" in proc.stdout
    assert scalar(db_conn, "SELECT COUNT(*) FROM users "
                           "WHERE username = ''") == 0


# ---------------------------------------------------------------------------
# Option 7 - rename a portfolio
# ---------------------------------------------------------------------------
def test_option7_renames_existing_portfolio(db_conn, test_db_name):
    user_id = new_user(db_conn, "ren7")
    portfolio_id = new_portfolio(db_conn, user_id, name="Old Menu Name")
    proc = run_menu(["7", str(portfolio_id), "New Menu Name", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Renamed." in proc.stdout
    assert q1(db_conn, "SELECT portfolio_name FROM portfolios "
                      "WHERE portfolio_id = %s",
              (portfolio_id,))["portfolio_name"] == "New Menu Name"


def test_option7_nonexistent_portfolio_reports_nothing_changed(test_db_name):
    """Regression: the demo used to print 'Renamed.' even when the id did
    not exist (UPDATE matched 0 rows)."""
    proc = run_menu(["7", "999", "Whatever", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "No portfolio with id 999" in proc.stdout
    assert "Renamed." not in proc.stdout


# ---------------------------------------------------------------------------
# Option 8 - delete a portfolio (CASCADE demo)
# ---------------------------------------------------------------------------
def _portfolio_with_activity(conn):
    user_id = new_user(conn, "del8")
    portfolio_id = new_portfolio(conn, user_id)
    stock_id = stock_id_by_ticker(conn, "KO")
    _db.record_transaction(conn, portfolio_id, stock_id, "BUY",
                           10, 50.00, "2026-01-05 10:00:00")
    _db.create_snapshot(conn, portfolio_id, "2026-01-06")
    return user_id, portfolio_id


def test_option8_cancellation_leaves_everything_intact(db_conn, test_db_name):
    user_id, portfolio_id = _portfolio_with_activity(db_conn)
    proc = run_menu(["8", str(portfolio_id), "no", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Cancelled." in proc.stdout
    assert scalar(db_conn, "SELECT COUNT(*) FROM portfolios "
                           "WHERE portfolio_id = %s",
                  (portfolio_id,)) == 1


def test_option8_delete_cascades_to_children(db_conn, test_db_name):
    user_id, portfolio_id = _portfolio_with_activity(db_conn)
    proc = run_menu(["8", str(portfolio_id), "YES", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Deleted" in proc.stdout
    for table in ("portfolios", "holdings", "transactions",
                  "portfolio_snapshots"):
        assert scalar(db_conn, f"SELECT COUNT(*) FROM {table} "
                               f"WHERE portfolio_id = %s",
                      (portfolio_id,)) == 0, table
    # The user survives: the cascade stops at their portfolio.
    assert scalar(db_conn, "SELECT COUNT(*) FROM users WHERE user_id = %s",
                  (user_id,)) == 1


def test_option8_nonexistent_portfolio_reports_nothing_deleted(test_db_name):
    """Regression: the demo used to print 'Deleted (...)' even when the id
    did not exist."""
    proc = run_menu(["8", "999", "YES", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "No portfolio with id 999" in proc.stdout
    assert "Deleted" not in proc.stdout


# ---------------------------------------------------------------------------
# Option 9 - record BUY / SELL through the procedure
# ---------------------------------------------------------------------------
def test_option9_buy_via_menu(db_conn, test_db_name):
    user_id = new_user(db_conn, "buy9")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    before = scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                             "WHERE portfolio_id = %s", (portfolio_id,))
    proc = run_menu(["9", str(portfolio_id), str(stock_id), "BUY",
                     "2", "245.50", "2027-04-01 10:00:00", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "Committed" in proc.stdout
    db_conn.rollback()  # end the REPEATABLE READ snapshot so the
    # subprocess's committed rows become visible below
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s",
                  (portfolio_id,)) == before + 1
    row = q1(db_conn, "SELECT quantity FROM holdings "
                      "WHERE portfolio_id = %s AND stock_id = %s",
             (portfolio_id, stock_id))
    assert row["quantity"] == Decimal("2.0000")


def test_option9_invalid_type_then_oversell_leaves_no_partial_state(
        db_conn, test_db_name):
    user_id = new_user(db_conn, "sell9")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           2, 200.00, "2027-04-01 09:00:00")
    tx_before = scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                                "WHERE portfolio_id = %s", (portfolio_id,))

    # 'TRADE' is re-prompted client-side, then a 9999-share SELL is
    # rejected server-side by sp_record_transaction.
    proc = run_menu(["9", str(portfolio_id), str(stock_id), "TRADE", "SELL",
                     "9999", "245.50", "2027-04-01 11:00:00", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "REJECTED by the database" in proc.stdout
    assert "exceeds" in proc.stdout
    db_conn.rollback()  # refresh the snapshot: without this the stale
    # read view would mask any hypothetical partial state below

    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s",
                  (portfolio_id,)) == tx_before
    row = q1(db_conn, "SELECT quantity, average_cost_per_unit FROM holdings "
                      "WHERE portfolio_id = %s AND stock_id = %s",
             (portfolio_id, stock_id))
    assert row["quantity"] == Decimal("2.0000")
    assert row["average_cost_per_unit"] == Decimal("200.00")


def test_option9_nonexistent_stock_rejected(db_conn, test_db_name):
    user_id = new_user(db_conn, "badstk9")
    portfolio_id = new_portfolio(db_conn, user_id)
    proc = run_menu(["9", str(portfolio_id), "999999", "BUY",
                     "1", "1.00", "2027-04-01 10:00:00", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "REJECTED by the database" in proc.stdout
    assert "Stock does not exist" in proc.stdout
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s",
                  (portfolio_id,)) == 0


def test_option9_invalid_date_rejected(db_conn, test_db_name):
    user_id = new_user(db_conn, "baddate9")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    proc = run_menu(["9", str(portfolio_id), str(stock_id), "BUY",
                     "1", "10.00", "not-a-date", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert "REJECTED by the database" in proc.stdout
    assert scalar(db_conn, "SELECT COUNT(*) FROM transactions "
                           "WHERE portfolio_id = %s",
                  (portfolio_id,)) == 0


# ---------------------------------------------------------------------------
# Option 10 - snapshots (idempotent upsert)
# ---------------------------------------------------------------------------
def test_option10_snapshot_upsert_via_menu(db_conn, test_db_name):
    user_id = new_user(db_conn, "snap10")
    portfolio_id = new_portfolio(db_conn, user_id)
    stock_id = stock_id_by_ticker(db_conn, "AAPL")
    _db.record_transaction(db_conn, portfolio_id, stock_id, "BUY",
                           2, 100.00, "2027-05-01 09:00:00")

    proc = run_menu(["10", str(portfolio_id), "2027-05-01",
                     "10", str(portfolio_id), "2027-05-01",
                     "0"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("Snapshot created") == 2
    # Same (portfolio, date) twice -> exactly one row (upsert, not duplicate).
    assert scalar(db_conn, "SELECT COUNT(*) FROM portfolio_snapshots "
                           "WHERE portfolio_id = %s AND snapshot_date = %s",
                  (portfolio_id, "2027-05-01")) == 1
    row = q1(db_conn, "SELECT total_market_value, total_cost_basis, "
                      "holdings_count FROM portfolio_snapshots "
                      "WHERE portfolio_id = %s AND snapshot_date = %s",
             (portfolio_id, "2027-05-01"))
    assert row["total_market_value"] == Decimal("491.00")   # 2 x 245.50
    assert row["total_cost_basis"] == Decimal("200.00")
    assert row["holdings_count"] == 1


# ---------------------------------------------------------------------------
# Option 0, unknown options, EOF, and connection failure
# ---------------------------------------------------------------------------
def test_unknown_menu_choices_then_exit(test_db_name):
    proc = run_menu(["99", "abc", "", "0"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("Unknown option.") == 3
    assert "Bye." in proc.stdout


def test_eof_exits_cleanly(test_db_name):
    proc = run_menu([""])
    assert proc.returncode == 0, proc.stderr
    assert "Bye." in proc.stdout


def test_connection_failure_prints_hint_and_exits():
    """Bad port -> the demo must exit(1) with the documented hint instead
    of a traceback."""
    proc = run_menu(["0"], db_name=None,
                    extra_env={"FINWISE_DB_PORT": "59999"})
    assert proc.returncode == 1
    assert "Could not connect to MySQL" in proc.stdout
    assert "Hint" in proc.stdout
    assert "Traceback" not in proc.stderr
