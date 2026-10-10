"""Shared pytest fixtures for the FinWise test suite.

The suite runs against a THROWAWAY database (default name `finwise_test`,
configurable via FINWISE_TEST_DB_NAME) that is created fresh from the SQL
scripts at the start of every session and dropped afterwards. Your demo
database is never touched.

Safety guards:
  * The test database name must contain the word "test", otherwise the run
    aborts instead of dropping something important.
  * If mysql-connector-python is not installed, the password is not
    configured, or the MySQL server is unreachable, every test is SKIPPED
    with a clear reason instead of failing (so the suite can be collected
    anywhere, e.g. on a machine without MySQL).
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))

import db  # noqa: E402
import load_database  # noqa: E402

TEST_DB = os.environ.get("FINWISE_TEST_DB_NAME",
                         db.DEFAULTS["FINWISE_TEST_DB_NAME"])

if "test" not in TEST_DB.lower():
    raise pytest.UsageError(
        f"FINWISE_TEST_DB_NAME must contain the word 'test' (got {TEST_DB!r}). "
        "Refusing to run tests against a database that might hold real data."
    )

SQL_FILES = [load_database.SQL_DIR / f for f in load_database.DEFAULT_FILES]


# ---------------------------------------------------------------------------
# Session-scoped: build the throwaway database from the SQL scripts.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_db_name():
    if db.mysql is None:
        pytest.skip("mysql-connector-python is not installed "
                    "(run: pip install -r requirements.txt)")
    if not os.environ.get("FINWISE_DB_PASSWORD"):
        pytest.skip("FINWISE_DB_PASSWORD is not set - copy .env.example to "
                    ".env and fill in your MySQL password (see README)")
    try:
        server = db.get_server_connection()
    except Exception as exc:
        pytest.skip(f"Could not connect to MySQL ({exc}). Start the server "
                    "and check your .env configuration.")

    try:
        cur = server.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        server.commit()
        cur.close()
        load_database.ensure_database(server, TEST_DB)
        load_database.load_sql_files(server, SQL_FILES, verbose=False)
    finally:
        server.close()

    yield TEST_DB

    # Teardown: remove the throwaway database.
    try:
        server = db.get_server_connection()
        cur = server.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        server.commit()
        server.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Function-scoped connection with automatic cleanup.
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_conn(test_db_name):
    conn = db.get_connection(database=test_db_name)
    yield conn
    conn.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Small helpers used by the tests (plain functions, not fixtures).
# ---------------------------------------------------------------------------
def q(conn, sql: str, params: tuple = ()):
    """Fetch all rows as a list of dicts."""
    return db.fetch_all(conn, sql, params)


def q1(conn, sql: str, params: tuple = ()):
    """Fetch the first row as a dict (or None)."""
    return db.fetch_one(conn, sql, params)


def scalar(conn, sql: str, params: tuple = ()):
    """Fetch a single value (first column of the first row)."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()


def new_user(conn, tag: str = "user") -> int:
    """Insert a uniquely-named test user and return its id."""
    username = f"test_{tag}_{uuid.uuid4().hex[:10]}"
    return db.execute(
        conn,
        "INSERT INTO users (username, email, full_name) VALUES (%s, %s, %s)",
        (username, f"{username}@test.example", "Test User"),
    )


def new_portfolio(conn, user_id: int, name: str | None = None) -> int:
    """Insert a test portfolio (uniquely named) and return its id."""
    name = name or f"Test Portfolio {uuid.uuid4().hex[:8]}"
    return db.execute(
        conn,
        "INSERT INTO portfolios (user_id, portfolio_name) VALUES (%s, %s)",
        (user_id, name),
    )


def stock_id_by_ticker(conn, ticker: str) -> int:
    row = q1(conn, "SELECT stock_id FROM stocks WHERE ticker_symbol = %s",
             (ticker,))
    assert row is not None, f"seed should contain ticker {ticker}"
    return row["stock_id"]


def holding(conn, portfolio_id: int, stock_id: int):
    """Return the (portfolio, stock) holding row or None."""
    return q1(
        conn,
        "SELECT holding_id, quantity, average_cost_per_unit "
        "FROM holdings WHERE portfolio_id = %s AND stock_id = %s",
        (portfolio_id, stock_id),
    )
