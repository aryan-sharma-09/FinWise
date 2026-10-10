# FinWise Data Dictionary

Complete reference for the FinWise relational schema: every table, column,
constraint, and index, plus the views and stored procedures.

- **DBMS:** MySQL 8.0.16+ (CHECK constraints require 8.0.16)
- **Character set:** `utf8mb4` / `utf8mb4_0900_ai_ci` everywhere
- **Naming:** lowercase `snake_case` (portability across macOS / Windows / Linux)
- **Money & quantities:** `DECIMAL` only — never `FLOAT`/`DOUBLE`
- **Relationships:** see `docs/er_diagram.mmd`

## Conventions and global rules

| Rule | Where enforced |
|---|---|
| Quantities and prices are strictly positive | `CHECK` constraints + `sp_record_transaction` |
| `holdings` never stores a zero position; a full sell-out deletes the row | Procedure logic + `CHECK (quantity > 0)` |
| `transactions` is an immutable audit log | Policy; all writes go through `sp_record_transaction` |
| One snapshot per (portfolio, date) | `UNIQUE (portfolio_id, snapshot_date)` |
| Deleting a user cascades to portfolios, holdings, transactions, snapshots | `ON DELETE CASCADE` |
| Deleting a stock or sector is refused while referenced | `ON DELETE RESTRICT` |
| Snapshots are point-in-time records, not derivable from current prices | See *Limitations* below |

## `users` — people who own portfolios

> Fictional accounts only in this project (`@finwise.example`). No
> authentication columns in this phase; if a login component is added later,
> a nullable `password_hash` column is a single additive `ALTER TABLE`.

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `user_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `username` | `VARCHAR(50)` | no | — | Unique login-style name |
| `email` | `VARCHAR(255)` | no | — | Unique contact address |
| `full_name` | `VARCHAR(100)` | no | — | Display name |
| `created_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` | Row creation time (UTC convention) |

**Indexes:** PK (`user_id`); `uq_users_username (username)`; `uq_users_email (email)`

## `portfolios` — named investment portfolios

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `portfolio_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `user_id` | `INT UNSIGNED` | no | — | Owner → `users.user_id` (`ON DELETE CASCADE`) |
| `portfolio_name` | `VARCHAR(80)` | no | — | Display name; unique per user |
| `created_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` | Creation time |

**Constraints:** `UNIQUE (user_id, portfolio_name)` — two users may share a
portfolio name, one user may not duplicate their own.

**Indexes:** PK; `uq_portfolios_user_name (user_id, portfolio_name)`; `idx_portfolios_user (user_id)`

## `sectors` — stock classification (reference data)

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `sector_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `sector_name` | `VARCHAR(60)` | no | — | Unique name (GICS-inspired) |
| `description` | `VARCHAR(500)` | yes | `NULL` | Short explanation |

**Indexes:** PK; `uq_sectors_name (sector_name)`

## `stocks` — master data (illustrative values)

> Every value is a synthetic illustrative number, **not live market data**.
> `current_price` represents `price_as_of`. This table deliberately holds one
> price per stock; historical prices need the future `stock_prices` extension
> (see `database_contract.md`).

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `stock_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `ticker_symbol` | `VARCHAR(10)` | no | — | Unique ticker (uppercase) |
| `company_name` | `VARCHAR(150)` | no | — | Display name |
| `sector_id` | `INT UNSIGNED` | no | — | → `sectors.sector_id` (`ON DELETE RESTRICT`) |
| `current_price` | `DECIMAL(12,2) UNSIGNED` | no | — | Illustrative price, `> 0` |
| `market_cap_millions` | `DECIMAL(18,2)` | yes | `NULL` | Market cap in **millions of USD** |
| `pe_ratio` | `DECIMAL(8,2)` | yes | `NULL` | Price/earnings; `NULL` = not meaningful (loss-making) |
| `dividend_yield` | `DECIMAL(5,2)` | yes | `NULL` | Percent 0–100; `NULL` = no dividend modeled |
| `price_as_of` | `DATE` | yes | `NULL` | Date the illustrative price represents |
| `updated_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` on update | Row maintenance time |

**CHECK constraints:** `current_price > 0`; `pe_ratio IS NULL OR pe_ratio > 0`;
`dividend_yield IS NULL OR (0 ≤ dividend_yield ≤ 100)`.

