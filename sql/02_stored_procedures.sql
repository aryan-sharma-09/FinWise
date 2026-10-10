-- =============================================================================
--  FinWise - 02_stored_procedures.sql
--
--  Purpose : Stored procedures that form the WRITE side of the database
--            contract. Application code (Python included) must change
--            holdings / transactions / snapshots ONLY through these
--            procedures.
--  Requires: MySQL 8.0.16 or newer.
--  Safety  : All procedures validate their input, run inside explicit
--            transactions, and roll back completely on any error, so a
--            rejected operation leaves neither a partial transaction row
--            nor a partial holding update.
--
--  Contents
--    sp_record_transaction  - the only sanctioned way to BUY or SELL.
--    sp_create_snapshot    - idempotent daily portfolio valuation snapshot.
--    sp_rebuild_holdings   - replays the transaction log to reconstruct
--                            holdings (used by the seed and tests).
--
--  NOTE on error handling
--    Each procedure declares an EXIT HANDLER FOR SQLEXCEPTION that performs
--    ROLLBACK and then RESIGNALs, so the client sees the original error
--    message and the database keeps no partial state.
--
--  NOTE on concurrency
--    sp_record_transaction locks the parent portfolio row (SELECT ... FOR
--    UPDATE) for the duration of the transaction. This serializes all
--    writes affecting the same portfolio, which prevents lost updates when
--    two sessions trade in the same portfolio at the same time. Writes to
--    different portfolios proceed in parallel.
-- =============================================================================

DELIMITER $$

