-- =============================================================================
--  FinWise - 03_views.sql
--
--  Purpose : Analytical views that form the READ side of the database
--            contract. Members 2, 3, and 4 should query these views rather
--            than hand-joining the base tables, so that the underlying
--            schema can evolve without breaking their components.
--  Requires: MySQL 8.0.16 or newer.
--  Safety  : Read-only; safe to re-run (CREATE OR REPLACE VIEW).
--
--  Contents
--    v_portfolio_positions      - current positions with value, P/L, weight
--    v_sector_allocation       - sector weights per portfolio
--    v_user_summary             - per-user totals
--    v_portfolio_performance    - snapshots with period-over-period change
--    v_holdings_reconciliation  - stored vs. transaction-derived holdings
--                                 (validation view; expected to be EMPTY)
--
--  Design notes
--   - The views are built with derived tables and correlated subqueries
--     rather than window functions so they behave identically across all
--     MySQL 8.0.x point releases. Window functions are demonstrated in
--     sql/05_analytics_queries.sql.
--   - Division-by-zero is impossible by construction: CHECK constraints
--     guarantee quantity > 0, average_cost_per_unit > 0, and prices > 0.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- v_portfolio_positions
--   One row per current holding: who owns it, in which portfolio, which
--   stock/sector, cost basis, market value, unrealized P/L, and the
--   position's percent weight inside its portfolio.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_portfolio_positions AS
SELECT
    h.holding_id,
    h.portfolio_id,
    p.portfolio_name,
    p.user_id,
    u.username,
    h.stock_id,
    s.ticker_symbol,
    s.company_name,
    sec.sector_name,
    h.quantity,
    h.average_cost_per_unit,
    s.current_price,
    ROUND(h.quantity * h.average_cost_per_unit, 2)                    AS cost_basis,
    ROUND(h.quantity * s.current_price, 2)                             AS market_value,
    ROUND(h.quantity * (s.current_price - h.average_cost_per_unit), 2) AS unrealized_pl,
    ROUND(100 * (s.current_price - h.average_cost_per_unit)
                / h.average_cost_per_unit, 2)                          AS pl_percent,
    t.portfolio_total_value,
    ROUND(100 * h.quantity * s.current_price / t.portfolio_total_value, 2)
                                                                       AS portfolio_weight_percent
FROM holdings h
JOIN stocks s      ON s.stock_id      = h.stock_id
JOIN sectors sec   ON sec.sector_id   = s.sector_id
JOIN portfolios p  ON p.portfolio_id  = h.portfolio_id
JOIN users u       ON u.user_id       = p.user_id
JOIN (
        SELECT h2.portfolio_id,
               SUM(h2.quantity * s2.current_price) AS portfolio_total_value
        FROM holdings h2
        JOIN stocks s2 ON s2.stock_id = h2.stock_id
        GROUP BY h2.portfolio_id
     ) t ON t.portfolio_id = h.portfolio_id;

-- -----------------------------------------------------------------------------
-- v_sector_allocation
--   One row per (portfolio, sector) with money invested and the sector's
--   percent weight inside the portfolio. Primary view for diversification
--   and concentration analysis.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sector_allocation AS
SELECT
    ps.portfolio_id,
    ps.portfolio_name,
    ps.user_id,
    ps.sector_name,
    ps.sector_value,
    pt.portfolio_total_value,
    ROUND(100 * ps.sector_value / pt.portfolio_total_value, 2) AS sector_weight_percent
FROM (
        SELECT p.portfolio_id,
               p.portfolio_name,
               p.user_id,
               sec.sector_name,
               SUM(h.quantity * s.current_price) AS sector_value
        FROM holdings h
        JOIN stocks s     ON s.stock_id    = h.stock_id
        JOIN sectors sec  ON sec.sector_id = s.sector_id
        JOIN portfolios p ON p.portfolio_id = h.portfolio_id
        GROUP BY p.portfolio_id, p.portfolio_name, p.user_id, sec.sector_name
     ) ps
JOIN (
        SELECT h3.portfolio_id,
               SUM(h3.quantity * s3.current_price) AS portfolio_total_value
        FROM holdings h3
        JOIN stocks s3 ON s3.stock_id = h3.stock_id
        GROUP BY h3.portfolio_id
     ) pt ON pt.portfolio_id = ps.portfolio_id;

-- -----------------------------------------------------------------------------
-- v_user_summary
--   One row per user (including users with no portfolios, thanks to LEFT
--   JOIN) with their total portfolio count, position count, market value,
--   cost basis, and unrealized P/L.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_user_summary AS
SELECT
    u.user_id,
    u.username,
    u.email,
    COUNT(DISTINCT p.portfolio_id)                                   AS portfolio_count,
    COALESCE(x.position_count, 0)                                    AS position_count,
    COALESCE(x.total_market_value, 0)                                AS total_market_value,
    COALESCE(x.total_cost_basis, 0)                                  AS total_cost_basis,
    ROUND(COALESCE(x.total_market_value, 0) -
          COALESCE(x.total_cost_basis, 0), 2)                        AS total_unrealized_pl
