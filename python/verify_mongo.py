#!/usr/bin/env python3
"""Health check for the FinWise MongoDB read model.

Verifies, in order:
  1. pymongo is installed, the server is reachable, and its version supports
     the aggregation stages this module uses ($setWindowFields -> MongoDB 5.0+).
  2. All four collections exist and contain the expected seed row counts
     (mirrors python/verify_setup.py).
  3. All five aggregation pipelines evaluate without error.
  4. The expected indexes exist.

Exit code 0 = passed, 1 = problems found. Run after the ETL:

  python python/load_mongo.py --yes
  python python/verify_mongo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mongo_db  # noqa: E402
import mongo_demo  # noqa: E402  (the five pipelines live here)

# Expected document counts after a clean ETL from the documented seed.
EXPECTED_COUNTS = {
    "stock_fundamentals": 26,
    "portfolios": 7,
    "transactions": 48,
    "portfolio_snapshots": 52,
}

# (collection, index key-list) pairs the read model relies on.
EXPECTED_INDEXES = {
    "stock_fundamentals": [[("ticker", 1)]],
    "portfolios": [[("user.user_id", 1)]],
    "transactions": [
        [("portfolio_id", 1), ("transaction_date", 1)],
        [("stock_id", 1)],
    ],
    "portfolio_snapshots": [[("portfolio_id", 1), ("snapshot_date", 1)]],
}

problems: list[str] = []


def ok(message: str) -> None:
    print(f"  [OK]   {message}")


def fail(message: str) -> None:
    print(f"  [FAIL] {message}")
    problems.append(message)


def check_connection(client) -> None:
    print("\n1. MongoDB server")
    version = mongo_db.server_version(client)
    if not version:
        fail("Could not read the server version (is MongoDB running?).")
        return
    print(f"   Server version: {version}")
    if mongo_db.version_at_least(version):
        ok(f"Version {version} supports $setWindowFields (5.0+).")
    else:
        fail(f"MongoDB {version} is too old - this module needs 5.0+ "
             "for $setWindowFields.")


def check_collections(database) -> dict:
    print("\n2. Collection document counts (expected seed values):")
    present = {}
    names = set(database.list_collection_names())
    for name, expected in EXPECTED_COUNTS.items():
        if name not in names:
            fail(f"{name}: collection is missing (run python/load_mongo.py)")
            continue
        count = mongo_db.count(database[name])
        present[name] = count
        if count == expected:
            ok(f"{name:<22} {count:>4} documents")
        else:
            fail(f"{name}: found {count} documents, expected {expected} "
                 "(re-run python/load_mongo.py)")
    return present


def check_pipelines(database) -> None:
    print("\n3. Aggregation pipelines (each must evaluate):")
    probes = {
        "sector allocation":
            lambda: mongo_demo.pipeline_sector_allocation(database),
        "top positions":
            lambda: mongo_demo.pipeline_top_positions(database, 3),
        "period returns":
            lambda: mongo_demo.pipeline_period_returns(database),
        "running capital":
            lambda: mongo_demo.pipeline_running_invested_capital(database),
        "portfolio dashboard":
            lambda: mongo_demo.pipeline_portfolio_dashboard(database),
    }
    for label, run in probes.items():
        try:
            result = run()
            ok(f"{label} evaluated ({_size(result)} result row(s))")
        except Exception as exc:
            fail(f"{label} is broken: {exc}")


def _size(result) -> int:
    if isinstance(result, dict):
        return sum(len(v) if isinstance(v, list) else 1
                   for v in result.values())
    return len(result)


def check_indexes(database) -> None:
    print("\n4. Indexes:")
    for name, expected_keys in EXPECTED_INDEXES.items():
        try:
            info = database[name].index_information()
        except Exception as exc:
            fail(f"{name}: could not read index information: {exc}")
            continue
        existing = [spec["key"] for spec in info.values()]
        for keys in expected_keys:
            if list(keys) in existing:
                ok(f"{name}: index on {keys}")
            else:
                fail(f"{name}: missing index on {keys} "
                     "(re-run python/load_mongo.py)")


def main() -> int:
    print("=" * 62)
    print("FinWise MongoDB setup verification")
    print("=" * 62)

    if mongo_db.pymongo is None:
        print("\nFAILED: pymongo is not installed. "
              "Run: pip install -r requirements.txt")
        return 1
    if not mongo_db.server_available():
        print(f"\nFAILED: could not reach MongoDB at "
              f"{mongo_db.DEFAULTS['FINWISE_MONGO_URI']}.")
        print("Start MongoDB (or set FINWISE_MONGO_URI in .env), then run")
        print("python python/load_mongo.py --yes. See docs/mongodb_module.md.")
        return 1

    client = mongo_db.get_client()
    try:
        database = client[mongo_db.DEFAULTS["FINWISE_MONGO_DB"]]
        check_connection(client)
        check_collections(database)
        check_pipelines(database)
        check_indexes(database)
    finally:
        client.close()

    print("\n" + "=" * 62)
    if problems:
        print(f"MONGO SETUP VERIFICATION FAILED with {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("MONGO SETUP VERIFICATION PASSED - the read model is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
