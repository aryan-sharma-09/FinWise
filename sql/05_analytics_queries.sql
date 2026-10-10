-- =============================================================================
--  FinWise - 05_analytics_queries.sql
--
--  Purpose : A documented library of read-only reference queries that
--            demonstrate the SQL concepts required by the project through
--            meaningful, FinWise-relevant questions. Members 2-4 can copy
--            these as starting points for their components.
--  Requires: The full seed (04_seed_data.sql) loaded.
--  Safety  : SELECT-only. Nothing here modifies data.
--
--  How to run
--    mysql -u root -p finwise < sql/05_analytics_queries.sql
--  or paste individual queries into any client (Workbench, mysql CLI).
--
--  NOTE ON DATA
--  All figures computed from ILLUSTRATIVE synthetic sample data. They are
--  educational examples only - not live market data or advice.
--
--  Concepts demonstrated (query number)
--    01  INNER JOIN (multi-table)          09  IN + subquery (aggregation)
--    02  LEFT JOIN + IS NULL (anti-join)   10  NOT EXISTS (anti-join)
--    03  LEFT JOIN + aggregate             11  EXISTS (semi-join)
--    04  GROUP BY + SUM/COUNT/AVG          12  Window: RANK() OVER
--    05  GROUP BY + HAVING                 13  Window: SUM() OVER (running total)
--    06  HAVING on a view (concentration)  14  CTE + CASE categorization
--    07  Scalar subquery                   15  Date functions + GROUP BY
--    08  Correlated subquery               16  Window: LAG() (period returns)
-- =============================================================================

USE finwise;

-- -----------------------------------------------------------------------------
-- 01. INNER JOIN across four tables: every current position with owner,
--     portfolio, stock, and sector details. (INNER JOIN, multi-table join)
-- -----------------------------------------------------------------------------
SELECT
    u.username,
    p.portfolio_name,
    s.ticker_symbol,
    sec.sector_name,
    h.quantity,
    h.average_cost_per_unit,
    s.current_price
FROM holdings h
JOIN portfolios p ON p.portfolio_id = h.portfolio_id
JOIN users u      ON u.user_id       = p.user_id
JOIN stocks s     ON s.stock_id      = h.stock_id
JOIN sectors sec  ON sec.sector_id  = s.sector_id
ORDER BY u.username, p.portfolio_name, s.ticker_symbol;

-- -----------------------------------------------------------------------------
-- 02. LEFT JOIN + IS NULL: users who own NO portfolio.
--     (LEFT JOIN anti-join pattern)
-- -----------------------------------------------------------------------------
SELECT u.user_id, u.username, u.email
FROM users u
LEFT JOIN portfolios p ON p.user_id = u.user_id
WHERE p.portfolio_id IS NULL;

-- -----------------------------------------------------------------------------
-- 03. LEFT JOIN + COUNT: sectors and how many stocks they contain, INCLUDING
--     sectors with zero stocks. (LEFT JOIN with aggregate; note COUNT(s.stock_id)
--     counts only non-NULL matches, while COUNT(*) would count empty sectors
--     as 1)
-- -----------------------------------------------------------------------------
SELECT sec.sector_name,
       COUNT(s.stock_id) AS stocks_in_sector,
       ROUND(AVG(s.current_price), 2) AS avg_price
FROM sectors sec
LEFT JOIN stocks s ON s.sector_id = sec.sector_id
GROUP BY sec.sector_id, sec.sector_name
ORDER BY stocks_in_sector DESC, sec.sector_name;

-- -----------------------------------------------------------------------------
-- 04. GROUP BY + aggregation: total market value and position count per user,
--     via the v_user_summary contract view. (GROUP BY, SUM, COALESCE)
-- -----------------------------------------------------------------------------
SELECT username,
       portfolio_count,
       position_count,
       total_market_value,
       total_cost_basis,
       total_unrealized_pl
FROM v_user_summary
ORDER BY total_market_value DESC;

-- -----------------------------------------------------------------------------
-- 05. GROUP BY + HAVING: users who own MORE THAN ONE portfolio.
--     (aggregation + HAVING filter on grouped result)
-- -----------------------------------------------------------------------------
SELECT u.username, COUNT(p.portfolio_id) AS portfolio_count
FROM users u
JOIN portfolios p ON p.user_id = u.user_id
GROUP BY u.user_id, u.username
HAVING COUNT(p.portfolio_id) > 1
ORDER BY portfolio_count DESC;