-- -----------------------------------------------------------------------------
-- sp_record_transaction
--   Records a BUY or SELL atomically and maintains the portfolio holding
--   with the weighted-average cost method.
--
--   Validation (rejected operations change NOTHING):
--     - transaction_type must be 'BUY' or 'SELL'
--     - quantity and price_per_unit must be strictly positive
--     - transaction_date must not be NULL
--     - portfolio and stock must exist
--     - SELL requires an existing holding and quantity <= held quantity
--
--   Cost basis rules (weighted-average method):
--     BUY : new_avg = (held_qty * held_avg + qty * price) / (held_qty + qty)
--           rounded to 2 decimal places.
--     SELL: average cost per unit stays unchanged; the holding's quantity is
--           reduced. Selling the full position DELETEs the holding row
--           (holdings never store zero or negative quantities).
--
--   OUT p_transaction_id receives the id of the inserted transaction row.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_record_transaction (
    IN  p_portfolio_id     INT UNSIGNED,
    IN  p_stock_id         INT UNSIGNED,
    IN  p_transaction_type VARCHAR(10),
    IN  p_quantity         DECIMAL(12,4),
    IN  p_price_per_unit   DECIMAL(12,2),
    IN  p_transaction_date DATETIME,
    IN  p_notes            VARCHAR(255),
    OUT p_transaction_id   INT UNSIGNED
)
proc: BEGIN
    DECLARE v_exists         INT UNSIGNED DEFAULT 0;
    DECLARE v_held_quantity  DECIMAL(12,4);
    DECLARE v_avg_cost       DECIMAL(12,2);
    DECLARE v_new_avg_cost   DECIMAL(12,4);

    -- Any SQL error (including the SIGNALs below) rolls back everything
    -- and re-raises the original message to the client.
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    -- ---- Input validation (before any data is touched) ---------------------
    IF p_transaction_type IS NULL OR p_transaction_type NOT IN ('BUY', 'SELL') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Invalid transaction type: must be BUY or SELL';
    END IF;

    IF p_quantity IS NULL OR p_quantity <= 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Quantity must be greater than zero';
    END IF;

    IF p_price_per_unit IS NULL OR p_price_per_unit <= 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Price per unit must be greater than zero';
    END IF;

    IF p_transaction_date IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Transaction date is required';
    END IF;

    SELECT COUNT(*) INTO v_exists FROM portfolios
     WHERE portfolio_id = p_portfolio_id;
    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Portfolio does not exist';
    END IF;

    SELECT COUNT(*) INTO v_exists FROM stocks
     WHERE stock_id = p_stock_id;
    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Stock does not exist';
    END IF;

    -- ---- Atomic mutation ----------------------------------------------------
    START TRANSACTION;

    -- Lock the parent portfolio row: serializes concurrent writes that
    -- target the same portfolio (see header notes).
    SELECT portfolio_id INTO v_exists FROM portfolios
     WHERE portfolio_id = p_portfolio_id
     FOR UPDATE;

    INSERT INTO transactions
        (portfolio_id, stock_id, transaction_type, quantity,
         price_per_unit, transaction_date, notes)
    VALUES
        (p_portfolio_id, p_stock_id, p_transaction_type, p_quantity,
         p_price_per_unit, p_transaction_date, p_notes);

    SET p_transaction_id = LAST_INSERT_ID();

    SELECT COUNT(*) INTO v_exists FROM holdings
     WHERE portfolio_id = p_portfolio_id
       AND stock_id     = p_stock_id;

    IF p_transaction_type = 'BUY' THEN
        IF v_exists = 0 THEN
            -- First purchase of this stock: cost basis is the buy price.
            INSERT INTO holdings (portfolio_id, stock_id, quantity, average_cost_per_unit)
            VALUES (p_portfolio_id, p_stock_id, p_quantity, p_price_per_unit);
        ELSE
            SELECT quantity, average_cost_per_unit
              INTO v_held_quantity, v_avg_cost
              FROM holdings
             WHERE portfolio_id = p_portfolio_id
               AND stock_id     = p_stock_id
             FOR UPDATE;

            SET v_new_avg_cost =
                (v_held_quantity * v_avg_cost + p_quantity * p_price_per_unit)
                / (v_held_quantity + p_quantity);

            UPDATE holdings
               SET quantity              = quantity + p_quantity,
                   average_cost_per_unit = ROUND(v_new_avg_cost, 2)
             WHERE portfolio_id = p_portfolio_id
               AND stock_id     = p_stock_id;
        END IF;
    ELSE
        -- SELL
        IF v_exists = 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Cannot sell: no holdings of this stock in this portfolio';
        END IF;

        SELECT quantity, average_cost_per_unit
          INTO v_held_quantity, v_avg_cost
          FROM holdings
         WHERE portfolio_id = p_portfolio_id
           AND stock_id     = p_stock_id
         FOR UPDATE;

        IF p_quantity > v_held_quantity THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Cannot sell: quantity exceeds current holdings';
        END IF;

        IF v_held_quantity - p_quantity = 0 THEN
            -- Full exit: remove the row (invariant: never store qty = 0).
            DELETE FROM holdings
             WHERE portfolio_id = p_portfolio_id
               AND stock_id     = p_stock_id;
        ELSE
            -- Average cost per unit is unchanged by a sale.
            UPDATE holdings
               SET quantity = quantity - p_quantity
             WHERE portfolio_id = p_portfolio_id
               AND stock_id     = p_stock_id;
        END IF;
    END IF;

    COMMIT;
END proc$$


-- -----------------------------------------------------------------------------
-- sp_create_snapshot
--   Computes the portfolio's market value and cost basis from its current
--   holdings x current illustrative prices and stores one snapshot row for
--   the given date. Calling it twice for the same (portfolio, date) updates
--   the existing row (idempotent upsert) instead of failing.
--
--   A portfolio with no holdings is snapshotted with zeros, which is a valid
--   historical record ("portfolio existed but was empty").
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_create_snapshot (
    IN  p_portfolio_id  INT UNSIGNED,
    IN  p_snapshot_date DATE
)
BEGIN
    DECLARE v_exists INT UNSIGNED DEFAULT 0;
    DECLARE v_value  DECIMAL(16,2) DEFAULT 0;
    DECLARE v_cost   DECIMAL(16,2) DEFAULT 0;
    DECLARE v_count  INT UNSIGNED  DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SELECT COUNT(*) INTO v_exists FROM portfolios
     WHERE portfolio_id = p_portfolio_id;
    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Portfolio does not exist';
    END IF;

    IF p_snapshot_date IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Snapshot date is required';
    END IF;

    START TRANSACTION;

    SELECT COALESCE(SUM(h.quantity * s.current_price), 0),
           COALESCE(SUM(h.quantity * h.average_cost_per_unit), 0),
           COUNT(*)
      INTO v_value, v_cost, v_count
      FROM holdings h
      JOIN stocks s ON s.stock_id = h.stock_id
     WHERE h.portfolio_id = p_portfolio_id;

    UPDATE portfolio_snapshots
       SET total_market_value = v_value,
           total_cost_basis   = v_cost,
           holdings_count     = v_count
     WHERE portfolio_id  = p_portfolio_id
       AND snapshot_date = p_snapshot_date;

    IF ROW_COUNT() = 0 THEN
        INSERT INTO portfolio_snapshots
            (portfolio_id, snapshot_date, total_market_value, total_cost_basis, holdings_count)
        VALUES
            (p_portfolio_id, p_snapshot_date, v_value, v_cost, v_count);
    END IF;

    COMMIT;
