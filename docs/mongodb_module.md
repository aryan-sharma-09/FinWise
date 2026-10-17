# MongoDB module (Person 3 - MongoDB and Data Engineering)

A small, beginner-friendly **document database** component for FinWise. It
keeps a copy of the project's data in MongoDB so we can show document
queries, one aggregation, and CRUD alongside the relational work.

> **Educational disclaimer.** Every stock, price, portfolio, transaction, and
> valuation here is **synthetic sample data**. This is a college project, not
> a real trading system, and nothing here is financial advice.

## The two parts

Person 3's work lives in two sibling folders:

| Folder | Part | What it does |
| --- | --- | --- |
| `mongodb/` | MongoDB | Connection helper + a read-only tour of the collections. |
| `etl/` | Data engineering | Copies the data out of MySQL into MongoDB. |

## Why MongoDB next to MySQL?

MySQL (Member 1's seven tables) is the **single source of truth**: it holds
the constraints, the stored procedures, and the audit trail. MongoDB does not
replace any of that. It is a second data model to practise with, and it is
filled from MySQL whenever we want.

```
MySQL  (source of truth)            MongoDB  (the collections)
  7 tables, views, procedures  --ETL-->  stock_fundamentals
  read-only                    <--       portfolios
                                         transactions
                                         portfolio_snapshots
```

The ETL only **reads** MySQL and only **writes** MongoDB. Nothing is ever
written back, so this module cannot corrupt MySQL.

## Files

| File | Purpose |
| --- | --- |
| `mongodb/mongo_db.py` | Connection helper: reads the settings, returns a MongoDB database. |
| `mongodb/mongo_demo.py` | Read-only find queries, one aggregation, and a CRUD demo. |
| `etl/load_mongo.py` | The ETL: reads MySQL, writes the MongoDB collections. |
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
   Check it with: `mongosh --eval "db.runCommand({ping:1})"`.

3. Build the collections, then explore them:

   ```bash
   python etl/load_mongo.py       # MySQL -> MongoDB
   python mongodb/mongo_demo.py   # read-only queries + CRUD demo
   ```

## Configuration

Optional - sensible defaults are built in. Override them in `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FINWISE_MONGO_URI` | `mongodb://127.0.0.1:27017` | Server to connect to. |
| `FINWISE_MONGO_DB` | `finwise_mongo` | Database the ETL writes and the demo reads. |
| `FINWISE_MONGO_TEST_DB` | `finwise_test_mongo` | Throwaway database used by the tests. |

Reads of MySQL use the existing `FINWISE_DB_*` settings from `python/db.py`.

## Tests

```bash
pytest tests/test_mongo_basic.py
```

As elsewhere in the suite, these **skip** (not fail) when pymongo is missing
or MongoDB is unreachable. The throwaway test database name must contain the
word `test`; `mongo_db.require_test_db_name` refuses anything else.
