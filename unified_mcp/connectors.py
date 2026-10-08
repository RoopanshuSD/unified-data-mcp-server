"""Data-source connectors. Each one opens a READ-ONLY session with a statement timeout.

SQLite (demo + tests) is exercised in this repo's test suite. Postgres and Snowflake follow the same interface;
their integration tests run only when credentials are provided (see tests/integration/).
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]


class Connector(Protocol):
    dialect: str

    def list_tables(self) -> list[dict]: ...
    def describe(self, table: str) -> dict: ...
    def query(self, sql: str, timeout_s: float) -> QueryResult: ...


class SQLiteConnector:
    dialect = "sqlite"

    def __init__(self, path: str):
        self.path = path

    def _conn(self, timeout_s: float = 5.0) -> sqlite3.Connection:
        # mode=ro: the database file is opened read-only at the OS/driver level.
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        return conn

    def list_tables(self) -> list[dict]:
        with self._conn() as c:
            names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return [{"table": n} for n in names]

    def describe(self, table: str) -> dict:
        with self._conn() as c:
            if table not in {t["table"] for t in self.list_tables()}:
                raise KeyError(table)
            cols = [{"name": r[1], "type": r[2], "pk": bool(r[5])} for r in c.execute(f'PRAGMA table_info("{table}")')]
            fks = [{"column": r[3], "references": f"{r[2]}.{r[4]}"}
                   for r in c.execute(f'PRAGMA foreign_key_list("{table}")')]
            count = c.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        return {"table": table, "columns": cols, "foreign_keys": fks, "row_count": count}

    def query(self, sql: str, timeout_s: float) -> QueryResult:
        with self._conn(timeout_s) as c:
            cur = c.execute(sql)
            return QueryResult([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])


class PostgresConnector:
    dialect = "postgres"

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _conn(self, timeout_s: float):
        import psycopg  # optional dependency: pip install ".[postgres]"
        conn = psycopg.connect(self.dsn, autocommit=False)
        conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        conn.execute(f"SET statement_timeout = {int(timeout_s * 1000)}")
        return conn

    def list_tables(self) -> list[dict]:
        with self._conn(5) as c:
            rows = c.execute("SELECT table_schema, table_name FROM information_schema.tables "
                             "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1,2").fetchall()
        return [{"schema": s, "table": t} for s, t in rows]

    def describe(self, table: str) -> dict:
        schema, _, name = table.rpartition(".")
        with self._conn(5) as c:
            cols = c.execute("SELECT column_name, data_type FROM information_schema.columns "
                             "WHERE table_name = %s AND table_schema = %s ORDER BY ordinal_position",
                             (name, schema or "public")).fetchall()
        if not cols:
            raise KeyError(table)
        return {"table": table, "columns": [{"name": n, "type": t} for n, t in cols]}

    def query(self, sql: str, timeout_s: float) -> QueryResult:
        with self._conn(timeout_s) as c:
            cur = c.execute(sql)
            return QueryResult([d.name for d in cur.description], [list(r) for r in cur.fetchall()])


class SnowflakeConnector:
    dialect = "snowflake"

    def __init__(self, **params):
        self.params = params  # account, user, password/authenticator, warehouse, database, schema, role

    def _conn(self, timeout_s: float):
        import snowflake.connector  # optional dependency: pip install ".[snowflake]"
        conn = snowflake.connector.connect(**self.params)
        conn.cursor().execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(timeout_s)}")
        return conn  # read-only is enforced by granting the connecting ROLE SELECT only

    def list_tables(self) -> list[dict]:
        cur = self._conn(5).cursor()
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'")
        return [{"schema": s, "table": t} for s, t in cur.fetchall()]

    def describe(self, table: str) -> dict:
        schema, _, name = table.rpartition(".")
        cur = self._conn(5).cursor()
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s"
                    + (" AND table_schema = %s" if schema else ""), (name.upper(),) + ((schema.upper(),) if schema else ()))
        return {"table": table, "columns": [{"name": n, "type": t} for n, t in cur.fetchall()]}

    def query(self, sql: str, timeout_s: float) -> QueryResult:
        cur = self._conn(timeout_s).cursor()
        cur.execute(sql)
        return QueryResult([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])


def make_connector(cfg: dict) -> Connector:
    kind = cfg["kind"]
    if kind == "sqlite":
        return SQLiteConnector(cfg["path"])
    if kind == "postgres":
        return PostgresConnector(cfg["dsn"])
    if kind == "snowflake":
        return SnowflakeConnector(**cfg["params"])
    raise ValueError(f"unknown source kind {kind}")
