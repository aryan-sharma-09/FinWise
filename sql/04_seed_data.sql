-- =============================================================================
--  FinWise - 04_seed_data.sql
--
--  Purpose : Deterministic, synthetic sample data for demos, testing, and
--            the analytics queries in 05_analytics_queries.sql.
--  Requires: MySQL 8.0.16 or newer, and 02_stored_procedures.sql loaded.
--
--  !! WARNING - WIPES AND RELOADS SAMPLE DATA !!
--  This script TRUNCATEs all seven tables and re-inserts the seed. It does
--  not drop the schema (run 01_schema.sql for that). Safe to re-run.
--
--  DATA PROVENANCE - IMPORTANT
--  - Every person in this file is FICTIONAL (usernames, names, and
--    @finwise.example emails). No private financial information is used.
--  - Ticker symbols are recognizable PUBLIC companies, but every price,
--    market cap, P/E, dividend yield, portfolio, transaction, and snapshot
--    value is a SYNTHETIC ILLUSTRATIVE number invented for this project.
--    They are NOT live or historical market data and must never be
--    presented as such (see README disclaimer).
--  - All values are fixed literals (no randomness), so the database is
--    identical every time this script runs.
--
--  HOW HOLDINGS ARE MATERIALIZED
--  This script inserts the transaction history DIRECTLY (it fabricates
--  history, which application code must never do) and then calls
--  sp_rebuild_holdings for each portfolio. The procedure replays the
--  transactions with the same weighted-average cost rules used by
--  sp_record_transaction, so holdings and transactions are consistent BY
--  CONSTRUCTION and v_holdings_reconciliation is empty after seeding.
--
--  HOW SNAPSHOTS ARE SEEDED
--  - Historical snapshots (dates 2025-10-10 .. 2026-09-10) are inserted
--    directly as ILLUSTRATIVE point-in-time records. They intentionally
--    cannot be re-derived from the seven-table core, because stocks stores
--    a single illustrative current price (see docs/database_contract.md;
--    a future stock_prices extension would enable true reconstruction).
--  - The LATEST snapshot (2026-10-10, the stocks' price_as_of date) is
--    created with sp_create_snapshot, so it is computed from the seeded
--    holdings x current prices and is internally consistent.
--
--  DATA SHAPE
--    6 users (two without portfolios, for LEFT JOIN demos)
--    8 sectors, 26 stocks
--    7 portfolios: 3 users own 1, one owns 3, one owns 2 (HAVING demos)
--    48 transactions over ~13 months (buys, partial sells, one full exit)
--    45 handcrafted historical snapshots + 7 computed current snapshots
--    Snapshot frequency: monthly for portfolios 1, 2, 4; quarterly for 3,
--    5, 6, 7 (mixed cadence is realistic and demonstrates LAG-style views).
-- =============================================================================

USE finwise;

-- Wipe and reset. TRUNCATE also resets AUTO_INCREMENT so ids are
-- deterministic (users 1-6, sectors 1-8, stocks 1-26, portfolios 1-7).
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE portfolio_snapshots;
TRUNCATE TABLE transactions;
TRUNCATE TABLE holdings;
TRUNCATE TABLE portfolios;
TRUNCATE TABLE stocks;
TRUNCATE TABLE sectors;
TRUNCATE TABLE users;
SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
--  users - all fictional (see header)
-- =============================================================================
INSERT INTO users (user_id, username, email, full_name, created_at) VALUES
 (1, 'aarav_mehta',   'aarav.mehta@finwise.example',   'Aarav Mehta',   '2025-08-15 09:00:00'),
 (2, 'priya_patel',   'priya.patel@finwise.example',   'Priya Patel',   '2025-08-20 10:30:00'),
 (3, 'diego_ramirez', 'diego.ramirez@finwise.example', 'Diego Ramirez', '2025-09-01 11:15:00'),
 (4, 'sara_khan',     'sara.khan@finwise.example',     'Sara Khan',     '2025-09-05 14:45:00'),
 (5, 'li_wei',        'li.wei@finwise.example',        'Wei Li',        '2025-09-10 16:20:00'),
 (6, 'emma_johnson',  'emma.johnson@finwise.example',  'Emma Johnson',  '2025-10-01 08:40:00');
-- Users 5 and 6 (li_wei, emma_johnson) intentionally own no portfolios,
-- to demonstrate LEFT JOIN and v_user_summary behavior.

-- =============================================================================
--  sectors - GICS-inspired reference list
-- =============================================================================
INSERT INTO sectors (sector_id, sector_name, description) VALUES
 (1, 'Technology',            'Software, semiconductors, hardware, and internet services.'),
 (2, 'Financials',            'Banks, payment networks, insurers, and capital markets firms.'),
 (3, 'Health Care',           'Pharmaceuticals, insurers, and medical product companies.'),
 (4, 'Consumer Discretionary', 'Retail, e-commerce, apparel, and discretionary goods and services.'),
 (5, 'Consumer Staples',      'Everyday essentials such as beverages, household products, and groceries.'),
 (6, 'Energy',                'Oil, gas, and integrated energy producers.'),
 (7, 'Industrials',           'Aerospace, machinery, and industrial manufacturing.'),
 (8, 'Utilities',             'Electric and multi-utility companies.');

-- =============================================================================
--  stocks - real public tickers, ILLUSTRATIVE synthetic values.
--  Every figure below is invented for this project. price_as_of marks the
--  date the illustrative prices represent. pe_ratio is NULL for companies
--  portrayed as loss-making (PFE, BA) to demonstrate NULL handling.
--  market_cap_millions is in millions of US dollars.
-- =============================================================================
INSERT INTO stocks (stock_id, ticker_symbol, company_name, sector_id, current_price,
                    market_cap_millions, pe_ratio, dividend_yield, price_as_of) VALUES
 (1,  'AAPL',  'Apple Inc.',                    1, 245.50, 3600000.00,  28.40, NULL,   '2026-10-10'),
 (2,  'MSFT',  'Microsoft Corporation',         1, 470.25, 3500000.00,  33.10, 0.75,  '2026-10-10'),
 (3,  'NVDA',  'NVIDIA Corporation',            1, 138.75, 3400000.00,  45.20, NULL,   '2026-10-10'),
 (4,  'GOOGL', 'Alphabet Inc.',                 1, 205.40, 2500000.00,  24.60, NULL,   '2026-10-10'),
 (5,  'META',  'Meta Platforms Inc.',           1, 605.80, 1500000.00,  22.30, NULL,   '2026-10-10'),
 (6,  'JPM',   'JPMorgan Chase and Co.',        2, 262.30,  740000.00,  14.80, 2.05,  '2026-10-10'),
 (7,  'V',     'Visa Inc.',                     2, 348.60,  680000.00,  31.20, 0.72,  '2026-10-10'),
 (8,  'BAC',   'Bank of America Corp.',         2,  48.75,  370000.00,  13.50, 2.30,  '2026-10-10'),
 (9,  'JNJ',   'Johnson and Johnson',           3, 168.20,  405000.00,  15.60, 3.05,  '2026-10-10'),
 (10, 'UNH',   'UnitedHealth Group Inc.',       3, 585.40,  540000.00,  17.40, 1.55,  '2026-10-10'),
 (11, 'PFE',   'Pfizer Inc.',                   3,  34.10,  193000.00, NULL,  5.85,  '2026-10-10'),
 (12, 'LLY',   'Eli Lilly and Company',         3, 942.60,  895000.00,  62.50, 0.65,  '2026-10-10'),
 (13, 'AMZN',  'Amazon.com Inc.',               4, 228.90, 2400000.00,  38.20, NULL,   '2026-10-10'),
 (14, 'TSLA',  'Tesla Inc.',                   4, 415.35, 1330000.00,  78.40, NULL,   '2026-10-10'),
 (15, 'NKE',   'NIKE Inc.',                     4,  78.45,  118000.00,  19.80, 1.95,  '2026-10-10'),
 (16, 'HD',    'Home Depot Inc.',               4, 392.80,  390000.00,  24.10, 2.15,  '2026-10-10'),
 (17, 'KO',    'Coca-Cola Company',             5,  68.55,  296000.00,  24.90, 2.85,  '2026-10-10'),
 (18, 'PG',    'Procter and Gamble Co.',        5, 172.30,  406000.00,  26.10, 2.45,  '2026-10-10'),
 (19, 'WMT',   'Walmart Inc.',                  5,  98.40,  792000.00,  38.60, 0.90,  '2026-10-10'),
 (20, 'XOM',   'Exxon Mobil Corporation',       6, 118.65,  520000.00,  13.20, 3.25,  '2026-10-10'),
 (21, 'CVX',   'Chevron Corporation',           6, 162.40,  300000.00,  14.60, 4.05,  '2026-10-10'),
 (22, 'BA',    'Boeing Company',                7, 178.55,  134000.00, NULL,  NULL,  '2026-10-10'),
 (23, 'CAT',   'Caterpillar Inc.',             7, 395.20,  190000.00,  16.90, 1.45,  '2026-10-10'),
 (24, 'HON',   'Honeywell International Inc.',  7, 224.75,  146000.00,  23.40, 2.10,  '2026-10-10'),
 (25, 'NEE',   'NextEra Energy Inc.',           8,  83.20,  170000.00,  21.70, 2.95,  '2026-10-10'),
 (26, 'DUK',   'Duke Energy Corporation',       8, 121.90,   94000.00,  19.30, 3.65,  '2026-10-10');

-- =============================================================================
--  portfolios
-- =============================================================================
INSERT INTO portfolios (portfolio_id, user_id, portfolio_name, created_at) VALUES
 (1, 1, 'Long-Term Growth',     '2025-09-01 09:30:00'),
 (2, 1, 'Dividend Income',      '2025-09-18 10:00:00'),
 (3, 1, 'Tech Focus',           '2026-01-10 13:20:00'),
 (4, 2, 'Balanced Core',        '2025-09-28 11:45:00'),
 (5, 2, 'Small Explorations',   '2026-02-15 15:10:00'),
 (6, 3, 'Index-Like Starter',   '2026-01-05 12:00:00'),
 (7, 4, 'Energy and Industrials','2025-12-01 09:50:00');

-- =============================================================================
--  transactions - 48 rows, ILLUSTRATIVE synthetic activity.
--  INSERT order is chronological per portfolio, which is also the replay
--  order used by sp_rebuild_holdings below.
--  Stock ids: 1 AAPL  2 MSFT  3 NVDA  4 GOOGL  5 META  6 JPM  7 V  9 JNJ
--             10 UNH  11 PFE  12 LLY  13 AMZN  14 TSLA  15 NKE  16 HD
--             17 KO  18 PG  19 WMT  20 XOM  21 CVX  22 BA  23 CAT  24 HON
--             25 NEE  26 DUK
-- =============================================================================
INSERT INTO transactions
    (portfolio_id, stock_id, transaction_type, quantity, price_per_unit, transaction_date, notes)
VALUES
 -- Portfolio 1: Long-Term Growth (Aarav) - includes a partial sell (TSLA)
 -- and a FULL EXIT (BA) to demonstrate holding-row deletion.
 (1,  1, 'BUY',  40, 212.30, '2025-09-15 10:15:00', 'Initial position'),
 (1,  2, 'BUY',  25, 415.60, '2025-09-15 10:32:00', 'Initial position'),
 (1,  3, 'BUY',  60, 121.40, '2025-09-16 11:05:00', 'Initial position'),
 (1,  4, 'BUY',  30, 178.25, '2025-10-02 09:50:00', 'Initial position'),
 (1, 13, 'BUY',  20, 198.45, '2025-10-02 10:12:00', 'Initial position'),
 (1, 22, 'BUY',  15, 155.30, '2025-10-28 14:20:00', 'Aerospace recovery thesis'),
 (1, 14, 'BUY',  25, 348.20, '2025-11-05 09:40:00', 'Initial position'),
 (1, 12, 'BUY',   6, 792.50, '2025-11-05 10:05:00', 'Initial position'),
 (1, 19, 'BUY',  35,  86.75, '2025-12-01 11:30:00', 'Defensive balance'),
 (1, 20, 'BUY',  30, 104.90, '2025-12-01 11:48:00', 'Defensive balance'),
 (1, 13, 'BUY',  10, 215.60, '2026-01-20 15:05:00', 'Added on dip'),
 (1, 25, 'BUY',  50,  76.35, '2026-02-09 10:22:00', 'Utilities diversification'),
 (1,  1, 'BUY',  15, 231.80, '2026-03-10 13:40:00', 'Added to winner'),
 (1, 14, 'SELL', 10, 402.75, '2026-04-14 11:15:00', 'Took partial profit'),
 (1,  3, 'BUY',  20, 132.90, '2026-06-11 09:55:00', 'Added to winner'),
 (1, 22, 'SELL', 15, 172.10, '2026-07-22 14:05:00', 'Exited position fully'),

 -- Portfolio 2: Dividend Income (Aarav).
 (2, 17, 'BUY',  80,  62.10, '2025-09-22 10:00:00', 'Income position'),
 (2, 18, 'BUY',  45, 158.90, '2025-09-22 10:25:00', 'Income position'),
 (2,  9, 'BUY',  30, 152.40, '2025-09-23 11:10:00', 'Income position'),
 (2, 20, 'BUY',  40,  99.80, '2025-11-12 09:45:00', 'Energy income'),
 (2, 26, 'BUY',  55, 108.45, '2025-11-12 10:02:00', 'Utility income'),
 (2, 25, 'BUY',  60,  71.90, '2026-02-17 13:30:00', 'Utility income'),
 (2,  9, 'BUY',  10, 160.15, '2026-05-18 10:40:00', 'Added on dip'),
 (2, 17, 'SELL', 10,  66.80, '2026-08-04 15:20:00', 'Trimmed position'),

 -- Portfolio 3: Tech Focus (Aarav) - young portfolio, partial sell of META.
 (3,  2, 'BUY',   8, 428.90, '2026-01-15 10:05:00', 'Initial position'),
 (3,  3, 'BUY',  25, 128.40, '2026-01-15 10:30:00', 'Initial position'),
 (3,  5, 'BUY',  12, 572.30, '2026-03-25 11:20:00', 'Initial position'),
 (3,  5, 'SELL',  4, 598.60, '2026-08-12 14:45:00', 'Took partial profit'),

 -- Portfolio 4: Balanced Core (Priya) - partial sell of PFE.
 (4,  1, 'BUY',  30, 219.75, '2025-10-06 09:35:00', 'Initial position'),
 (4,  6, 'BUY',  25, 238.40, '2025-10-06 09:52:00', 'Initial position'),
 (4,  7, 'BUY',  15, 312.85, '2025-10-07 10:15:00', 'Initial position'),
 (4, 10, 'BUY',   8, 548.20, '2025-10-07 10:31:00', 'Initial position'),
 (4, 17, 'BUY', 100,  64.30, '2025-11-03 11:05:00', 'Initial position'),
 (4, 19, 'BUY',  40,  91.20, '2025-11-03 11:22:00', 'Initial position'),
 (4, 23, 'BUY',  10, 352.60, '2026-02-24 13:10:00', 'Industrial addition'),
 (4, 11, 'BUY', 120,  29.85, '2026-04-07 10:45:00', 'Value opportunity'),
 (4, 11, 'SELL', 40,  31.20, '2026-06-09 14:30:00', 'Trimmed position'),

 -- Portfolio 5: Small Explorations (Priya) - all buys, one losing position.
 (5, 15, 'BUY',  60,  84.20, '2026-03-03 10:20:00', 'Initial position'),
 (5, 16, 'BUY',  15, 368.90, '2026-05-26 11:40:00', 'Initial position'),
 (5, 14, 'BUY',  10, 388.75, '2026-08-25 09:55:00', 'Speculative position'),

 -- Portfolio 6: Index-Like Starter (Diego).
 (6, 19, 'BUY',  25,  89.45, '2026-01-19 10:50:00', 'Initial position'),
 (6,  6, 'BUY',  20, 249.60, '2026-01-19 11:05:00', 'Initial position'),
 (6,  4, 'BUY',  18, 191.30, '2026-04-21 14:20:00', 'Initial position'),
 (6, 18, 'BUY',  30, 165.75, '2026-07-14 10:35:00', 'Initial position'),

 -- Portfolio 7: Energy and Industrials (Sara).
 (7, 20, 'BUY',  45, 108.30, '2025-12-09 09:40:00', 'Initial position'),
 (7, 21, 'BUY',  30, 152.80, '2025-12-09 09:58:00', 'Initial position'),
 (7, 22, 'BUY',  20, 149.75, '2026-03-16 11:15:00', 'Aerospace recovery'),
 (7, 24, 'BUY',  25, 210.40, '2026-06-02 10:30:00', 'Industrial addition');

-- =============================================================================
--  Materialize holdings by replaying the history above (consistent by
--  construction; see header). After these calls v_holdings_reconciliation
--  returns no rows.
-- =============================================================================
CALL sp_rebuild_holdings(1);
CALL sp_rebuild_holdings(2);
CALL sp_rebuild_holdings(3);
CALL sp_rebuild_holdings(4);
CALL sp_rebuild_holdings(5);
CALL sp_rebuild_holdings(6);
CALL sp_rebuild_holdings(7);

-- =============================================================================
--  portfolio_snapshots - ILLUSTRATIVE historical records.
--  These are point-in-time records, NOT values derivable from current data
--  (see header and docs/database_contract.md). Value trajectories were
--  chosen to be plausible against the transaction history above and to end
--  near each portfolio's computed 2026-10-10 value:
--    P1 72,437.10   P2 35,722.50   P3 12,077.15   P4 41,305.70
--    P5 14,752.50   P6 16,572.20   P7 19,401.00
--  Monthly cadence for portfolios 1, 2, 4; quarterly for 3, 5, 6, 7.
-- =============================================================================
INSERT INTO portfolio_snapshots
    (portfolio_id, snapshot_date, total_market_value, total_cost_basis, holdings_count)
VALUES
 -- Portfolio 1: Long-Term Growth (monthly)
 (1, '2025-10-10', 36900.00, 35482.50,  5),
 (1, '2025-11-10', 52300.00, 51272.00,  8),
 (1, '2025-12-10', 58100.00, 57455.25, 10),
 (1, '2026-01-10', 59000.00, 57455.25, 10),
 (1, '2026-02-10', 64200.00, 63428.75, 11),
 (1, '2026-03-10', 67500.00, 66905.75, 11),
 (1, '2026-04-10', 64800.00, 66905.75, 11),
 (1, '2026-05-10', 66100.00, 63423.75, 11),
 (1, '2026-06-10', 68900.00, 63423.75, 11),
 (1, '2026-07-10', 70400.00, 66081.75, 11),
 (1, '2026-08-10', 69200.00, 63752.25, 10),
 (1, '2026-09-10', 71300.00, 63752.25, 10),

 -- Portfolio 2: Dividend Income (monthly)
 (2, '2025-10-10', 17100.00, 16690.50, 3),
 (2, '2025-11-10', 17400.00, 16690.50, 3),
 (2, '2025-12-10', 26900.00, 26647.25, 5),
 (2, '2026-01-10', 27200.00, 26647.25, 5),
 (2, '2026-02-10', 31800.00, 30961.25, 6),
 (2, '2026-03-10', 32100.00, 30961.25, 6),
 (2, '2026-04-10', 31600.00, 30961.25, 6),
 (2, '2026-05-10', 33900.00, 32562.75, 6),
 (2, '2026-06-10', 34600.00, 32562.75, 6),
 (2, '2026-07-10', 35000.00, 32562.75, 6),
 (2, '2026-08-10', 34900.00, 31941.75, 6),
 (2, '2026-09-10', 35400.00, 31941.75, 6),

 -- Portfolio 3: Tech Focus (quarterly; portfolio created 2026-01-10)
 (3, '2026-04-10', 13900.00, 13508.80, 3),
 (3, '2026-07-10', 13200.00, 13508.80, 3),

 -- Portfolio 4: Balanced Core (monthly)
 (4, '2025-10-10', 22100.00, 21630.85, 4),
 (4, '2025-11-10', 32300.00, 31708.85, 6),
 (4, '2025-12-10', 33100.00, 31708.85, 6),
 (4, '2026-01-10', 33800.00, 31708.85, 6),
 (4, '2026-02-10', 34200.00, 31708.85, 6),
 (4, '2026-03-10', 35900.00, 35234.85, 7),
 (4, '2026-04-10', 39800.00, 38816.85, 8),
 (4, '2026-05-10', 38200.00, 38816.85, 8),
 (4, '2026-06-10', 38900.00, 37622.85, 8),
 (4, '2026-07-10', 40100.00, 37622.85, 8),
 (4, '2026-08-10', 40600.00, 37622.85, 8),
 (4, '2026-09-10', 40900.00, 37622.85, 8),

 -- Portfolio 5: Small Explorations (quarterly; created 2026-02-15)
 (5, '2026-04-10',  4900.00,  5052.00, 1),
 (5, '2026-07-10', 11200.00, 10585.50, 2),

 -- Portfolio 6: Index-Like Starter (quarterly; created 2026-01-05)
 (6, '2026-04-10',  7500.00,  7228.25, 2),
 (6, '2026-07-10', 11400.00, 10671.65, 3),

 -- Portfolio 7: Energy and Industrials (quarterly; created 2025-12-01)
 (7, '2026-01-10',  9800.00,  9457.50, 2),
 (7, '2026-04-10', 13100.00, 12452.50, 3),
 (7, '2026-07-10', 18300.00, 17712.50, 4);

-- =============================================================================
--  Latest snapshot (2026-10-10 = price_as_of date): computed from the seeded
--  holdings x current illustrative prices, so it is internally consistent.
-- =============================================================================
CALL sp_create_snapshot(1, '2026-10-10');
CALL sp_create_snapshot(2, '2026-10-10');
CALL sp_create_snapshot(3, '2026-10-10');
CALL sp_create_snapshot(4, '2026-10-10');
CALL sp_create_snapshot(5, '2026-10-10');
CALL sp_create_snapshot(6, '2026-10-10');
CALL sp_create_snapshot(7, '2026-10-10');

-- Expected results after a clean load (handy for sanity checks):
--   users 6 | sectors 8 | stocks 26 | portfolios 7
--   transactions 48 | holdings 38 | portfolio_snapshots 52
--   v_holdings_reconciliation: 0 rows