**Indexes:** PK; `uq_stocks_ticker (ticker_symbol)`; `idx_stocks_sector (sector_id)`

## `holdings` — current portfolio state (maintained)

> One row per (portfolio, stock) with a non-zero position. This table is
> **maintained state**: every change happens inside
> `sp_record_transaction` (or `sp_rebuild_holdings`). Application code must
> never write it directly — `v_holdings_reconciliation` exists to catch such
> drift.

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `holding_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** (surrogate) |
| `portfolio_id` | `INT UNSIGNED` | no | — | → `portfolios.portfolio_id` (`ON DELETE CASCADE`) |
| `stock_id` | `INT UNSIGNED` | no | — | → `stocks.stock_id` (`ON DELETE RESTRICT`) |
| `quantity` | `DECIMAL(12,4) UNSIGNED` | no | — | Shares held, `> 0` (fractional allowed) |
| `average_cost_per_unit` | `DECIMAL(12,2) UNSIGNED` | no | — | Weighted-average cost, `> 0` |
| `updated_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` on update | Last maintenance time |

**Constraints:** `UNIQUE (portfolio_id, stock_id)`; `CHECK (quantity > 0)`;
`CHECK (average_cost_per_unit > 0)`.

**Indexes:** PK; `uq_holdings_portfolio_stock (portfolio_id, stock_id)`;
`idx_holdings_stock (stock_id)` — supports "which portfolios hold X?".

## `transactions` — immutable event history

> The audit trail and source of truth for *what happened and when*. Rows are
> never updated or deleted. All inserts go through `sp_record_transaction`
> (the seed script is the only documented exception, because it fabricates
> history before holdings exist, then calls `sp_rebuild_holdings`).

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `transaction_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `portfolio_id` | `INT UNSIGNED` | no | — | → `portfolios.portfolio_id` (`ON DELETE CASCADE`) |
| `stock_id` | `INT UNSIGNED` | no | — | → `stocks.stock_id` (`ON DELETE RESTRICT`) |
| `transaction_type` | `ENUM('BUY','SELL')` | no | — | Direction |
| `quantity` | `DECIMAL(12,4) UNSIGNED` | no | — | Shares traded, `> 0` |
| `price_per_unit` | `DECIMAL(12,2) UNSIGNED` | no | — | Execution price, `> 0` |
| `transaction_date` | `DATETIME` | no | — | When the trade happened (UTC convention) |
| `notes` | `VARCHAR(255)` | yes | `NULL` | Free-text comment |
| `created_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` | Row insert time |

**CHECK constraints:** `quantity > 0`; `price_per_unit > 0`.

**Indexes:** PK; `idx_tx_portfolio_date (portfolio_id, transaction_date)`;
`idx_tx_stock (stock_id)`; `idx_tx_date (transaction_date)`.

## `portfolio_snapshots` — point-in-time valuations

> One row per (portfolio, date). Used for performance trends and risk
> metrics. **These are historical records**: computed from holdings × prices
> as of `snapshot_date` by `sp_create_snapshot` and *not re-derivable later*
> (stocks carries a single illustrative current price). Seeded historical
> snapshots are illustrative synthetic values; only the final snapshot
> (2026-10-10) is computed from the seeded holdings.

| Column | Type | Null | Default | Meaning |
|---|---|---|---|---|
| `snapshot_id` | `INT UNSIGNED AUTO_INCREMENT` | no | — | **Primary key** |
| `portfolio_id` | `INT UNSIGNED` | no | — | → `portfolios.portfolio_id` (`ON DELETE CASCADE`) |
| `snapshot_date` | `DATE` | no | — | Valuation date |
| `total_market_value` | `DECIMAL(16,2) UNSIGNED` | no | — | Σ quantity × current_price, `≥ 0` |
| `total_cost_basis` | `DECIMAL(16,2) UNSIGNED` | no | — | Σ quantity × average_cost_per_unit, `≥ 0` |
| `holdings_count` | `INT UNSIGNED` | no | `0` | Number of distinct positions |
| `created_at` | `TIMESTAMP` | no | `CURRENT_TIMESTAMP` | Row insert time |

**Constraints:** `UNIQUE (portfolio_id, snapshot_date)`;
`CHECK (total_market_value >= 0)`; `CHECK (total_cost_basis >= 0)`.

