# FinWise — Financial Literacy and Portfolio Risk Analytics Platform

FinWise is a database-driven platform that helps users manage **simulated**
investment portfolios, record investment transactions, explore stock
fundamentals, and understand portfolio performance and risk.

> **IMPORTANT — Educational project disclaimer**
>
> - All prices, fundamentals, portfolios, and transactions in this repository
>   are **synthetic, illustrative sample data** for a college DCDS project.
>   They are **not live market data** and must never be presented as such.
> - FinWise does **not** execute real trades, predict stock prices, or provide
>   personalized financial advice.
> - No private or personal financial information is stored anywhere in this
>   repository. All user accounts are fictional (`@finwise.example`).

---

## What is included (Member 1 scope — database foundation)

- A seven-table MySQL 8.0+ relational schema:
  `users`, `portfolios`, `sectors`, `stocks`, `holdings`, `transactions`,
  `portfolio_snapshots` — with primary keys, foreign keys, `CHECK`
  constraints, and indexes.
- Stored procedures:
  - `sp_record_transaction` — atomic, validated, concurrency-safe BUY/SELL
    processing that maintains `holdings` with weighted-average cost.
  - `sp_create_snapshot` — idempotent daily portfolio valuation snapshots.
  - `sp_rebuild_holdings` — replays the transaction log to reconstruct
    holdings (used by the seed and by the test suite).
- Analytical views: `v_portfolio_positions`, `v_sector_allocation`,
  `v_user_summary`, `v_portfolio_performance`, `v_holdings_reconciliation`.
- Deterministic seed data: 6 fictional users, 8 sectors, 26 recognizable
  public tickers with **illustrative** values, 7 portfolios, 48 transactions
  across ~13 months, and dated portfolio snapshots.
- A library of documented reference queries demonstrating joins, `GROUP BY`,
  `HAVING`, subqueries, window functions, CTEs, and more.
- Python integration: a secure connection helper (credentials via `.env`,
  never in source code), a cross-platform database loader, CRUD examples that
  write **only** through the stored procedures, and a verification script.
- A pytest suite covering schema constraints, referential integrity and
  cascade deletes, procedure behavior with atomicity checks (rejected
  operations leave no partial state), weighted-average cost math, signed
  arithmetic (losing positions and performance decreases),
  holdings/transactions reconciliation, invalid-input handling, and
  the CRUD demo menu (options 0-10) via scripted integration tests.

## Documentation for teammates

- [`docs/data_dictionary.md`](docs/data_dictionary.md) — every table, column,
  type, constraint, and index.
- [`docs/database_contract.md`](docs/database_contract.md) — **DRAFT** stable
  API (views + procedures) that Members 2, 3, and 4 build against. Requires
  team review.
