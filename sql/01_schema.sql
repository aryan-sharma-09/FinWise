-- =============================================================================
--  FinWise - Financial Literacy and Portfolio Risk Analytics Platform
--  01_schema.sql
--
--  Purpose : Create the seven core tables with keys, foreign keys, CHECK
--            constraints, and indexes.
--  Requires: MySQL 8.0.16 or newer (CHECK constraints are enforced 8.0.16+).
--
--  !! WARNING - DESTRUCTIVE TO FINWISE TABLES !!
--  This script DROPs and re-CREATEs all seven FinWise tables. Never run it
--  against a database that contains data you need. To wipe only the sample
--  data and reload it, run 04_seed_data.sql instead (it truncates the tables
--  but leaves this schema intact).
--
--  Design notes
--  - All identifiers are lowercase snake_case so the schema behaves
--    identically on macOS, Windows, and Linux (lower_case_table_names
--    differs by operating system).
--  - All monetary and quantity columns use DECIMAL (exact arithmetic),
--    never FLOAT/DOUBLE.
--  - Referential actions:
--      users        -> portfolios               ON DELETE CASCADE
--      portfolios   -> holdings/transactions/
--                      portfolio_snapshots      ON DELETE CASCADE
--      stocks       -> holdings/transactions    ON DELETE RESTRICT
--      sectors      -> stocks                   ON DELETE RESTRICT
--    Deleting a user removes their portfolios and all related rows; deleting
--    a stock or sector is refused while any row still references it, so
--    transaction history is never silently destroyed.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS finwise
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

-- Drop in child-first order so foreign key checks can remain enabled.
DROP TABLE IF EXISTS portfolio_snapshots;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS holdings;
DROP TABLE IF EXISTS portfolios;
DROP TABLE IF EXISTS stocks;
DROP TABLE IF EXISTS sectors;
DROP TABLE IF EXISTS users;

USE finwise;