-- -----------------------------------------------------------------------------
-- 06. HAVING on a view: sector CONCENTRATION alert - any (portfolio, sector)
--     pair that makes up more than 25% of the portfolio's value.
--     (HAVING on an aggregated view)
-- -----------------------------------------------------------------------------
SELECT portfolio_name, sector_name,
       sector_value,
       sector_weight_percent
FROM v_sector_allocation
WHERE sector_weight_percent > 25
ORDER BY sector_weight_percent DESC;

-- -----------------------------------------------------------------------------
-- 07. Scalar subquery: portfolios whose current market value is above the
--     AVERAGE portfolio value across the whole platform.
--     (scalar subquery in WHERE)
-- -----------------------------------------------------------------------------
SELECT p.portfolio_id, p.portfolio_name, u.username,
       ROUND(SUM(h.quantity * s.current_price), 2) AS market_value
FROM portfolios p
JOIN users u     ON u.user_id      = p.user_id
JOIN holdings h  ON h.portfolio_id = p.portfolio_id
JOIN stocks s    ON s.stock_id    = h.stock_id
GROUP BY p.portfolio_id, p.portfolio_name, u.username
HAVING SUM(h.quantity * s.current_price) >
       (SELECT AVG(total_value)
        FROM (SELECT SUM(h2.quantity * s2.current_price) AS total_value
              FROM holdings h2
              JOIN stocks s2 ON s2.stock_id = h2.stock_id
              GROUP BY h2.portfolio_id) AS all_portfolios)
ORDER BY market_value DESC;

