-- =============================================================================
--  FinWise - Financial Literacy and Portfolio Risk Analytics Platform
--  00_create_database.sql
--
--  Purpose : Create the FinWise database (schema) with UTF-8 support.
--  Requires: MySQL 8.0.16 or newer (CHECK constraints are enforced 8.0.16+).
--  Safety  : Safe to re-run. Creates the database if missing; never drops
--            or modifies existing data.
--
--  After running this file, the session is using the `finwise` database, so
--  files 01-04 can be sourced in order. (They also work when loaded with:
--    mysql -u root -p finwise < sql/01_schema.sql  ... etc.)
--
--  OPTIONAL - least-privilege application account (recommended for shared
--  classroom machines). The commands are commented out: run them manually
--  and enter a strong password at the prompt. Never store the real password
--  in this repository.
--
--    CREATE USER 'finwise_app'@'localhost'
--      IDENTIFIED BY '<ENTER-A-STRONG-PASSWORD-HERE>';
--    GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON finwise.*
--      TO 'finwise_app'@'localhost';
--    FLUSH PRIVILEGES;
-- =============================================================================

CREATE DATABASE IF NOT EXISTS finwise
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE finwise;
