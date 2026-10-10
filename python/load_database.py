#!/usr/bin/env python3
"""Cross-platform loader for the FinWise SQL scripts.

Why a Python loader?
  * Identical setup workflow on macOS and Windows: no shell quirks, no mysql
    PATH issues, and correct handling of the DELIMITER directives used by
    the stored-procedure file (a plain `mysql < file` also works - see
    README - but the loader is the recommended path).
  * The pytest suite reuses this module to build its throwaway test
    database, so there is exactly one implementation of "load the SQL".

Safety
  * Destructive BY DESIGN: `01_schema.sql` drops and recreates the FinWise
    tables in the target database, and `04_seed_data.sql` wipes and reloads
    sample data. The loader prints a clear warning and asks for confirmation
    (type the database name) unless `--yes` is passed.
  * The database name is validated against ^[A-Za-z0-9_]+$ and always
    backtick-quoted, so a crafted name cannot inject SQL.
  * Credentials come from python/db.py (.env / environment) - never from
    the command line, where they would be visible in the process list.

Usage
  python python/load_database.py            # interactive confirmation
  python python/load_database.py --yes     # non-interactive (CI, scripts)
  python python/load_database.py --database finwise --files sql/01_schema.sql
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (local module, path set above)

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

# The loader creates the target database itself (equivalent to file 00), so
# file 00 is intentionally not in the default set.
DEFAULT_FILES = [
    "01_schema.sql",
    "02_stored_procedures.sql",
    "03_views.sql",
    "04_seed_data.sql",
]

_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_DELIMITER_LINE_RE = re.compile(r"^\s*delimiter\s+(\S+)\s*$", re.IGNORECASE)
_USE_RE = re.compile(r"^\s*USE\b", re.IGNORECASE)


def _strip_leading_comments(stmt: str) -> str:
    """Remove whitespace and comments from the START of a statement.

    Used to classify statements safely: a chunk like "-- header\nUSE finwise;"
    must be recognized as a USE statement (and dropped by the loader, which
    manages the active database itself) rather than slipping through because
    the raw text merely starts with a comment.
    """
    i, n = 0, len(stmt)
    while i < n:
        ch = stmt[i]
        if ch in " \t\r\n":
            i += 1
        elif stmt.startswith("/*", i):
            end = stmt.find("*/", i + 2)
            if end == -1:
                return stmt[i:]  # unterminated - let the server complain
            i = end + 2
        elif stmt.startswith("--", i) and (i + 2 >= n or stmt[i + 2] in " \t\r\n"):
            end = stmt.find("\n", i)
            i = n if end == -1 else end + 1
        elif ch == "#":
            end = stmt.find("\n", i)
            i = n if end == -1 else end + 1
        else:
            return stmt[i:]
    return ""



def split_sql_statements(text: str) -> list[str]:
    """Split a MySQL script into executable statements.

    Understands, so it can safely process procedure definitions:
      * single/double-quoted strings (with '' and \\ escaping),
      * line comments (`-- ` and `#`) and block comments (/* */),
      * `DELIMITER` directives (must appear at the start of a line).

    Statement text keeps its comments (the server accepts them inline).
    `USE` statements are dropped - even when preceded by comment banners -
    because the loader selects the target database itself; that is what
    allows the same scripts to load `finwise_test` during testing.
    Comment-only chunks (e.g. trailing footers) are discarded.
    """
    statements: list[str] = []
    buffer: list[str] = []
    delimiter = ";"
    in_squote = in_dquote = in_block = in_line = False
    at_line_start = True
    i, n = 0, len(text)

    def flush() -> None:
        stmt = "".join(buffer).strip()
        code = _strip_leading_comments(stmt) if stmt else ""
        if stmt and code:
            if not _USE_RE.match(code):
                statements.append(stmt)
            # else: 'USE' statements are dropped on purpose - the loader
            # selects the target database itself, which is what allows the
            # same scripts to load `finwise_test` during testing.
        # Comment-only chunks (e.g. trailing file banners) are discarded.
        buffer.clear()

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line:  # comment runs to end of line
            if ch == "\n":
                in_line = False
                at_line_start = True
            buffer.append(ch)
            i += 1
            continue

        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                buffer.append("*/")
                i += 2
            else:
                buffer.append(ch)
                i += 1
            continue

        if in_squote:
            if ch == "\\" and nxt:  # escaped character
                buffer.append(ch + nxt)
                i += 2
            elif ch == "'":
                if nxt == "'":  # '' escape
                    buffer.append("''")
                    i += 2
                else:
                    in_squote = False
                    buffer.append(ch)
                    i += 1
            else:
                buffer.append(ch)
                i += 1
            continue

        if in_dquote:
            if ch == "\\" and nxt:
                buffer.append(ch + nxt)
                i += 2
            elif ch == '"':
                if nxt == '"':
                    buffer.append('""')
                    i += 2
                else:
                    in_dquote = False
                    buffer.append(ch)
                    i += 1
            else:
                buffer.append(ch)
                i += 1
            continue

        # Not inside a string or comment.
        if ch == "-" and nxt == "-" and (i + 2 >= n or text[i + 2] in " \t\r\n"):
            in_line = True
            buffer.append("--")
            i += 2
            continue
        if ch == "#":
            in_line = True
            buffer.append("#")
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            buffer.append("/*")
            i += 2
            continue
        if ch == "'":
            in_squote = True
            buffer.append(ch)
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            buffer.append(ch)
            i += 1
            continue

        # DELIMITER directive - only at the beginning of a line. Comments
        # buffered so far stay attached to the next statement.
        if at_line_start and text[i : i + 9].lower() == "delimiter":
            line_end = text.find("\n", i)
            line = text[i : line_end if line_end != -1 else n]
            m = _DELIMITER_LINE_RE.match(line)
            if m:
                delimiter = m.group(1)
                i = line_end + 1 if line_end != -1 else n
                at_line_start = True
                continue

        if text.startswith(delimiter, i):
            flush()
            i += len(delimiter)
            continue

        if ch == "\n":
            at_line_start = True
        elif ch not in " \t\r":
            at_line_start = False
        buffer.append(ch)
        i += 1

    flush()
    return statements


def ensure_database(server_conn, name: str) -> None:
    """Create the target database if it does not exist and select it."""
    if not _NAME_RE.match(name):
        raise SystemExit(
            f"Refusing to use database name {name!r}: only letters, digits "
            "and underscores are allowed."
        )
    cur = server_conn.cursor()
    try:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cur.execute(f"USE `{name}`")
        server_conn.commit()
    finally:
        cur.close()


def load_sql_files(conn, file_paths: list[Path], verbose: bool = True) -> int:
    """Execute every statement from the given SQL files, in order.

    Files are loaded one at a time with an explicit commit after each file,
    so a failure leaves a clear boundary in the progress output.
    Returns the total number of statements executed.
    """
    total = 0
    cur = conn.cursor()
    try:
        for path in file_paths:
            if verbose:
                print(f"-- loading {path.name} ...", end=" ", flush=True)
            statements = split_sql_statements(path.read_text(encoding="utf-8"))
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as exc:
                    preview = " ".join(stmt.split())[:120]
                    raise RuntimeError(
                        f"Failed statement in {path.name}:\n"
                        f"  error : {exc}\n  stmt  : {preview} ..."
                    ) from exc
            conn.commit()
            total += len(statements)
            if verbose:
                print(f"{len(statements)} statements OK")
    finally:
        cur.close()
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database",
        default=None,
        help="Target database (default: FINWISE_DB_NAME from .env, or 'finwise')",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        metavar="SQL_FILE",
        help="Optional subset of SQL files (paths or names in sql/). "
        "Default: the standard load order 01-04.",
    )
    args = parser.parse_args(argv)

    database = args.database or db.DEFAULTS["FINWISE_DB_NAME"]
    if args.files:
        file_paths = [
            (p if p.exists() else SQL_DIR / p) for p in map(Path, args.files)
        ]
        for path in file_paths:
            if not path.exists():
                raise SystemExit(f"File not found: {path}")
    else:
        file_paths = [SQL_DIR / f for f in DEFAULT_FILES]

    print("=" * 70)
    print("FinWise database loader")
    print("=" * 70)
    print(f"Target database : {database}")
    print("Files           : " + ", ".join(p.name for p in file_paths))
    print()
    print("!! WARNING: this DROPs and re-CREATEs the FinWise tables and")
    print("!! reloads the sample data in the target database.")
    print()

    if not args.yes:
        reply = input(f"Type the database name '{database}' to continue: ")
        if reply.strip() != database:
            print("Aborted - nothing was changed.")
            return 1

    conn = db.get_server_connection()
    try:
        ensure_database(conn, database)
        load_sql_files(conn, file_paths)
    finally:
        conn.close()

    print()
    print(f"Done. Database '{database}' is ready.")
    print("Next steps:")
    print("  python python/verify_setup.py   # health check")
    print("  python python/crud_examples.py  # interactive demo")
    print("  pytest                          # full test suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