**Indexes:** PK; `uq_snapshots_portfolio_date (portfolio_id, snapshot_date)`;
`idx_snapshots_date (snapshot_date)`.

## Views (read API)

| View | Purpose | Key columns |
|---|---|---|
| `v_portfolio_positions` | Current positions with value, unrealized P/L, and portfolio weight | `portfolio_id, ticker_symbol, sector_name, quantity, average_cost_per_unit, current_price, cost_basis, market_value, unrealized_pl, pl_percent, portfolio_total_value, portfolio_weight_percent` |
| `v_sector_allocation` | Sector money and percent weight per portfolio | `portfolio_id, sector_name, sector_value, portfolio_total_value, sector_weight_percent` |
| `v_user_summary` | Per-user totals (keeps zero-portfolio users) | `user_id, username, portfolio_count, position_count, total_market_value, total_cost_basis, total_unrealized_pl` |
| `v_portfolio_performance` | Snapshots with previous value and change | `portfolio_id, snapshot_date, holdings_count, total_cost_basis, total_market_value, previous_market_value, change_value, change_percent` |
| `v_holdings_reconciliation` | Stored vs transaction-derived holdings; **must be empty** | `portfolio_id, stock_id, derived_quantity, stored_quantity, quantity_difference` |

## Stored procedures (write API)

| Procedure | Signature | Notes |
|---|---|---|
| `sp_record_transaction` | `(IN p_portfolio_id, IN p_stock_id, IN p_transaction_type VARCHAR(10), IN p_quantity DECIMAL(12,4), IN p_price_per_unit DECIMAL(12,2), IN p_transaction_date DATETIME, IN p_notes VARCHAR(255), OUT p_transaction_id INT UNSIGNED)` | Atomic BUY/SELL; validates everything; locks the portfolio row (`FOR UPDATE`) to serialize concurrent writes; maintains holdings with weighted-average cost; `ROLLBACK` + `RESIGNAL` on any error. |
| `sp_create_snapshot` | `(IN p_portfolio_id, IN p_snapshot_date DATE)` | Computes totals from current holdings × prices; idempotent upsert per (portfolio, date). |
| `sp_rebuild_holdings` | `(IN p_portfolio_id)` | Replays the transaction log with identical cost rules; used by the seed and tests, and for disaster recovery. |

**Weighted-average cost rules (documented + tested):**

```
BUY : new_avg = ROUND((held_qty * held_avg + qty * price)
                      / (held_qty + qty), 2)
SELL: average_cost_per_unit unchanged; quantity reduced;
      a full sell-out DELETES the holding row.
```

Worked example (asserted in `tests/test_procedures.py`):

```
BUY 10 @ 100.00 -> qty 10, avg 100.00
BUY  5 @ 130.00 -> qty 15, avg 110.00     (10*100 + 5*130) / 15
SELL  3 @ 150.00 -> qty 12, avg 110.00    (sale never changes the average)
BUY  6 @  95.00 -> qty 18, avg 105.00     (12*110 + 6*95) / 18
SELL 18 @ 120.00 -> holding row removed   (full exit)
```

## Seed data shape

| Table | Rows | Notes |
|---|---|---|
| `users` | 6 | Two users own no portfolios (LEFT JOIN demos) |
| `sectors` | 8 | GICS-inspired |
| `stocks` | 26 | Real public tickers, **illustrative** values |
| `portfolios` | 7 | One user owns 3, one owns 2 (HAVING demos) |
| `transactions` | 48 | ~13 months; partial sells and one full exit |
| `holdings` | 38 | Materialized via `sp_rebuild_holdings` |
| `portfolio_snapshots` | 52 | Monthly (P1, P2, P4) + quarterly (P3, P5, P6, P7) + computed current |

## Known limitations

1. **No historical stock prices.** `stocks.current_price` is a single
   illustrative "as of" value; snapshots are point-in-time records that
   cannot be recomputed from the seven-table core. A future additive
   `stock_prices (stock_id, price_date, close_price)` table would enable
   historical reconstruction without breaking any contract.
2. **Snapshot cost basis is historical.** A snapshot's `total_cost_basis`
   reflects the holdings *at that moment*; later trades legitimately change
   today's cost basis, so current holdings need not match old snapshots.
3. **No cash ledger.** Portfolios track positions only; buy/sell proceeds
   are derivable from `transactions` (quantity × price) when needed.
