"""FinWise MongoDB connection + CRUD helpers - the NoSQL side of the project.

This module is the MongoDB counterpart of ``python/db.py`` and follows the
same rules:

  * Connection settings are read from environment variables, optionally
    loaded from a ``.env`` file at the project root. NEVER hard-code a URI
    or credentials here or in any script; ``.env`` is gitignored and only
    ``.env.example`` is committed.

  * The MongoDB collections are a READ MODEL populated from MySQL by
    ``python/load_mongo.py`` (read-only ETL). Nothing in this module ever
    writes back into MySQL: MySQL remains the single source of truth for
    holdings / transactions / snapshots (see docs/database_contract.md).

  * All data is synthetic and illustrative. It is not live market data and
    must never be presented as such (see the README disclaimer).

Collections (see docs/mongodb_module.md):
    stock_fundamentals   - one document per stock, with embedded sector and
                           fundamentals sub-documents (semi-structured data)
    portfolios           - one document per portfolio with a holdings[] array
    transactions         - append-only BUY/SELL event log
    portfolio_snapshots  - point-in-time valuation records (time series)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Optional dependency: import failures are deferred until a connection is
# actually attempted, exactly like python/db.py, so this module can always be
# imported (tests collect, scripts print a friendly hint) even before
# `pip install -r requirements.txt`.
# ---------------------------------------------------------------------------
try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover
    pymongo = None
    MongoClient = None  # type: ignore[assignment]
    PyMongoError = Exception  # type: ignore[assignment,misc]

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
    "FINWISE_MONGO_DB": "finwise",
    "FINWISE_MONGO_TEST_DB": "finwise_test",
}

# Short timeout so a missing server fails fast (and tests skip quickly)
# instead of hanging for the driver's 30-second default.
SERVER_SELECTION_TIMEOUT_MS = 2000

# The collections owned by the read model (populated by load_mongo.py). An
# ordinary aggregation here is the MongoDB analogue of a SQL view.
COLLECTIONS = (
    "stock_fundamentals",
    "portfolios",
    "transactions",
    "portfolio_snapshots",
)

# MongoDB feature builds required by this module:
#   * $setWindowFields  -> MongoDB 5.0+
#   * $lookup/$facet/$bucket -> MongoDB 3.6+/4.4
MIN_SERVER_VERSION = (5, 0, 0)


def _env(key: str) -> str:
    return os.environ.get(key, DEFAULTS[key])


def _missing_driver() -> None:
    if pymongo is None:
        raise RuntimeError(
            "pymongo is not installed. Run: pip install -r requirements.txt"
        )


def require_test_db_name(name: str) -> str:
    """Return ``name`` if it is safe to use as a throwaway test database.

    Mirrors the MySQL safety guard in tests/conftest.py: a destructive test
    database must contain the word "test", so an accidental configuration
    cannot drop real data.
    """
    if "test" not in name.lower():
        raise ValueError(
            f"Refusing to use MongoDB database {name!r} for tests: the name "
            "must contain the word 'test'."
        )
    return name


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
def get_client(
    uri: Optional[str] = None,
    timeout_ms: int = SERVER_SELECTION_TIMEOUT_MS,
):
    """Return a MongoClient (server is NOT contacted until first use)."""
    _missing_driver()
    return MongoClient(
        uri or _env("FINWISE_MONGO_URI"),
        serverSelectionTimeoutMS=timeout_ms,
    )


def get_database(database: Optional[str] = None, client=None):
    """Return a database handle.

    ``database=None`` selects FINWISE_MONGO_DB (default: finwise). Pass an
    explicit name (e.g. the test database) to override.
    """
    client = client or get_client()
    return client[database if database is not None else _env("FINWISE_MONGO_DB")]


def get_collection(name: str, database: Optional[str] = None, client=None):
    """Return a collection handle from the selected database."""
    return get_database(database=database, client=client)[name]


def server_available(uri: Optional[str] = None) -> bool:
    """Return True if a MongoDB server answers a ping, else False.

    Never raises: used by the health check and the tests to decide whether
    to run or skip.
    """
    if pymongo is None:
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


def server_version(client=None) -> Optional[str]:
    """Return the server version string, or None when unreachable."""
    if pymongo is None:
        return None
    own = client is None
    client = client or get_client()
    try:
        info = client.server_info()
        return str(info.get("version", "")) or None
    except Exception:
        return None
    finally:
        if own:
            client.close()


def version_at_least(version: Optional[str], minimum=MIN_SERVER_VERSION) -> bool:
    """True if ``version`` (e.g. '7.0.5') is >= ``minimum`` tuple."""
    if not version:
        return False
    try:
        parts = tuple(int(p) for p in version.split(".")[:3])
    except ValueError:
        return False
    return parts >= tuple(minimum)


# ---------------------------------------------------------------------------
# CRUD helpers - parameterized by a collection handle.
#
# All helpers take a collection object (from get_collection) rather than a
# connection, mirroring how python/db.py separates "get a connection" from
# the query helpers. Documents are plain dicts; every operation is scoped to
# the MongoDB read model and never touches MySQL.
# ---------------------------------------------------------------------------
def insert_one(collection, document: dict) -> Any:
    """Insert a single document and return its _id."""
    return collection.insert_one(document).inserted_id


def insert_many(collection, documents: Sequence[dict]) -> list:
    """Insert many documents and return their _ids (order preserved)."""
    if not documents:
        return []
    return list(collection.insert_many(list(documents)).inserted_ids)


def find_all(
    collection,
    query: Optional[dict] = None,
    projection: Optional[dict] = None,
    sort: Optional[list] = None,
    limit: int = 0,
) -> list[dict]:
    """Return matching documents as a list (find)."""
    cursor = collection.find(query or {}, projection)
    if sort:
        cursor = cursor.sort(sort)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def find_one(
    collection,
    query: Optional[dict] = None,
    projection: Optional[dict] = None,
) -> Optional[dict]:
    """Return the first matching document or None."""
    return collection.find_one(query or {}, projection)


def count(collection, query: Optional[dict] = None) -> int:
    """Return the number of documents matching ``query``."""
    return int(collection.count_documents(query or {}))


def update_one(collection, query: dict, update: dict, upsert: bool = False):
    """Update the first matching document (e.g. {"$set": {...}})."""
    return collection.update_one(query, update, upsert=upsert)


def update_many(collection, query: dict, update: dict, upsert: bool = False):
    """Update every matching document ((e.g. {"$inc": {...}})."""
    return collection.update_many(query, update, upsert=upsert)


def upsert(collection, query: dict, document: dict):
    """Replace-or-insert one document (idempotent write by natural key)."""
    return collection.replace_one(query, document, upsert=True)


def delete_one(collection, query: dict):
    """Delete the first matching document."""
    return collection.delete_one(query)


def delete_many(collection, query: dict):
    """Delete every matching document."""
    return collection.delete_many(query)


def distinct(collection, field: str, query: Optional[dict] = None) -> list:
    """Return the distinct values of ``field`` (filtered by ``query``)."""
    return list(collection.distinct(field, query or {}))


def aggregate(collection, pipeline: Iterable[dict]) -> list[dict]:
    """Run an aggregation pipeline and return the result documents."""
    return list(collection.aggregate(list(pipeline)))
