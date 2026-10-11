#!/usr/bin/env python3
"""Interactive CRUD demo for FinWise - also a template for Members 2-4.

Every operation below demonstrates the CORRECT pattern from the database
contract (docs/database_contract.md):

  * READS  go through the contract views (v_portfolio_positions,
    v_sector_allocation, v_portfolio_performance, v_user_summary).
  * WRITES to users and portfolios use plain parameterized statements.
  * WRITES to holdings / transactions / portfolio_snapshots go ONLY through
    the stored procedures via db.record_transaction / db.create_snapshot.
    Note how a rejected transaction (e.g. selling more shares than held)
    surfaces the procedure's error message and changes nothing.

Run with:  python python/crud_examples.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402


# ---------------------------------------------------------------------------
# Small input helpers
# ---------------------------------------------------------------------------
def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def ask_int(prompt: str) -> int:
    while True:
        try:
            return int(ask(prompt))
        except ValueError:
            print("  Please enter a whole number.")


def ask_positive_decimal(prompt: str) -> Decimal:
    while True:
        try:
            value = Decimal(ask(prompt))
            if value > 0:
                return value
        except Exception:
            pass
        print("  Please enter a positive number.")


def print_table(rows: list[dict], columns: list[str]) -> None:
    """Tiny row printer - enough for a demo, no external dependencies."""
    if not rows:
        print("  (no rows)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  " + " | ".join(c.ljust(widths[c]) for c in columns))
    print("  " + "-+-".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  " + " | ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def show_error(exc: Exception) -> None:
    print(f"  REJECTED by the database: {exc}")


# ---------------------------------------------------------------------------
# Menu operations
# ---------------------------------------------------------------------------
def list_users(conn) -> None:
    print("\nUsers (via v_user_summary - includes users with no portfolios):")
    rows = db.fetch_all(
        conn,
        "SELECT username, portfolio_count, position_count, "
        "       total_market_value, total_unrealized_pl "
        "FROM v_user_summary ORDER BY user_id",
    )
    print_table(rows, ["username", "portfolio_count", "position_count",
                       "total_market_value", "total_unrealized_pl"])


def list_portfolios(conn) -> None:
    user_id = ask_int("User id")
    rows = db.fetch_all(
        conn,
        "SELECT portfolio_id, portfolio_name, created_at "
        "FROM portfolios WHERE user_id = %s ORDER BY portfolio_id",
        (user_id,),
    )
    print_table(rows, ["portfolio_id", "portfolio_name", "created_at"])


def show_positions(conn) -> None:
    portfolio_id = ask_int("Portfolio id")
    rows = db.fetch_all(
        conn,
        "SELECT ticker_symbol, sector_name, quantity, average_cost_per_unit, "
        "       current_price, market_value, unrealized_pl, pl_percent, "
        "       portfolio_weight_percent "
        "FROM v_portfolio_positions WHERE portfolio_id = %s "
        "ORDER BY market_value DESC",
        (portfolio_id,),
    )
    print_table(rows, ["ticker_symbol", "sector_name", "quantity",
                       "average_cost_per_unit", "current_price", "market_value",
                       "unrealized_pl", "pl_percent", "portfolio_weight_percent"])


def show_sector_allocation(conn) -> None:
    portfolio_id = ask_int("Portfolio id")
    rows = db.fetch_all(
        conn,
        "SELECT sector_name, sector_value, sector_weight_percent "
        "FROM v_sector_allocation WHERE portfolio_id = %s "
        "ORDER BY sector_weight_percent DESC",
        (portfolio_id,),
    )
    print_table(rows, ["sector_name", "sector_value", "sector_weight_percent"])


def show_performance(conn) -> None:
    portfolio_id = ask_int("Portfolio id")
    rows = db.fetch_all(
        conn,
        "SELECT snapshot_date, holdings_count, total_market_value, "
        "       previous_market_value, change_value, change_percent "
        "FROM v_portfolio_performance WHERE portfolio_id = %s "
        "ORDER BY snapshot_date",
        (portfolio_id,),
    )
    print_table(rows, ["snapshot_date", "holdings_count", "total_market_value",
                       "previous_market_value", "change_value", "change_percent"])


def add_user(conn) -> None:
    username = ask("Username")
    email = ask("Email")
    full_name = ask("Full name")
    if not (username and email and full_name):
        print("  All fields are required - nothing was created.")
        return
    try:
        user_id = db.execute(
            conn,
            "INSERT INTO users (username, email, full_name) VALUES (%s, %s, %s)",
            (username, email, full_name),
        )
        print(f"  Created user id {user_id}.")
    except Exception as exc:
        show_error(exc)


def rename_portfolio(conn) -> None:
    portfolio_id = ask_int("Portfolio id")
    new_name = ask("New name")
    try:
        if db.fetch_one(conn, "SELECT portfolio_id FROM portfolios "
                              "WHERE portfolio_id = %s",
                        (portfolio_id,)) is None:
            print(f"  No portfolio with id {portfolio_id} - nothing changed.")
            return
        db.execute(
            conn,
            "UPDATE portfolios SET portfolio_name = %s WHERE portfolio_id = %s",
            (new_name, portfolio_id),
        )
        print("  Renamed.")
    except Exception as exc:
        show_error(exc)


def delete_portfolio(conn) -> None:
    portfolio_id = ask_int("Portfolio id to delete")
    try:
        if db.fetch_one(conn, "SELECT portfolio_id FROM portfolios "
                              "WHERE portfolio_id = %s",
                        (portfolio_id,)) is None:
            print(f"  No portfolio with id {portfolio_id} - nothing deleted.")
            return
    except Exception as exc:
        show_error(exc)
        return
    confirm = ask(f"Type YES to permanently delete portfolio {portfolio_id} "
                  "and ALL its holdings, transactions and snapshots")
    if confirm != "YES":
        print("  Cancelled.")
        return
    try:
        db.execute(conn, "DELETE FROM portfolios WHERE portfolio_id = %s",
                   (portfolio_id,))
        print("  Deleted (referential integrity cascaded the related rows).")
    except Exception as exc:
        show_error(exc)


def list_stocks(conn) -> None:
    rows = db.fetch_all(
        conn,
        "SELECT stock_id, ticker_symbol, company_name, sector_id, current_price "
        "FROM stocks ORDER BY stock_id",
    )
    print_table(rows, ["stock_id", "ticker_symbol", "company_name",
                       "sector_id", "current_price"])


def record_transaction(conn) -> None:
    print("\nRecord a transaction (writes ONLY through sp_record_transaction):")
    list_portfolios_ids(conn)
    portfolio_id = ask_int("Portfolio id")
    list_stocks(conn)
    stock_id = ask_int("Stock id")
    tx_type = ""
    while tx_type not in ("BUY", "SELL"):
        tx_type = ask("BUY or SELL").upper()
    quantity = ask_positive_decimal("Quantity (e.g. 10 or 2.5)")
    price = ask_positive_decimal("Price per unit (e.g. 245.50)")
    trade_date = ask("Date and time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    notes = ask("Notes (optional)", "")

    try:
        tx_id = db.record_transaction(
            conn, portfolio_id, stock_id, tx_type,
            float(quantity), float(price), trade_date,
            notes or None,
        )
        print(f"  Committed. transaction_id = {tx_id}.")
        print("  Tip: try a SELL larger than the held quantity to see the")
        print("  procedure reject it and leave both tables unchanged.")
    except Exception as exc:
        show_error(exc)


def list_portfolios_ids(conn) -> None:
    rows = db.fetch_all(
        conn,
        "SELECT portfolio_id, portfolio_name, user_id FROM portfolios "
        "ORDER BY portfolio_id",
    )
    print_table(rows, ["portfolio_id", "portfolio_name", "user_id"])


def create_snapshot(conn) -> None:
    portfolio_id = ask_int("Portfolio id")
    snapshot_date = ask("Snapshot date (YYYY-MM-DD)",
                        datetime.now().strftime("%Y-%m-%d"))
    try:
        db.create_snapshot(conn, portfolio_id, snapshot_date)
        print("  Snapshot created (calling twice for the same date simply")
        print("  refreshes it - the procedure is an idempotent upsert).")
    except Exception as exc:
        show_error(exc)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
MENU = """
================ FinWise CRUD demo ================
 1) List users (with summary totals)
 2) List portfolios of a user
 3) Show positions of a portfolio        [v_portfolio_positions]
 4) Show sector allocation               [v_sector_allocation]
 5) Show performance history             [v_portfolio_performance]
 6) Add a user
 7) Rename a portfolio
 8) Delete a portfolio (demonstrates CASCADE)
 9) Record a BUY / SELL                  [sp_record_transaction]
10) Create a snapshot                    [sp_create_snapshot]
 0) Exit
===================================================
"""

ACTIONS = {
    "1": list_users,
    "2": list_portfolios,
    "3": show_positions,
    "4": show_sector_allocation,
    "5": show_performance,
    "6": add_user,
    "7": rename_portfolio,
    "8": delete_portfolio,
    "9": record_transaction,
    "10": create_snapshot,
}


def main() -> int:
    try:
        conn = db.get_connection()
    except Exception as exc:
        print(f"Could not connect to MySQL: {exc}")
        print("Hint: start the server, copy .env.example to .env, and set")
        print("FINWISE_DB_PASSWORD. Then run python python/load_database.py.")
        return 1

    try:
        while True:
            print(MENU)
            choice = input("Choose an option: ").strip()
            if choice == "0":
                print("Bye.")
                return 0
            action = ACTIONS.get(choice)
            if action is None:
                print("  Unknown option.")
                continue
            try:
                action(conn)
            except KeyboardInterrupt:
                print("\n  (cancelled)")
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
