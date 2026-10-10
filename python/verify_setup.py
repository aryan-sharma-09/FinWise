#!/usr/bin/env python3
"""Installation health check for FinWise.

Verifies, in order:
  1. The MySQL server version is 8.0.16+ (CHECK constraints are required).
  2. All seven tables exist and contain the expected seed row counts.
  3. All five contract views are queryable.
  4. v_holdings_reconciliation is empty (holdings match the transaction log).

Exit code 0 = passed, 1 = problems found. Run after loading the database:

  python python/verify_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402

EXPECTED_COUNTS = {
    "users": 6,
    "portfolios": 7,
    "sectors": 8,
    "stocks": 26,
    "holdings": 38,
    "transactions": 48,
    "portfolio_snapshots": 52,
}

VIEWS = [
    "v_portfolio_positions",
    "v_sector_allocation",
    "v_user_summary",
    "v_portfolio_performance",
    "v_holdings_reconciliation",
]

problems: list[str] = []


def ok(message: str) -> None:
    print(f"  [OK]   {message}")


def fail(message: str) -> None:
    print(f"  [FAIL] {message}")
    problems.append(message)


def check_version(conn) -> None:
    (version,) = db.fetch_one(conn, "SELECT VERSION()").values()
    print(f"\n1. MySQL server version: {version}")
    try:
        major, minor, patch = (int(x) for x in version.split(".")[:3])
    except ValueError:
        fail("Could not parse the server version string.")
        return
    if (major, minor, patch) >= (8, 0, 16):
        ok(f"Version {version} supports CHECK constraints (8.0.16+).")
    else:
        fail(f"MySQL {version} is too old - FinWise requires 8.0.16+.")


def check_tables(conn) -> None:
    print("\n2. Table row counts (expected seed values):")
    for table, expected in EXPECTED_COUNTS.items():
        row = db.fetch_one(conn, f"SELECT COUNT(*) AS n FROM {table}")
        count = row["n"]
        if count == expected:
            ok(f"{table:<20} {count:>4} rows")
        else:
            fail(f"{table}: found {count} rows, expected {expected} "
                 "(did you load 04_seed_data.sql?)")


def check_views(conn) -> None:
    print("\n3. Contract views:")
    for view in VIEWS:
        try:
            db.fetch_one(conn, f"SELECT COUNT(*) AS n FROM {view}")
            ok(f"{view} is queryable")
        except Exception as exc:
            fail(f"{view} is missing or broken: {exc}")


def check_reconciliation(conn) -> None:
    print("\n4. Holdings <-> transactions reconciliation:")
    row = db.fetch_one(conn,
                       "SELECT COUNT(*) AS n FROM v_holdings_reconciliation")
    if row["n"] == 0:
        ok("v_holdings_reconciliation is empty - holdings match the "
           "transaction log exactly.")
    else:
        fail(f"v_holdings_reconciliation returned {row['n']} row(s) - "
             "holdings and transactions are out of sync!")


def main() -> int:
    print("=" * 62)
    print("FinWise setup verification")
    print("=" * 62)
    try:
        conn = db.get_connection()
    except Exception as exc:
        print(f"Could not connect to MySQL: {exc}")
        print("Hint: start the server and configure .env (see README).")
        return 1

    try:
        check_version(conn)
        check_tables(conn)
        check_views(conn)
        check_reconciliation(conn)
    finally:
        conn.close()

    print("\n" + "=" * 62)
    if problems:
        print(f"SETUP VERIFICATION FAILED with {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("SETUP VERIFICATION PASSED - the FinWise database is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
