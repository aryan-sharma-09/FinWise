# FinWise MongoDB Module (Member 3)

A denormalized, **semi-structured read model** of the FinWise data, built and
queried with MongoDB. It complements the MySQL core that Member 1 owns; it
does not replace it.

> **Educational disclaimer.** Every stock, price, portfolio, transaction, and
> valuation in MongoDB is **synthetic, illustrative sample data** mirrored
> from the MySQL seed. It is **not live market data** and must never be
> presented as such.

---

## 1. Design principle: MySQL is the single source of truth

```
MySQL (source of truth)            MongoDB (read model)
  sql/01..04, procedures   --ETL-->  stock_fundamentals
  views (read API)                   portfolios  (embedded holdings[])
        |                            transactions
        |  read-only                 portfolio_snapshots
        +---------------------------->
```

- The ETL (`python/load_mongo.py`) **only SELECTs** from MySQL and **writes to
  MongoDB**. Nothing is ever written back into MySQL.
- Writes to `holdings` / `transactions` / `portfolio_snapshots` in MySQL still
  go exclusively through the stored procedures (see
  `docs/database_contract.md`). The MongoDB demo never touches MySQL.
- The read model is disposable: re-run `python python/load_mongo.py --yes` at
  any time to rebuild it from MySQL.

## 2. Collections

| Collection | Document shape (abridged) | Purpose |
|---|---|---|
| `stock_fundamentals` | `{_id: stock_id, ticker, company_name, sector:{name, description}, fundamentals:{price, market_cap_millions, pe_ratio, dividend_yield, price_as_of}, tags:[]}` | Semi-structured fundamentals; embedded `sector` sub-document and optional/null fields (e.g. no P/E for the loss-making stocks). |
| `portfolios` | `{_id: portfolio_id, portfolio_name, user:{user_id, username}, total_value, holdings:[{stock_id, ticker, sector, quantity, avg_cost, current_price, market_value, unrealized_pl, weight_percent}]}` | Denormalized positions: one document per portfolio with an embedded `holdings[]` array. |
| `transactions` | `{_id: transaction_id, portfolio_id, stock_id, ticker, transaction_type, quantity, price_per_unit, transaction_date, notes}` | Append-only BUY/SELL event log (mirrors the immutable MySQL log). |
| `portfolio_snapshots` | `{_id: snapshot_id, portfolio_id, snapshot_date, total_market_value, total_cost_basis, holdings_count}` | Point-in-time valuation records (time series). |

### Indexes

| Collection | Index |
|---|---|
| `stock_fundamentals` | `ticker` (unique) |
| `portfolios` | `user.user_id` |
| `transactions` | `(portfolio_id, transaction_date)`, `stock_id` |
| `portfolio_snapshots` | `(portfolio_id, snapshot_date)` |

### `_id` and idempotency

Every document uses a **deterministic `_id`** derived from the MySQL primary
key, so re-running the ETL replaces documents instead of duplicating them.
Documents whose MySQL row disappeared are pruned, so the mirror always matches
the source exactly.

## 3. CRUD operations (`python/mongo_db.py`)

A thin helper layer mirroring `python/db.py`:

| Helper | MongoDB operation |
|---|---|
| `insert_one` / `insert_many` | `insertOne` / `insertMany` |
| `find_all` / `find_one` | `find` (with `projection`, `sort`, `limit`) / `findOne` |
| `update_one` / `update_many` | `updateOne` / `updateMany` (`$set`, `$inc`, `$push`, `$pull`, `$addToSet`) |
| `upsert` | `replaceOne(..., upsert=True)` (idempotent write by key) |
| `delete_one` / `delete_many` | `deleteOne` / `deleteMany` |
| `count` / `distinct` / `aggregate` | `countDocuments` / `distinct` / `aggregate` |

The demo (`python/mongo_demo.py`) exercises all four CRUD letters plus an
idempotent upsert.

## 4. Aggregation pipelines (`python/mongo_demo.py`)

The five pipelines reproduce the MySQL analytics in `sql/05_analytics_queries.sql`
using MongoDB's aggregation framework. They are defined once and reused by the
demo, the health check, and the tests.

| # | Function | Stages | MySQL analogue |
|---|---|---|---|
| 1 | `pipeline_sector_allocation` | `$unwind` + `$lookup` + `$group` + `$sort` | `v_sector_allocation` |
| 2 | `pipeline_top_positions` | `$unwind` + `$setWindowFields` (`$rank`) + `$match` | query 12 (`RANK()`) |
| 3 | `pipeline_period_returns` | `$setWindowFields` (`$shift`) + `$addFields` | query 16 (`LAG()`), `v_portfolio_performance` |
| 4 | `pipeline_running_invested_capital` | `$match` + `$setWindowFields` (running `$sum`) | query 13 (`SUM() OVER`) |
| 5 | `pipeline_portfolio_dashboard` | `$group` + `$facet` + `$bucket` | query 14 (CTE + CASE) |

**Requirement:** `$setWindowFields` needs **MongoDB 5.0 or newer**. The health
check verifies this and reports a clear failure on older servers.

## 5. Setup

### 5.1 Install the driver

```bash
pip install -r requirements.txt      # adds pymongo>=4.6
```

### 5.2 Start MongoDB (local) **or** use Atlas

- **Local:** install MongoDB Community Server and start it. The default
  connection string is `mongodb://127.0.0.1:27017`.
- **Atlas:** create a free cluster and put its connection string in `.env`:

  ```dotenv
  FINWISE_MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/
  FINWISE_MONGO_DB=finwise
  FINWISE_MONGO_TEST_DB=finwise_test
  ```

Never commit `.env` (it is gitignored); only `.env.example` is committed.

### 5.3 Load the read model (after the MySQL database exists)

```bash
python python/load_database.py --yes    # ensure MySQL seed is present
python python/load_mongo.py --yes       # read-only ETL into MongoDB
python python/verify_mongo.py           # health check
python python/mongo_demo.py             # CRUD + aggregation demo
```

## 6. Tests

```bash
pytest tests/test_mongo_crud.py tests/test_mongo_pipelines.py
```

- Tests use a **throwaway MongoDB database** whose name must contain `"test"`
  (`FINWISE_MONGO_TEST_DB`, default `finwise_test`); it is dropped and rebuilt
  around every test. The demo database is never touched.
- If `pymongo` is not installed or MongoDB is unreachable, the MongoDB tests
  **skip with a clear reason** instead of failing - the same philosophy as the
  MySQL tests.
- The full ETL integration test additionally needs MySQL and skips when it is
  unavailable.

## 7. Files

| File | Role |
|---|---|
| `python/mongo_db.py` | Connection + CRUD helper layer |
| `python/load_mongo.py` | Read-only MySQL -> MongoDB ETL (idempotent) |
| `python/mongo_demo.py` | Interactive CRUD + aggregation demo |
| `python/verify_mongo.py` | Health check (PASS/FAIL) |
| `tests/test_mongo_crud.py` | Skip-safe CRUD tests |
| `tests/test_mongo_pipelines.py` | Skip-safe pipeline + ETL tests |

## 8. Out of scope

- No writes back into MySQL; no change to the SQL procedures, views, or the
  MySQL schema.
- No authentication, live market data, or trading logic (project-wide scope,
  see the README).
