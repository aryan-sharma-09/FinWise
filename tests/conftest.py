"""Shared pytest fixtures for the FinWise test suite.

The suite runs against a THROWAWAY database (default name `finwise_test`,
configurable via FINWISE_TEST_DB_NAME) that is created fresh from the SQL
scripts at the start of every session and dropped afterwards. Your demo
database is never touched.

Tests that assert the documented SEED SHAPE (row counts, seed invariants)
use the `pristine_db` fixture instead of `db_conn`: it rebuilds the
throwaway database from the SQL scripts first, so those assertions are
independent of test execution order (other tests commit their own setup
data through the procedures, by design).

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
import mongo_db  # noqa: E402

TEST_DB = os.environ.get("FINWISE_TEST_DB_NAME",
                         db.DEFAULTS["FINWISE_TEST_DB_NAME"])

if "test" not in TEST_DB.lower():
    raise pytest.UsageError(
        f"FINWISE_TEST_DB_NAME must contain the word 'test' (got {TEST_DB!r}). "
        "Refusing to run tests against a database that might hold real data."
    )

# The MongoDB read-model data model tests use their own throwaway database.
# The same safety rule applies: its name MUST contain "test".
MONGO_TEST_DB = os.environ.get("FINWISE_MONGO_TEST_DB",
                               mongo_db.DEFAULTS["FINWISE_MONGO_TEST_DB"])

if "test" not in MONGO_TEST_DB.lower():
    raise pytest.UsageError(
        f"FINWISE_MONGO_TEST_DB must contain the word 'test' (got "
        f"{MONGO_TEST_DB!r}). Refusing to drop a MongoDB database that might "
        "hold real data."
    )

SQL_FILES = [load_database.SQL_DIR / f for f in load_database.DEFAULT_FILES]


def _drop_test_db() -> None:
    """Remove the throwaway database if it exists (best effort)."""
    try:
        server = db.get_server_connection()
        cur = server.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        server.commit()
        server.close()
    except Exception:
        pass


def _drop_and_build_test_db() -> None:
    """(Re)create the throwaway database from the SQL scripts."""
    server = db.get_server_connection()
    try:
        cur = server.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        server.commit()
        cur.close()
        load_database.ensure_database(server, TEST_DB)
        load_database.load_sql_files(server, SQL_FILES, verbose=False)
    finally:
        server.close()


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
        db.get_server_connection().close()
    except Exception as exc:
        pytest.skip(f"Could not connect to MySQL ({exc}). Start the server "
                    "and check your .env configuration.")

    _drop_and_build_test_db()
    yield TEST_DB

    # Teardown: remove the throwaway database.
    _drop_test_db()


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
# Function-scoped PRISTINE database connection: for tests that assert the
# documented seed shape. The throwaway database is rebuilt from the SQL
# scripts first, so committed setup data from earlier tests cannot affect
# these assertions.
# ---------------------------------------------------------------------------
@pytest.fixture()
def pristine_db(test_db_name):
    _drop_and_build_test_db()
    conn = db.get_connection(database=TEST_DB)
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


# ---------------------------------------------------------------------------
# MongoDB fixtures (Member 3). They follow the same philosophy as the MySQL
# fixtures above: use a throwaway database whose name contains "test", and
# SKIP cleanly (never fail) when pymongo or the server is unavailable.
# ---------------------------------------------------------------------------
def _mongo_skip_reason():
    """Return a human-readable reason to skip, or None when Mongo is usable."""
    if mongo_db.pymongo is None:
        return ("pymongo is not installed "
                "(run: pip install -r requirements.txt)")
    if not mongo_db.server_available():
        return ("MongoDB is not reachable. Start MongoDB or set "
                "FINWISE_MONGO_URI in .env (see docs/mongodb_module.md).")
    return None


@pytest.fixture(scope="session")
def mongo_client():
    """Session-scoped client to the throwaway MongoDB test database."""
    reason = _mongo_skip_reason()
    if reason:
        pytest.skip(reason)
    client = mongo_db.get_client()
    yield client
    try:
        client.drop_database(MONGO_TEST_DB)
    finally:
        client.close()


@pytest.fixture()
def mongo_db_conn(mongo_client):
    """Function-scoped, EMPTY throwaway MongoDB database.

    Dropped before and after each test, so MongoDB tests are independent of
    one another and can never leak into the read model of the demo database.
    """
    mongo_client.drop_database(MONGO_TEST_DB)
    database = mongo_client[MONGO_TEST_DB]
    yield database
    mongo_client.drop_database(MONGO_TEST_DB)