FROM users u
LEFT JOIN portfolios p ON p.user_id = u.user_id
LEFT JOIN (
        SELECT p2.user_id,
               COUNT(*)                      AS position_count,
               SUM(h.quantity * s.current_price)             AS total_market_value,
               SUM(h.quantity * h.average_cost_per_unit)      AS total_cost_basis
        FROM holdings h
        JOIN stocks s     ON s.stock_id     = h.stock_id
        JOIN portfolios p2 ON p2.portfolio_id = h.portfolio_id
        GROUP BY p2.user_id
     ) x ON x.user_id = u.user_id
GROUP BY u.user_id, u.username, u.email,
         x.position_count, x.total_market_value, x.total_cost_basis;

-- -----------------------------------------------------------------------------
-- v_portfolio_performance
--   One row per snapshot with the previous snapshot's value, the absolute
--   change, and the percent change (NULL for a portfolio's first snapshot).
--   The "previous" snapshot is the latest snapshot dated strictly before the
--   current row, whatever the snapshot frequency.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_portfolio_performance AS
SELECT
    ps.snapshot_id,
    ps.portfolio_id,
    p.portfolio_name,
    p.user_id,
    ps.snapshot_date,
    ps.holdings_count,
    ps.total_cost_basis,
    ps.total_market_value,
    prev.total_market_value AS previous_market_value,
    CASE
        WHEN prev.total_market_value IS NULL THEN NULL
        ELSE ROUND(ps.total_market_value - prev.total_market_value, 2)
    END AS change_value,
    CASE
        WHEN prev.total_market_value IS NULL OR prev.total_market_value = 0 THEN NULL
        ELSE ROUND(100 * (ps.total_market_value - prev.total_market_value)
                        / prev.total_market_value, 2)
    END AS change_percent
FROM portfolio_snapshots ps
JOIN portfolios p ON p.portfolio_id = ps.portfolio_id
LEFT JOIN portfolio_snapshots prev
       ON prev.portfolio_id = ps.portfolio_id
      AND prev.snapshot_date = (
            SELECT MAX(ps2.snapshot_date)
            FROM portfolio_snapshots ps2
            WHERE ps2.portfolio_id = ps.portfolio_id
              AND ps2.snapshot_date < ps.snapshot_date
          );

-- -----------------------------------------------------------------------------
-- v_holdings_reconciliation
--   Compares the STORED holdings against holdings DERIVED from the
--   transaction log (SUM of buys minus sells, per portfolio and stock).
--
--   Under normal operation this view returns ZERO rows. A non-empty result
--   means holdings and transactions have drifted out of sync (e.g. someone
--   wrote rows directly instead of using sp_record_transaction).
--   The seed materializes holdings via sp_rebuild_holdings precisely so
--   this view starts empty, and the test suite asserts it stays empty.
--
--   Row meanings:
--     stored_quantity IS NULL, derived_quantity <> 0
--                                  -> transactions exist but no holding row
--     stored_quantity IS NULL, derived_quantity = 0
--                                  -> NOT flagged: a completed full sell-out
--                                     (log nets to zero; the holding row was
--                                     correctly removed by the procedure)
--     derived_quantity IS NULL     -> holding row exists without any
--                                     transactions (impossible via procedures)
--     both present                 -> quantities disagree
--   A derived_quantity of 0 with a stored row is also flagged (a full
--   sell-out must remove the holding row).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_holdings_reconciliation AS
SELECT
    COALESCE(d.portfolio_id, h.portfolio_id) AS portfolio_id,
    COALESCE(d.stock_id, h.stock_id)         AS stock_id,
    d.derived_quantity,
    h.quantity AS stored_quantity,
    ROUND(COALESCE(d.derived_quantity, 0) - COALESCE(h.quantity, 0), 4)
        AS quantity_difference
FROM (
        SELECT portfolio_id,
               stock_id,
               SUM(CASE WHEN transaction_type = 'BUY' THEN quantity
                        ELSE -quantity END) AS derived_quantity
        FROM transactions
        GROUP BY portfolio_id, stock_id
     ) d
LEFT JOIN holdings h
       ON h.portfolio_id = d.portfolio_id
      AND h.stock_id     = d.stock_id
WHERE (h.holding_id IS NULL AND ROUND(d.derived_quantity, 4) <> 0)
   OR ROUND(d.derived_quantity, 4) <> ROUND(h.quantity, 4)
UNION
SELECT
    h2.portfolio_id,
    h2.stock_id,
    NULL AS derived_quantity,
    h2.quantity AS stored_quantity,
    h2.quantity AS quantity_difference
FROM holdings h2
LEFT JOIN (
        SELECT portfolio_id, stock_id
        FROM transactions
        GROUP BY portfolio_id, stock_id
     ) t2
       ON t2.portfolio_id = h2.portfolio_id
      AND t2.stock_id     = h2.stock_id
WHERE t2.portfolio_id IS NULL;
