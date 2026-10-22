"""AST validation plus SQLite authorization and a physically read-only connection."""

import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

import sqlglot
from sqlglot import exp


class UnsafeSQL(ValueError):
    pass


def ensure_database(path: Path, seed_directory: Path = Path("data/database")):
    """Initialize only a missing destination; never reset an existing database."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".seed-", dir=path.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.executescript((seed_directory / "schema.sql").read_text())
            connection.executescript((seed_directory / "seed_data.sql").read_text())
            connection.commit()
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass  # Another startup initialized it; preserve that database.
    finally:
        os.unlink(temporary)


class Database:
    def __init__(self, path: Path):
        self.path = path.resolve()
        if not self.path.is_file():
            raise FileNotFoundError(
                f"Database is missing: {path}; restore or seed the source first"
            )
        with closing(self.connect()) as conn:
            self.tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.schema = "\n".join(
                r[0]
                for r in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            )

    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only=ON")
        conn.enable_load_extension(False)
        return conn

    def query(self, sql: str, parameters: dict | None = None, *, timeout: float = 10) -> dict:
        if not isinstance(sql, str) or len(sql) > 10000:
            raise UnsafeSQL("SQL must be a SELECT of at most 10000 characters")
        try:
            statements = sqlglot.parse(sql, read="sqlite")
        except sqlglot.errors.ParseError as exc:
            raise UnsafeSQL("SQL could not be parsed") from exc
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise UnsafeSQL("Exactly one SELECT statement is permitted")
        tree = statements[0]
        ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
        if any(table.name not in self.tables | ctes for table in tree.find_all(exp.Table)):
            raise UnsafeSQL("Only application tables and SELECT CTEs are permitted")
        if sum(1 for _ in tree.walk()) > 500 or any(
            isinstance(n, (exp.DML, exp.DDL, exp.Command)) for n in tree.walk()
        ):
            raise UnsafeSQL("SQL contains forbidden or excessively complex operations")
        functions = {
            "count",
            "sum",
            "avg",
            "min",
            "max",
            "coalesce",
            "ifnull",
            "nullif",
            "round",
            "abs",
            "lower",
            "upper",
            "length",
            "substr",
            "substring",
            "date",
            "datetime",
            "strftime",
            "julianday",
            "like",
            "trim",
            "cast",
            "total",
            "group_concat",
            "replace",
            "iif",
        }

        def authorize(action, arg1, arg2, db_name, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1 in self.tables:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in functions:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn = self.connect()
        try:
            deadline = time.monotonic() + timeout
            conn.set_authorizer(authorize)
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            cursor = conn.execute(sql, parameters or {})
            rows = cursor.fetchmany(201)
            return {
                "sql": sql,
                "parameters": parameters or {},
                "columns": [c[0] for c in cursor.description],
                "rows": [list(r) for r in rows[:200]],
                "truncated": len(rows) > 200,
            }
        except sqlite3.DatabaseError as exc:
            if "authoriz" in str(exc) or "prohibited" in str(exc):
                raise UnsafeSQL("SQL attempted a forbidden table, function, or operation") from exc
            raise ValueError(f"SQLite query failed: {exc}") from exc
        finally:
            conn.close()
