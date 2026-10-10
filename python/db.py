"""FinWise database connection helpers - the Python side of the contract.

Security rules (see docs/database_contract.md):
  * Credentials are read from environment variables, optionally loaded from
    a `.env` file at the project root. NEVER hard-code credentials here or
    in any script; `.env` is gitignored and only `.env.example` is committed.
  * Every query in this module uses parameterized statements (%s
    placeholders), so user input is never spliced into SQL text.
  * All writes to holdings / transactions / portfolio_snapshots go through
    the stored procedures (sp_record_transaction, sp_create_snapshot).
    Application code must never modify those tables directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Union

# ---------------------------------------------------------------------------
# Optional dependencies: import failures are deferred until a connection is
# actually attempted, so this module can always be imported (tests collect,
# scripts print a friendly hint) even before `pip install -r requirements.txt`.
# ---------------------------------------------------------------------------
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:  # pragma: no cover
    mysql = None
    MySQLError = Exception  # type: ignore[assignment,misc]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    # Load the project's .env if present (does not override real env vars).
    load_dotenv(PROJECT_ROOT / ".env")

DEFAULTS = {
    "FINWISE_DB_HOST": "127.0.0.1",
    "FINWISE_DB_PORT": "3306",
    "FINWISE_DB_USER": "root",
    "FINWISE_DB_PASSWORD": "",
    "FINWISE_DB_NAME": "finwise",
    "FINWISE_TEST_DB_NAME": "finwise_test",
}


def _env(key: str) -> str:
    return os.environ.get(key, DEFAULTS[key])


def _missing_driver() -> None:
    if mysql is None:
        raise RuntimeError(
            "mysql-connector-python is not installed. "
            "Run: pip install -r requirements.txt"
        )


def require_password() -> str:
    """Return the configured MySQL password or fail with a clear message."""
    password = _env("FINWISE_DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "FINWISE_DB_PASSWORD is not set. Copy .env.example to .env and "
            "fill in your MySQL password (never commit the real .env)."
        )
    return password


def get_connection(database: Optional[str] = None, autocommit: bool = False):
    """Open a connection to the FinWise database.

    `database=None` selects FINWISE_DB_NAME (default: finwise). Pass an
    explicit name (e.g. the test database) to override.
    """
    _missing_driver()
    return mysql.connector.connect(
        host=_env("FINWISE_DB_HOST"),
        port=int(_env("FINWISE_DB_PORT")),
        user=_env("FINWISE_DB_USER"),
        password=require_password(),
        database=database if database is not None else _env("FINWISE_DB_NAME"),
        autocommit=autocommit,
    )


def get_server_connection():
    """Open a connection WITHOUT selecting a database (admin tasks only)."""
    _missing_driver()
    return mysql.connector.connect(
        host=_env("FINWISE_DB_HOST"),
        port=int(_env("FINWISE_DB_PORT")),
        user=_env("FINWISE_DB_USER"),
        password=require_password(),
        autocommit=False,
    )


# ---------------------------------------------------------------------------
# Parameterized query helpers
# ---------------------------------------------------------------------------
def fetch_all(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return all rows as dictionaries."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def fetch_one(conn, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    """Run a SELECT and return the first row (dict) or None."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def execute(conn, sql: str, params: tuple = ()) -> int:
    """Run an INSERT/UPDATE/DELETE with commit-on-success, rollback-on-error.

    Returns lastrowid (useful for AUTO_INCREMENT ids). Parameters are always
    bound - never build SQL by string formatting.
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except MySQLError:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Stored-procedure wrappers - the ONLY sanctioned write paths.
# These mirror the database contract (docs/database_contract.md).
# ---------------------------------------------------------------------------
def record_transaction(
    conn,
    portfolio_id: int,
    stock_id: int,
    transaction_type: str,
    quantity: Union[int, float],
    price_per_unit: Union[int, float],
    transaction_date: str,
    notes: Optional[str] = None,
) -> int:
    """Record a BUY/SELL through sp_record_transaction and return the new id.

    Atomic and validated server-side: rejected calls raise an error whose
    message comes straight from the procedure, and they leave no partial
    transaction row and no partial holding update.
    """
    cur = conn.cursor()
    try:
        cur.callproc(
            "sp_record_transaction",
            [portfolio_id, stock_id, transaction_type,
             quantity, price_per_unit, transaction_date, notes, 0],
        )
        # Retrieve the OUT parameter p_transaction_id (8th argument).
        cur.execute("SELECT @_sp_record_transaction_8")
        (transaction_id,) = cur.fetchone()
        conn.commit()
        return int(transaction_id)
    except MySQLError:
        conn.rollback()
        raise
    finally:
        cur.close()


def create_snapshot(
    conn,
    portfolio_id: int,
    snapshot_date: str,
) -> None:
    """Create (or refresh) a portfolio snapshot via sp_create_snapshot."""
    cur = conn.cursor()
    try:
        cur.callproc("sp_create_snapshot", [portfolio_id, snapshot_date])
        conn.commit()
    except MySQLError:
        conn.rollback()
        raise
    finally:
        cur.close()