-- -----------------------------------------------------------------------------
-- 08. Correlated subquery: stocks whose illustrative price is above the
--     average price of their OWN sector. (correlated subquery - the inner
--     query references the outer row's sector)
-- -----------------------------------------------------------------------------
SELECT s1.ticker_symbol, s1.company_name, sec.sector_name, s1.current_price,
       (SELECT ROUND(AVG(s2.current_price), 2)
        FROM stocks s2
        WHERE s2.sector_id = s1.sector_id) AS sector_avg_price
FROM stocks s1
JOIN sectors sec ON sec.sector_id = s1.sector_id
WHERE s1.current_price >
      (SELECT AVG(s2.current_price)
       FROM stocks s2
       WHERE s2.sector_id = s1.sector_id)
ORDER BY s1.current_price DESC;

-- -----------------------------------------------------------------------------
-- 09. IN + aggregation subquery: stocks held in AT LEAST 3 different
--     portfolios. (IN with a subquery over a GROUP BY result)
-- -----------------------------------------------------------------------------
SELECT s.ticker_symbol, s.company_name, sec.sector_name, s.current_price
FROM stocks s
JOIN sectors sec ON sec.sector_id = s.sector_id
WHERE s.stock_id IN (
        SELECT h.stock_id
        FROM holdings h
        GROUP BY h.stock_id
        HAVING COUNT(DISTINCT h.portfolio_id) >= 3
     )
ORDER BY s.ticker_symbol;

-- -----------------------------------------------------------------------------
-- 10. NOT EXISTS: stocks in the catalog that have NEVER been traded by any
--     portfolio (no transaction and no holding).
--     (NOT EXISTS anti-join - the canonical way to express "no matching rows")
-- -----------------------------------------------------------------------------
SELECT s.ticker_symbol, s.company_name, sec.sector_name
FROM stocks s
JOIN sectors sec ON sec.sector_id = s.sector_id
WHERE NOT EXISTS (SELECT 1 FROM transactions t WHERE t.stock_id = s.stock_id)
  AND NOT EXISTS (SELECT 1 FROM holdings  h WHERE h.stock_id  = s.stock_id)
ORDER BY s.ticker_symbol;

-- -----------------------------------------------------------------------------
-- 11. EXISTS: portfolios that contain at least one DIVIDEND-PAYING stock
--     (dividend_yield is not NULL). Note how NULL handling matters here:
--     a plain WHERE dividend_yield > 0 would silently drop NULL rows, which
--     is the same set in practice but EXISTS states the intent explicitly.
--     (EXISTS semi-join + NULL-aware filtering)
-- -----------------------------------------------------------------------------
SELECT DISTINCT p.portfolio_id, p.portfolio_name, u.username
FROM portfolios p
JOIN users u    ON u.user_id      = p.user_id
JOIN holdings h ON h.portfolio_id = p.portfolio_id
JOIN stocks s   ON s.stock_id     = h.stock_id
WHERE EXISTS (SELECT 1
              FROM holdings h2
              JOIN stocks s2 ON s2.stock_id = h2.stock_id
              WHERE h2.portfolio_id = p.portfolio_id
                AND s2.dividend_yield IS NOT NULL)
ORDER BY p.portfolio_name;

-- -----------------------------------------------------------------------------
-- 12. Window function RANK(): the top 3 positions by weight WITHIN each
--     portfolio. (RANK() OVER partition window; compare with query 09, which
--     needed GROUP BY + HAVING to answer a similar-sounding question)
-- -----------------------------------------------------------------------------
SELECT portfolio_name, ticker_symbol, market_value, portfolio_weight_percent,
       RANK() OVER (PARTITION BY portfolio_id
                    ORDER BY market_value DESC) AS weight_rank_in_portfolio
FROM v_portfolio_positions
ORDER BY portfolio_id, weight_rank_in_portfolio;

-- -----------------------------------------------------------------------------
-- 13. Window function SUM() OVER: a RUNNING TOTAL of capital invested per
--     portfolio over time, from the transaction log.
--     (window aggregate with ORDER BY - a running sum without a self-join)
-- -----------------------------------------------------------------------------
SELECT p.portfolio_name,
       s.ticker_symbol,
       t.transaction_type,
       t.quantity,
       t.price_per_unit,
       t.transaction_date,
       ROUND(SUM(CASE WHEN t.transaction_type = 'BUY'
                      THEN t.quantity * t.price_per_unit ELSE 0 END)
             OVER (PARTITION BY t.portfolio_id
                   ORDER BY t.transaction_date, t.transaction_id), 2)
           AS running_invested_capital
FROM transactions t
JOIN portfolios p ON p.portfolio_id = t.portfolio_id
JOIN stocks s    ON s.stock_id     = t.stock_id
WHERE t.portfolio_id = 1
ORDER BY t.transaction_date, t.transaction_id;

-- -----------------------------------------------------------------------------
-- 14. CTE + CASE: a one-page diversification report per portfolio - sector
--     weights bucketed into concentration labels with a computed risk note.
--     (Common Table Expression, CASE expression, string output)
-- -----------------------------------------------------------------------------
WITH sector_weights AS (
    SELECT portfolio_id,
           portfolio_name,
           sector_name,
           sector_weight_percent
    FROM v_sector_allocation
)
SELECT portfolio_name,
       sector_name,
       sector_weight_percent,
       CASE
           WHEN sector_weight_percent >= 50 THEN 'Very concentrated'
           WHEN sector_weight_percent >= 30 THEN 'Concentrated'
           WHEN sector_weight_percent >= 15 THEN 'Moderate'
           ELSE 'Diversified'
       END AS concentration_label
FROM sector_weights
ORDER BY portfolio_name, sector_weight_percent DESC;

-- -----------------------------------------------------------------------------
-- 15. Date functions + GROUP BY: monthly trading activity across the whole
--     platform (transaction count and capital moved per month).
--     (YEAR(), MONTH(), DATE_FORMAT, aggregation)
-- -----------------------------------------------------------------------------
SELECT YEAR(t.transaction_date)                              AS trade_year,
       DATE_FORMAT(t.transaction_date, '%Y-%m')              AS trade_month,
       COUNT(*)                                             AS transaction_count,
       COUNT(DISTINCT t.portfolio_id)                        AS active_portfolios,
       ROUND(SUM(t.quantity * t.price_per_unit), 2)          AS capital_moved
FROM transactions t
GROUP BY YEAR(t.transaction_date), DATE_FORMAT(t.transaction_date, '%Y-%m')
ORDER BY trade_year, trade_month;

-- -----------------------------------------------------------------------------
-- 16. Window function LAG(): month-over-month change of a portfolio's total
--     value directly from the snapshots (independent of the
--     v_portfolio_performance view, which uses a correlated subquery).
--     (LAG() OVER partition - the classic "compare to previous row" pattern)
-- -----------------------------------------------------------------------------
SELECT portfolio_id,
       snapshot_date,
       total_market_value,
       LAG(total_market_value) OVER (PARTITION BY portfolio_id
                                     ORDER BY snapshot_date) AS previous_value,
       ROUND(total_market_value -
             LAG(total_market_value) OVER (PARTITION BY portfolio_id
                                           ORDER BY snapshot_date), 2) AS change_value
FROM portfolio_snapshots
WHERE portfolio_id = 1
ORDER BY snapshot_date;

-- =============================================================================
--  End of analytics queries.
--  Reminder: values are computed from illustrative sample data only.
-- =============================================================================
