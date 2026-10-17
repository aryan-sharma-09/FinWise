# MongoDB module (Person 3 - MongoDB and Data Engineering)

A small, beginner-friendly **document database** component for FinWise. It
keeps a **read model** of the project's data in MongoDB so we can demonstrate
document CRUD and simple aggregation queries alongside the relational work.

> **Educational disclaimer.** Every stock, price, portfolio, transaction, and
> valuation here is **synthetic sample data**. This is a college project, not
> a real trading system, and nothing here is financial advice.

## Why MongoDB next to MySQL?

MySQL (Member 1's seven tables) is the **single source of truth**: it holds
the constraints, the stored procedures, and the audit trail. MongoDB does not
replace any of that. It is a place to practise a *second* data model, and it
is rebuilt from MySQL whenever we want.

```
MySQL  (source of truth)             MongoDB  (read model)
  7 tables, views, procedures  --ETL-->  stock_fundamentals
  read-only                    <--      portfolios
                                         transactions
                                         portfolio_snapshots
```

The ETL script only **reads** MySQL and only **writes** MongoDB. Nothing is
ever written back, so MySQL cannot be corrupted by this module.

## Files

| File | Purpose |
| --- | --- |
| `python/mongo_db.py` | Connection + small CRUD helpers over PyMongo. |
| `python/load_mongo.py` | The ETL: reads MySQL, writes the MongoDB read model. |
| `python/mongo_demo.py` | A few read-only queries plus a small CRUD demo. |
| `tests/test_mongo_basic.py` | Basic CRUD + aggregation tests (skip if no server). |
| `docs/mongodb_module.md` | This document. |

## Collections and fields

Four collections, each a **flat** document per MySQL row (`_id` reuses the
MySQL primary key, so re-running the ETL replaces documents instead of
duplicating them):

| Collection | Fields |
| --- | --- |
| `stock_fundamentals` | `_id`, `ticker`, `company_name`, `sector`, `price`, `market_cap_millions`, `pe_ratio`, `dividend_yield`, `price_as_of` |
| `portfolios` | `_id`, `portfolio_name`, `user_id`, `username`, `owner_full_name` |
| `transactions` | `_id`, `portfolio_id`, `ticker`, `transaction_type`, `quantity`, `price_per_unit`, `transaction_date`, `notes` |
| `portfolio_snapshots` | `_id`, `portfolio_id`, `snapshot_date`, `total_market_value`, `total_cost_basis`, `holdings_count` |

A couple of deliberate simplifications to keep the code easy to read:

- MySQL `DECIMAL` values are converted to `float` in MongoDB (`to_float`).
- `DATE` columns such as `price_as_of` are stored as `"YYYY-MM-DD"` strings
  (`to_text`), because PyMongo cannot store a `datetime.date` directly.

## Setup and run

1. Install dependencies (adds PyMongo):

   ```bash
   pip install -r requirements.txt
   ```

2. Make sure the FinWise MySQL database is loaded and a MongoDB server is
   running locally (`mongod`, listening on `127.0.0.1:27017` by default).
   Check with: `mongosh --eval "db.runCommand({ping:1})"`.

3. Build the read model, then explore it:

   ```bash
   python python/load_mongo.py --yes   # MySQL -> MongoDB
   python python/mongo_demo.py         # read-only queries + CRUD demo
   ```

## Configuration

Optional - sensible defaults are built in. Override them in `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FINWISE_MONGO_URI` | `mongodb://127.0.0.1:27017` | Server to connect to. |
| `FINWISE_MONGO_DB` | `finwise_mongo` | Database the ETL writes and the demo reads. |
| `FINWISE_MONGO_TIMEOUT_MS` | `2000` | How long to wait for the server. |
| `FINWISE_MONGO_TEST_DB` | `finwise_test_mongo` | Throwaway database used by the tests. |

Reads of MySQL use the existing `FINWISE_DB_*` settings from `python/db.py`.

## Tests

```bash
pytest tests/test_mongo_basic.py
```

As elsewhere in the suite, these **skip** (not fail) when pymongo is missing
or MongoDB is unreachable. The throwaway test database name must contain the
word `test`; `mongo_db.require_test_db_name` refuses anything else.
