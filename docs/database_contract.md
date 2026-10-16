# FinWise Database Contract — **DRAFT, v0.1**

> **STATUS: DRAFT — REQUIRES TEAM REVIEW.**
> Members 2, 3, and 4 have not yet finalized their component scopes, so
> this contract is a *proposal* from Member 1, not a frozen agreement.
> Please review the views, procedure signatures, and rules below with your
> component in mind and reply with additions or changes **before** you
> build against them. Signatures will only be treated as frozen once the
> team signs off on this document.

**Audience:** Members 2, 3, and 4 (application components).
**Author:** Member 1 (SQL database and portfolio management).
**Schema reference:** `docs/data_dictionary.md`; ER: `docs/er_diagram.mmd`.

---

## 1. What this contract gives you

A stable API on top of the FinWise database:

- **Read API** — five views (§3). Query them instead of hand-joining base
  tables; they are maintained and tested by Member 1.
- **Write API** — three stored procedures (§4). They are the *only*
  sanctioned way to mutate holdings, transactions, or snapshots.
- **Python helpers** — `python/db.py` wraps the procedures
  (`db.record_transaction`, `db.create_snapshot`) and offers parameterized
  `fetch_all / fetch_one / execute` so you never need to write SQL by string
  formatting.

**Guarantee:** as long as your code reads through the views and writes
through the procedures, the underlying schema can be tuned or extended
without breaking your components.

## 2. Ground rules (please follow these exactly)

1. **Never** `INSERT` / `UPDATE` / `DELETE` on `holdings`, `transactions`,
   or `portfolio_snapshots` from application code. Not even "just this
   once". `v_holdings_reconciliation` and the test suite will catch it, and
   it breaks the audit-trail guarantee the project is graded on.
2. **Never** mutate existing transaction rows. History is immutable. If a
   trade was entered wrongly, record a correcting SELL (or BUY) — the same
   way real brokerages work.
3. **Reads:** use the views where one exists (§3). For anything custom,
   plain parameterized SELECTs against base tables are fine.
4. **Writes to `users` / `portfolios` / `stocks` / `sectors`:** normal
   parameterized SQL is fine (these are simple CRUD tables). Keep
   referential integrity in mind — e.g. a stock's `sector_id` must exist.
5. **Credentials:** load them via `python/db.py` (`.env` / environment
   variables). Never hard-code a password, and never commit `.env`.
6. **Timestamps:** treat stored datetimes as **UTC** and convert for
   display only, so macOS and Windows teammates agree on dates.
7. **Data is illustrative.** Anything user-facing that shows prices or
   valuations should carry the project's educational disclaimer.

## 3. Read API — views

### `v_portfolio_positions`
One row per current holding.

| Column | Meaning |
|---|---|
| `holding_id`, `portfolio_id`, `portfolio_name`, `user_id`, `username` | Ownership |
| `stock_id`, `ticker_symbol`, `company_name`, `sector_name` | Instrument |
| `quantity`, `average_cost_per_unit`, `current_price` | Raw state |
| `cost_basis` | `quantity × average_cost_per_unit` |
| `market_value` | `quantity × current_price` |
| `unrealized_pl` | `market_value − cost_basis` |
| `pl_percent` | percent gain/loss vs cost (NULL-safe) |
| `portfolio_total_value` | portfolio's total market value (repeated per row) |
| `portfolio_weight_percent` | position weight inside its portfolio |

`cost_basis` is presented rounded to two decimal places (cents); the
underlying `average_cost_per_unit` is stored with six-decimal precision, so a
client-side recomputation of `quantity × average_cost_per_unit` may differ by
a fraction of a cent.

Typical use: position tables, "top holdings", gain/loss screens.

### `v_sector_allocation`
One row per (portfolio, sector) — even sectors with zero holdings in that
portfolio are simply absent (weights only cover held sectors).

| Column | Meaning |
|---|---|
| `portfolio_id`, `portfolio_name`, `user_id` | Ownership |
| `sector_name`, `sector_value` | Money in that sector |
| `portfolio_total_value` | Portfolio total |
| `sector_weight_percent` | Sector weight (should sum to ~100 per portfolio) |

Typical use: diversification charts, concentration alerts.

### `v_user_summary`
One row per user — **including users with no portfolios** (zeros), so
LEFT JOIN behavior is already handled for you.

| Column | Meaning |
|---|---|
| `user_id`, `username`, `email` | Identity |
| `portfolio_count`, `position_count` | Counts |
| `total_market_value`, `total_cost_basis`, `total_unrealized_pl` | Totals |

### `v_portfolio_performance`
One row per snapshot, ordered analysis-ready.

| Column | Meaning |
|---|---|
| `snapshot_id`, `portfolio_id`, `portfolio_name`, `user_id`, `snapshot_date` | Keys |
| `holdings_count`, `total_cost_basis`, `total_market_value` | Snapshot state |
| `previous_market_value` | Previous snapshot's value (NULL for the first) |
| `change_value`, `change_percent` | Period-over-period change |

Typical use: performance line charts, risk metrics (e.g. period returns
for volatility). Snapshot dates are irregular (monthly for portfolios 1,
2, 4 and quarterly for 3, 5, 6, 7 in the seed) — handle NULL
`change_percent` and uneven spacing.

### `v_holdings_reconciliation`
Validation view — **expected to be empty**. One row per (portfolio, stock)
where stored holdings disagree with the transaction log. Useful for a
"database health" indicator in any component; non-empty means someone wrote
rows outside the procedures.

## 4. Write API — stored procedures

### `sp_record_transaction` (the only BUY/SELL path)

