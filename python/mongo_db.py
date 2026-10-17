"""FinWise MongoDB helpers - the Python side of the MongoDB read model.

MySQL (Member 1's schema) is the single source of truth. This module only
knows how to talk to MongoDB; the ETL script `load_mongo.py` is what copies
data from MySQL into these collections.

Rules (mirroring python/db.py):
  * Connection settings come from environment variables, optionally loaded
    from the project's `.env` file. Never hard-code them.
  * pymongo is imported lazily, so this module always imports cleanly - even
    before `pip install -r requirements.txt` has been run.
  * Every MongoDB action goes through a small named helper.

All data is synthetic sample data: this is a college project, not a real
trading system, and nothing here is financial advice.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Optional dependency: a missing pymongo must not stop this module (or the
# test suite) from being imported. We raise only when a connection is needed.
# ---------------------------------------------------------------------------
try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    # Load the project's .env if present (does not override real env vars).
    load_dotenv(PROJECT_ROOT / ".env")

DEFAULTS = {
    "FINWISE_MONGO_URI": "mongodb://127.0.0.1:27017",
    "FINWISE_MONGO_DB": "finwise_mongo",
    "FINWISE_MONGO_TEST_DB": "finwise_test_mongo",
    "FINWISE_MONGO_TIMEOUT_MS": "2000",
}

# The four read-model collections, in the order the ETL fills them.
COLLECTIONS = (
    "stock_fundamentals",
    "portfolios",
    "transactions",
    "portfolio_snapshots",
)


def _env(key: str) -> str:
    return os.environ.get(key, DEFAULTS[key])


def _missing_driver() -> None:
    if MongoClient is None:
        raise RuntimeError(
            "pymongo is not installed. Run: pip install -r requirements.txt"
        )


def require_test_db_name(name: str) -> str:
    """Return `name` only if it looks like a throwaway test database.

    The tests use this so a typo can never point a destructive call at the
    real read-model database.
    """
    if "test" not in name.lower():
        raise ValueError(
            f"Refusing to treat {name!r} as a test database: the name must "
            "contain the word 'test'."
        )
    return name


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------
def get_client(uri: Optional[str] = None, timeout_ms: Optional[int] = None):
    """Create a MongoClient.

    PyMongo connects lazily, so this rarely fails here; the first command we
    run is what actually proves the server is up (see server_available).
    """
    _missing_driver()
    if timeout_ms is None:
        timeout_ms = int(_env("FINWISE_MONGO_TIMEOUT_MS"))
    return MongoClient(
        uri or _env("FINWISE_MONGO_URI"),
        serverSelectionTimeoutMS=timeout_ms,
    )


def get_database(name: Optional[str] = None, client=None):
    """Return a database handle (default: FINWISE_MONGO_DB)."""
    if client is None:
        client = get_client()
    return client[name if name is not None else _env("FINWISE_MONGO_DB")]


def get_collection(name: str, database: Optional[str] = None, client=None):
    """Return a collection handle from the chosen database."""
    return get_database(database, client)[name]


def server_available(uri: Optional[str] = None) -> bool:
    """True if a MongoDB server answers a ping before the timeout."""
    if MongoClient is None:
        return False
    client = None
    try:
        client = get_client(uri)
        client.admin.command("ping")
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            client.close()


# ---------------------------------------------------------------------------
# Small CRUD helpers. Each one is a one-liner on purpose: read the PyMongo
# docs, then read the helper, and the mapping is obvious.
# ---------------------------------------------------------------------------
def insert_one(collection, document: dict) -> Any:
    """Insert a single document and return its new _id."""
    return collection.insert_one(document).inserted_id


def insert_many(collection, documents: list[dict]) -> list:
    """Insert several documents and return their new _ids."""
    return collection.insert_many(list(documents)).inserted_ids


def find_all(collection, query: Optional[dict] = None,
             limit: int = 0) -> list[dict]:
    """Return matching documents as a list (limit=0 means "no limit")."""
    cursor = collection.find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_one(collection, query: dict) -> Optional[dict]:
    """Return the first document matching `query`, or None."""
    return collection.find_one(query)


def count(collection, query: Optional[dict] = None) -> int:
    """Count documents matching `query` (or all documents if omitted)."""
    return collection.count_documents(query or {})


def update_one(collection, query: dict, new_values: dict):
    """Set the given fields on the first matching document.

    `new_values` is a plain dict of field -> value, e.g. {"price": 410.25};
    we wrap it in a $set for you.
    """
    return collection.update_one(query, {"$set": new_values})


def delete_one(collection, query: dict):
    """Delete the first document matching `query`."""
    return collection.delete_one(query)


def delete_many(collection, query: dict):
    """Delete every document matching `query`."""
    return collection.delete_many(query)


def aggregate(collection, pipeline: list[dict]) -> list[dict]:
    """Run an aggregation pipeline and return the result rows."""
    return list(collection.aggregate(list(pipeline)))
