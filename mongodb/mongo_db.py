"""FinWise MongoDB connection helper - the MongoDB side of the project.

MySQL (Member 1's schema) is the single source of truth for FinWise. This
module is the MongoDB side of the project: it only knows how to connect to
the server. etl/load_mongo.py fills the collections from MySQL, and
mongodb/mongo_demo.py reads them.

Connection settings come from environment variables, optionally read from
the project's .env file (see .env.example). Never hard-code them here.

All data is synthetic sample data - not real financial information.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read the project's .env file if there is one. This does NOT override real
# environment variables, so a value set on the command line still wins.
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DEFAULTS = {
    "FINWISE_MONGO_URI": "mongodb://127.0.0.1:27017",
    "FINWISE_MONGO_DB": "finwise_mongo",
    "FINWISE_MONGO_TEST_DB": "finwise_test_mongo",
}

# The four collections used by the demo and the tests.
COLLECTIONS = (
    "stock_fundamentals",
    "portfolios",
    "transactions",
    "portfolio_snapshots",
)


def setting(name):
    """Return one setting from the environment, or its built-in default."""
    return os.environ.get(name, DEFAULTS[name])


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------
def get_client():
    """Create a connection to the MongoDB server."""
    return MongoClient(
        setting("FINWISE_MONGO_URI"),
        serverSelectionTimeoutMS=2000,
    )


def get_database(name=None, client=None):
    """Return a MongoDB database handle (default: FINWISE_MONGO_DB)."""
    if client is None:
        client = get_client()
    if name is None:
        name = setting("FINWISE_MONGO_DB")
    return client[name]


def server_available():
    """Return True if a MongoDB server answers a quick ping."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False


def require_test_db_name(name):
    """Return the name only if it contains the word "test".

    The tests call this so a typo can never point a destructive call at the
    real read-model database.
    """
    if "test" not in name.lower():
        raise ValueError(
            "Refusing to use '" + name + "' as a test database: the name "
            "must contain the word 'test'."
        )
    return name