```sql
CALL sp_record_transaction(
    p_portfolio_id,      -- INT UNSIGNED, must exist
    p_stock_id,          -- INT UNSIGNED, must exist
    p_transaction_type,  -- 'BUY' or 'SELL' (anything else is rejected)
    p_quantity,          -- DECIMAL(12,4), > 0 (fractional shares allowed)
    p_price_per_unit,    -- DECIMAL(12,2), > 0
    p_transaction_date,  -- DATETIME, not NULL
    p_notes,             -- VARCHAR(255) or NULL
    @p_transaction_id    -- OUT: id of the new transactions row
);
```

Python: `db.record_transaction(conn, portfolio_id, stock_id, "BUY", 10,
245.50, "2026-10-12 10:30:00", "optional note") -> int`.

**Behavior guarantees (all tested):**

- **Atomic:** the `transactions` insert and the `holdings` update commit
  together or not at all. A rejected call changes *nothing*.
- **Concurrency-safe:** the parent portfolio row is locked (`FOR UPDATE`)
  for the call's duration, so two sessions trading the same portfolio
  cannot corrupt the holdings. Different portfolios proceed in parallel.
- **Validated rejections** (procedure raises `SQLSTATE 45000` with these
  messages — show them to users as-is):
  - `Invalid transaction type: must be BUY or SELL`
  - `Quantity must be greater than zero`
  - `Price per unit must be greater than zero`
  - `Transaction date is required`
  - `Portfolio does not exist` / `Stock does not exist`
  - `Cannot sell: no holdings of this stock in this portfolio`
  - `Cannot sell: quantity exceeds current holdings`
- **Cost basis:** weighted-average method (work example in the data
  dictionary §Stored procedures). Sells never change the average; a full
  sell-out removes the holding row.

### `sp_create_snapshot`

```sql
CALL sp_create_snapshot(p_portfolio_id, p_snapshot_date);
```

Python: `db.create_snapshot(conn, portfolio_id, "2026-10-12")`.

Computes market value and cost basis from *current* holdings × *current*
illustrative prices and stores one row per (portfolio, date). Calling it
twice for the same date **refreshes** the row (idempotent upsert). Empty
portfolios snapshot as zeros — a valid record, not an error.

### `sp_rebuild_holdings`

```sql
CALL sp_rebuild_holdings(p_portfolio_id);
```

Maintenance/repair procedure (also used by the seed). Replaces the
portfolio's holdings with a faithful replay of its transaction log. Your
components should not need it; it is documented so you know what happened
to holdings after a seed reload.

## 5. Environment & Python contract

Config comes from environment variables (`.env` at repo root, template
`.env.example`; see README):

| Variable | Default |
|---|---|
| `FINWISE_DB_HOST` | `127.0.0.1` |
| `FINWISE_DB_PORT` | `3306` |
| `FINWISE_DB_USER` | `root` (or a least-privilege app account) |
| `FINWISE_DB_PASSWORD` | **required** — never commit |
| `FINWISE_DB_NAME` | `finwise` |
| `FINWISE_TEST_DB_NAME` | `finwise_test` (must contain "test") |

Import pattern:

```python
from db import (get_connection, fetch_all, fetch_one, execute,
               record_transaction, create_snapshot)

conn = get_connection()            # to the finwise database
rows = fetch_all(conn, "SELECT * FROM v_portfolio_positions WHERE portfolio_id = %s", (pid,))
tx_id = record_transaction(conn, pid, sid, "BUY", 10, 245.50, "2026-10-12 10:30:00")
```

## 6. Change protocol

1. Request schema changes through Member 1 (GitHub issue or chat).
2. Additive changes (new nullable columns, new views/procedures) are
   preferred; the API in this document stays signature-compatible.
3. `01_schema.sql` / `02_stored_procedures.sql` / `03_views.sql` are
   versioned — do not hot-fix them locally, or your teammates' setups will
   diverge.

## 7. Explicitly OUT of scope for this phase

- Live market-data APIs (all prices are illustrative).
- Authentication/login (no password columns exist; additive if needed).
- Cash balances inside portfolios (buy/sell proceeds are derivable from
  `transactions`).
- Historical per-stock prices — **known limitation**: snapshots are
  point-in-time records and cannot reconstruct historical prices. If a
  component needs historical price series, request the additive
  `stock_prices(stock_id, price_date, close_price)` extension; the current
  schema and contract are prepared for it.

## 8. Open questions for the team (please answer during review)

1. Which views/procedures do your components actually need, and is any
   column missing that you would have to compute client-side?
2. Do you need a paged/ordered variant of any view (e.g. top-N positions)?
3. Is the snapshot frequency (monthly/quarterly) enough for the risk
   analytics you plan, or should the runner create daily snapshots?
4. Should `v_user_summary` expose portfolio-level rows too (one row per
   portfolio per user)?
5. Any naming clashes with your planned code (table/view names)?

## 9. MongoDB read model (additive, Member 3)

FinWise also provides a **read-only MongoDB read model** of the data
(`docs/mongodb_module.md`). It does **not** change anything in this contract:

- The ETL (`python/load_mongo.py`) only **SELECTs** from the views/tables
  above and writes to MongoDB. It never writes back, so the "writes go
  through the procedures" rule (§2.1) is unchanged.
- The views and procedures above remain the only read/write API for MySQL.
- The MongoDB collections (`stock_fundamentals`, `portfolios`,
  `transactions`, `portfolio_snapshots`) are disposable and can be rebuilt
  from MySQL at any time.

— End of DRAFT v0.1 —
