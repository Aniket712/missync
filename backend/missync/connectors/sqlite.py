from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..models import Capabilities, Column, SchemaSnapshot, Table
from ..security import quote_ident, validate_local_path
from .base import Connector, ConnectorError, view_body


class SQLiteConnector(Connector):
    type = "sqlite"
    dialect = "sqlite"
    capabilities = Capabilities(
        read_only_enforced="File opened with mode=ro and PRAGMA query_only=ON",
        notes="Type affinity is loose; declared types are used for comparison.",
    )

    def __init__(self, path: str, enforce_path: bool = True):
        self.path = validate_local_path(path) if enforce_path else Path(path)
        if not self.path.exists():
            raise ConnectorError(f"SQLite file not found: {self.path.name}")
        self._conn = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        self._conn.execute("PRAGMA query_only=ON")

    def test(self) -> dict[str, Any]:
        v = self._conn.execute("select sqlite_version()").fetchone()[0]
        return {"server": f"SQLite {v}", "read_only": True}

    def discover(self) -> SchemaSnapshot:
        tables: list[Table] = []
        rows = self._conn.execute(
            "select name, type, sql from sqlite_master where type in ('table','view') "
            "and name not like 'sqlite_%' order by name"
        ).fetchall()
        for name, kind, sql in rows:
            cols = [
                Column(name=c[1], type=(c[2] or "TEXT").upper(), nullable=not (c[3] or c[5]), primary_key=bool(c[5]))
                for c in self._conn.execute(f"PRAGMA table_info({quote_ident(name)})")
            ]
            definition = None
            if kind == "view" and sql:
                definition = view_body(sql)
            t = Table(name=name, kind=kind, columns=cols, definition=definition)
            if kind == "table":
                t.row_count = self.row_count(name)
            tables.append(t)
        return SchemaSnapshot(dialect=self.dialect, tables=tables)

    def row_count(self, table: str) -> int | None:
        return self._conn.execute(f"select count(*) from {quote_ident(table)}").fetchone()[0]

    def fetch_rows(self, table: str, limit: int):
        cur = self._conn.execute(f"select * from {quote_ident(table)} limit ?", (limit + 1,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return cols, rows[:limit], len(rows) > limit

    def query(self, sql: str, limit: int = 1000):
        from ..analysis.sql_parser import assert_single_select

        assert_single_select(sql, self.dialect)
        cur = self._conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        return cols, cur.fetchmany(limit)

    def close(self) -> None:
        self._conn.close()