END$$


-- -----------------------------------------------------------------------------
-- sp_rebuild_holdings
--   Reconstructs the holdings of one portfolio by replaying its entire
--   transaction history in (stock, date, id) order, applying exactly the
--   same weighted-average cost rules as sp_record_transaction.
--
--   Uses: (1) the seed script fabricates history first, then materializes
--             holdings with this procedure, guaranteeing the two tables are
--             consistent by construction;
--         (2) the test suite proves replaying history reproduces the
--             maintained holdings bit-for-bit;
--         (3) disaster recovery if a holdings row is ever damaged.
--
--   The procedure DELETEs the portfolio's existing holdings first and runs
--   inside one transaction, so a failure restores the previous state.
-- -----------------------------------------------------------------------------
CREATE PROCEDURE sp_rebuild_holdings (
    IN  p_portfolio_id INT UNSIGNED
)
BEGIN
    DECLARE v_exists   INT UNSIGNED  DEFAULT 0;
    DECLARE v_done     INT           DEFAULT 0;
    DECLARE v_tx_stock INT UNSIGNED;
    DECLARE v_tx_type  VARCHAR(10);
    DECLARE v_tx_qty   DECIMAL(12,4);
    DECLARE v_tx_price DECIMAL(12,2);
    DECLARE v_cur_stock INT UNSIGNED DEFAULT NULL;
    DECLARE v_qty      DECIMAL(12,4) DEFAULT 0;
    DECLARE v_avg      DECIMAL(12,2) DEFAULT 0;

    DECLARE cur_tx CURSOR FOR
        SELECT stock_id, transaction_type, quantity, price_per_unit
          FROM transactions
         WHERE portfolio_id = p_portfolio_id
         ORDER BY stock_id, transaction_date, transaction_id;

    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SELECT COUNT(*) INTO v_exists FROM portfolios
     WHERE portfolio_id = p_portfolio_id;
    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Portfolio does not exist';
    END IF;

    START TRANSACTION;

    DELETE FROM holdings
     WHERE portfolio_id = p_portfolio_id;

    OPEN cur_tx;

    read_loop: LOOP
        FETCH cur_tx INTO v_tx_stock, v_tx_type, v_tx_qty, v_tx_price;
        IF v_done = 1 THEN
            LEAVE read_loop;
        END IF;

        -- When the replay moves to a different stock, flush the previous run.
        IF v_cur_stock IS NULL OR v_tx_stock <> v_cur_stock THEN
            IF v_cur_stock IS NOT NULL AND v_qty > 0 THEN
                INSERT INTO holdings (portfolio_id, stock_id, quantity, average_cost_per_unit)
                VALUES (p_portfolio_id, v_cur_stock, v_qty, v_avg);
            END IF;
            SET v_cur_stock = v_tx_stock,
                v_qty        = 0,
                v_avg        = 0;
        END IF;

        IF v_tx_type = 'BUY' THEN
            SET v_avg = ROUND((v_qty * v_avg + v_tx_qty * v_tx_price)
                              / (v_qty + v_tx_qty), 2),
                v_qty = v_qty + v_tx_qty;
        ELSE
            -- Sale: average cost per unit is unchanged.
            SET v_qty = v_qty - v_tx_qty;
        END IF;
    END LOOP;

    CLOSE cur_tx;

    -- Flush the final stock run.
    IF v_cur_stock IS NOT NULL AND v_qty > 0 THEN
        INSERT INTO holdings (portfolio_id, stock_id, quantity, average_cost_per_unit)
        VALUES (p_portfolio_id, v_cur_stock, v_qty, v_avg);
    END IF;

    COMMIT;
END$$

DELIMITER ;