- [`docs/er_diagram.mmd`](docs/er_diagram.mmd) — ER diagram (Mermaid source;
  render it with the Mermaid VS Code extension or https://mermaid.live). The
  file starts directly with the `erDiagram` line so every Mermaid renderer can
  detect the diagram; it shows key attributes only — the complete column list
  lives in the data dictionary. Crow's-foot notation: `||--o{` means "one
  parent row to zero-or-more child rows".

## Requirements

| Component | Version | Notes |
|---|---|---|
| MySQL Server | **8.0.16 or newer** | `CHECK` constraints are enforced from 8.0.16; CTEs and window functions require 8.0 |
| Python | 3.10 or newer | 3.12+ recommended |
| mysql-connector-python | ≥ 8.2 | via `requirements.txt` |

Works the same on macOS and Windows. All identifiers are lowercase
`snake_case`, all text files use LF line endings and UTF-8, and timestamps
are stored in UTC by convention — so the schema behaves identically on both
operating systems.

## Project structure

```
FinWise/
├── README.md                  ← you are here
├── .env.example               ← template for local database credentials
├── requirements.txt
├── pytest.ini
├── sql/
│   ├── 00_create_database.sql ← creates the database (safe to re-run)
│   ├── 01_schema.sql          ← WARNING: drops and recreates all 7 tables
│   ├── 02_stored_procedures.sql
│   ├── 03_views.sql
│   ├── 04_seed_data.sql       ← WARNING: wipes and reloads sample data
│   └── 05_analytics_queries.sql ← read-only reference queries
├── python/
│   ├── db.py                  ← connection helper + procedure wrappers
│   ├── load_database.py       ← cross-platform loader for the SQL scripts
│   ├── crud_examples.py       ← menu-driven CRUD demo
│   └── verify_setup.py        ← health check for your installation
├── tests/
│   ├── conftest.py
│   ├── test_schema.py
│   ├── test_procedures.py
│   ├── test_reconciliation.py
│   ├── test_signed_arithmetic.py
│   └── test_menu_integration.py
└── docs/
    ├── data_dictionary.md
    ├── database_contract.md   ← DRAFT: requires team review
    └── er_diagram.mmd
```

## Setup

### 1. Install MySQL 8.0+ and start the server

**macOS (Homebrew)**

```bash
brew install mysql
brew services start mysql      # or: mysql.server start
mysql -u root -p               # verify it responds (press Enter if no root password)
```

**macOS (official installer)** — download the MySQL 8.0 DMG from
dev.mysql.com, install, and start MySQL from System Settings.

**Windows**

1. Install the MySQL 8.0 Community Server with the MySQL Installer
   (https://dev.mysql.com/downloads/installer/). Keep the "Server only" or
   "Developer Default" setup — choose **Legacy or SHA256 authentication**;
   either works with Connector/Python 8.2+.
2. Remember the root password you set.
3. The installer usually starts the service automatically (check
   `services.msc` → MySQL80).

Verify from a terminal (PowerShell or Command Prompt):

```powershell
mysql -u root -p -e "SELECT VERSION();"
```

If `mysql` is not recognized, add
`C:\Program Files\MySQL\MySQL Server 8.0\bin` to your PATH or use the full
path. The Python loader below avoids this problem entirely.

### 2. Install Python dependencies

```bash
# from the repository root
python3 -m venv .venv
source .venv/bin/activate            # macOS
# Windows (PowerShell):
#   python -m venv .venv
#   .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Configure credentials (never commit them)

```bash
cp .env.example .env                 # Windows: copy .env.example .env
```

Edit `.env` and set `FINWISE_DB_PASSWORD` to your MySQL root password (or a
dedicated account — see *Security notes* below). `.env` is gitignored.

### 4. Load the database

**Option A — Python loader (recommended; identical on macOS and Windows)**

```bash
python python/load_database.py --yes
```

This creates the `finwise` database, loads the schema, procedures, views,
and seed data, and prints progress. It is **destructive to existing FinWise
tables** — it drops and recreates them — so it asks for confirmation unless
`--yes` is passed. You can target another database with `--database NAME`.

**Option B — mysql command line**

```bash
mysql -u root -p                            < sql/00_create_database.sql
mysql -u root -p finwise                    < sql/01_schema.sql
mysql -u root -p finwise                    < sql/02_stored_procedures.sql
mysql -u root -p finwise                    < sql/03_views.sql
mysql -u root -p finwise                    < sql/04_seed_data.sql
```

(Or, inside a `mysql` session: `source sql/00_create_database.sql;` — file 00
also selects the `finwise` database, so you can then `source` files 01–04 in
order.)

### 5. Verify the installation

```bash
python python/verify_setup.py
```

Expected result: all seven tables report row counts, the reconciliation view
is empty (holdings match the transaction log), and the script prints
`SETUP VERIFICATION PASSED`.

### 6. Run the test suite

```bash
pytest
```

The tests create and destroy a **separate** database (default name
`finwise_test` — configurable with `FINWISE_TEST_DB_NAME`, which must contain
the word "test") so your demo data is never touched. If MySQL is not running
or `.env` is not configured, every test is skipped with a clear reason rather
than failing.

### 7. Try the interactive demo

```bash
python python/crud_examples.py
```

A menu lets you list users, browse portfolio positions through the views,
add users, rename or delete portfolios, and record BUY/SELL transactions —
the latter always through `sp_record_transaction`, including what happens
when a transaction is rejected (e.g., selling more shares than held).

## Browsing the analytics queries

`sql/05_analytics_queries.sql` contains ~16 numbered, commented, read-only
reference queries (joins, aggregations, `HAVING`, subqueries, window
functions, CTEs). Run them anywhere you can run SQL, for example:

```bash
mysql -u root -p finwise < sql/05_analytics_queries.sql
```

## Security notes

- **No credentials in source code.** The Python layer reads all connection
  settings from environment variables / `.env`. `.env` is gitignored; only
  `.env.example` (placeholders) is committed.
- **Least privilege.** For a shared classroom setup, create a dedicated
  account instead of using root (template in `sql/00_create_database.sql`):

  ```sql
  CREATE USER 'finwise_app'@'localhost' IDENTIFIED BY '<strong-password>';
  GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON finwise.* TO 'finwise_app'@'localhost';
  ```

  then set `FINWISE_DB_USER=finwise_app` in `.env`.
- **Parameterized queries everywhere.** The Python layer never builds SQL by
  string formatting, so it is not vulnerable to SQL injection through user
  input.

## Team workflow (Members 2, 3, 4)

1. Read `docs/database_contract.md` (DRAFT) first — it defines the stable
   read API (views) and write API (stored procedures).
2. Never write to `holdings`, `transactions`, or `portfolio_snapshots`
   directly from application code. Use `sp_record_transaction` /
   `sp_create_snapshot` (or the Python wrappers in `python/db.py`).
3. Schema changes go through Member 1, additive `ALTER`s preferred, so the
   view/procedure signatures stay stable.

## Known limitations and future extensions

- **Historical prices.** `stocks.current_price` is a single illustrative
  "as of" price per stock. `portfolio_snapshots` are point-in-time records and
  **cannot** reconstruct historical per-stock prices. If the team later needs
  historical price charts, add a `stock_prices` table (additive change) —
  see `docs/database_contract.md`.
- No authentication, live market APIs, cash balances, or trading simulation
  — intentionally out of scope for this phase.

## Business Intelligence & Analytics

The portfolio management and risk metrics are visualized using an interactive Power BI dashboard:

![FinWise Dashboard Overview](dashboards/dashboard_overview.png)

### Key Analytics Modules:
- **Concentration Analysis**: Herfindahl-Hirschman Index (HHI) score monitoring.
- **Exposure Breakdown**: Real-time sector asset allocation.
- **Valuation Tracking**: Historical portfolio value progression over snapshot dates.
- **Position Ledger**: Granular unrealized P/L and fundamentals breakdown per holding.

- ## 🌐 Live Interactive Web Dashboard

Access the real-time portfolio analytics and risk monitoring platform online:

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://finwise-2kdst3db5dplzxp29vbspe.streamlit.app/)

> **Live Demo:** [FinWise Analytics Hub](https://finwise-2kdst3db5dplzxp29vbspe.streamlit.app/)

---

### Local Execution

To run the Streamlit frontend locally:

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the web application
streamlit run app.py