-- =============================================================================
--  users - people who own portfolios (fictional accounts in sample data)
-- =============================================================================
CREATE TABLE users (
  user_id       INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  username      VARCHAR(50)     NOT NULL,
  email         VARCHAR(255)    NOT NULL,
  full_name     VARCHAR(100)    NOT NULL,
  created_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_username (username),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  sectors - reference classification of stocks (GICS-inspired)
-- =============================================================================
CREATE TABLE sectors (
  sector_id     INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  sector_name   VARCHAR(60)     NOT NULL,
  description   VARCHAR(500)    NULL,
  PRIMARY KEY (sector_id),
  UNIQUE KEY uq_sectors_name (sector_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  stocks - master data of tradable instruments with illustrative
--  fundamentals. current_price is an illustrative value "as of" price_as_of;
--  it is NOT live market data. A single current price per stock means
--  historical prices cannot be reconstructed from this table (a future
--  stock_prices extension would add that - see docs/database_contract.md).
-- =============================================================================
CREATE TABLE stocks (
  stock_id            INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  ticker_symbol       VARCHAR(10)    NOT NULL,
  company_name        VARCHAR(150)   NOT NULL,
  sector_id           INT UNSIGNED   NOT NULL,
  current_price       DECIMAL(12,2)  UNSIGNED NOT NULL,
  market_cap_millions DECIMAL(18,2)  NULL,                -- millions of USD
  pe_ratio            DECIMAL(8,2)   NULL,                -- NULL = not meaningful (e.g. loss-making)
  dividend_yield      DECIMAL(5,2)   NULL,                -- percent, 0..100
  price_as_of         DATE           NULL,                -- date the illustrative price represents
  updated_at          TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (stock_id),
  UNIQUE KEY uq_stocks_ticker (ticker_symbol),
  KEY idx_stocks_sector (sector_id),
  CONSTRAINT fk_stocks_sector
    FOREIGN KEY (sector_id) REFERENCES sectors (sector_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT chk_stocks_price
    CHECK (current_price > 0),
  CONSTRAINT chk_stocks_pe
    CHECK (pe_ratio IS NULL OR pe_ratio > 0),
  CONSTRAINT chk_stocks_dividend
    CHECK (dividend_yield IS NULL OR (dividend_yield >= 0 AND dividend_yield <= 100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  portfolios - named investment portfolios owned by a user
-- =============================================================================
CREATE TABLE portfolios (
  portfolio_id    INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  user_id         INT UNSIGNED   NOT NULL,
  portfolio_name  VARCHAR(80)    NOT NULL,
  created_at      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (portfolio_id),
  UNIQUE KEY uq_portfolios_user_name (user_id, portfolio_name),
  KEY idx_portfolios_user (user_id),
  CONSTRAINT fk_portfolios_user
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  holdings - CURRENT state: one row per (portfolio, stock) with a position.
--  INVARIANT: quantity is always > 0. A full sell-out DELETEs the row
--  instead of leaving quantity = 0.
--
--  holdings is maintained state: every change goes through
--  sp_record_transaction (see 02_stored_procedures.sql). Application code
--  must never INSERT/UPDATE/DELETE these rows directly.
-- =============================================================================
CREATE TABLE holdings (
  holding_id             INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  portfolio_id           INT UNSIGNED   NOT NULL,
  stock_id               INT UNSIGNED   NOT NULL,
  quantity               DECIMAL(12,4)  UNSIGNED NOT NULL,
  average_cost_per_unit  DECIMAL(12,2)  UNSIGNED NOT NULL,
  updated_at             TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (holding_id),
  UNIQUE KEY uq_holdings_portfolio_stock (portfolio_id, stock_id),
  KEY idx_holdings_stock (stock_id),
  CONSTRAINT fk_holdings_portfolio
    FOREIGN KEY (portfolio_id) REFERENCES portfolios (portfolio_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_holdings_stock
    FOREIGN KEY (stock_id) REFERENCES stocks (stock_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT chk_holdings_quantity
    CHECK (quantity > 0),
  CONSTRAINT chk_holdings_cost
    CHECK (average_cost_per_unit > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  transactions - IMMUTABLE historical record of BUY/SELL activity.
--  This is the audit trail and the source of truth for history. Rows must
--  never be updated or deleted; all inserts go through
--  sp_record_transaction (the seed script is the only documented exception
--  because it fabricates history before holdings exist).
-- =============================================================================
CREATE TABLE transactions (
  transaction_id    INT UNSIGNED       NOT NULL AUTO_INCREMENT,
  portfolio_id      INT UNSIGNED       NOT NULL,
  stock_id          INT UNSIGNED       NOT NULL,
  transaction_type  ENUM('BUY','SELL') NOT NULL,
  quantity          DECIMAL(12,4)      UNSIGNED NOT NULL,
  price_per_unit    DECIMAL(12,2)      UNSIGNED NOT NULL,
  transaction_date  DATETIME           NOT NULL,
  notes             VARCHAR(255)       NULL,
  created_at        TIMESTAMP          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (transaction_id),
  KEY idx_tx_portfolio_date (portfolio_id, transaction_date),
  KEY idx_tx_stock (stock_id),
  KEY idx_tx_date (transaction_date),
  CONSTRAINT fk_tx_portfolio
    FOREIGN KEY (portfolio_id) REFERENCES portfolios (portfolio_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_tx_stock
    FOREIGN KEY (stock_id) REFERENCES stocks (stock_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT chk_tx_quantity
    CHECK (quantity > 0),
  CONSTRAINT chk_tx_price
    CHECK (price_per_unit > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- =============================================================================
--  portfolio_snapshots - point-in-time valuation records, one per portfolio
--  per day (used for performance trends and risk metrics).
--
--  IMPORTANT: snapshots are historical RECORDS. They are computed from
--  holdings x prices as of their snapshot_date and cannot be re-derived
--  later from the seven-table core, because stocks stores only ONE
--  illustrative current price. Historical per-stock prices would require a
--  future stock_prices extension table.
--
--  Application code must never INSERT/UPDATE these rows directly; use
--  sp_create_snapshot.
-- =============================================================================
CREATE TABLE portfolio_snapshots (
  snapshot_id         INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  portfolio_id        INT UNSIGNED   NOT NULL,
  snapshot_date       DATE           NOT NULL,
  total_market_value  DECIMAL(16,2)  UNSIGNED NOT NULL,
  total_cost_basis    DECIMAL(16,2)  UNSIGNED NOT NULL,
  holdings_count      INT UNSIGNED   NOT NULL DEFAULT 0,
  created_at          TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  UNIQUE KEY uq_snapshots_portfolio_date (portfolio_id, snapshot_date),
  KEY idx_snapshots_date (snapshot_date),
  CONSTRAINT fk_snapshots_portfolio
    FOREIGN KEY (portfolio_id) REFERENCES portfolios (portfolio_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT chk_snapshot_value
    CHECK (total_market_value >= 0),
  CONSTRAINT chk_snapshot_cost
    CHECK (total_cost_basis >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
