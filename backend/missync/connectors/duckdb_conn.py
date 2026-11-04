from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Capabilities, Column, SchemaSnapshot, Table
from ..security import quote_ident, validate_local_path
from .base import Connector, ConnectorError, view_body


class DuckDBConnector(Connector):
    """DuckDB database file (read-only) and/or CSV/Parquet files exposed as views."""

    type = "duckdb"
    dialect = "duckdb"
    capabilities = Capabilities(
        read_only_enforced="Database opened with read_only=True; files are read via read_csv_auto/read_parquet",
        notes="CSV/Parquet sources are exposed as tables inside an in-memory DuckDB; no view definitions.",
    )

    def __init__(self, path: str | None = None, files: list[str] | None = None, enforce_path: bool = True):
        import duckdb

        if path:
            p = validate_local_path(path) if enforce_path else Path(path)
            if not p.exists():
                raise ConnectorError(f"DuckDB file not found: {p.name}")
            self._conn = duckdb.connect(str(p), read_only=True)
        else:
            self._conn = duckdb.connect(":memory:")
        self._file_tables: set[str] = set()
        for f in files or []:
            self._register_file(f, enforce_path)

    def _register_file(self, f: str, enforce_path: bool) -> None:
        p = validate_local_path(f) if enforce_path else Path(f)
        if not p.exists():
            raise ConnectorError(f"File not found: {p.name}")
        ext = p.suffix.lower()
        reader = {".csv": "read_csv_auto", ".parquet": "read_parquet"}.get(ext)
        if not reader:
            raise ConnectorError("Only .csv and .parquet files are supported")
        name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in p.stem)
        literal = p.as_posix().replace("'", "''")  # DDL cannot be parameterised; the path was validated and exists
        self._conn.execute(f"create view {quote_ident(name)} as select * from {reader}('{literal}')")
        self._file_tables.add(name)

    def test(self) -> dict[str, Any]:
        return {"server": f"DuckDB {self._conn.execute('select version()').fetchone()[0]}", "read_only": True}

    def discover(self) -> SchemaSnapshot:
        tables: list[Table] = []
        rows = self._conn.execute(
            "select table_name, table_type from information_schema.tables "
            "where table_schema='main' order by table_name"
        ).fetchall()
        pks = {
            (r[0], r[1])
            for r in self._conn.execute(
                "select table_name, unnest(constraint_column_names) from duckdb_constraints() "
                "where constraint_type='PRIMARY KEY'"
            ).fetchall()
        }
        views = dict(
            self._conn.execute("select view_name, sql from duckdb_views() where not internal").fetchall()
        )
        for name, ttype in rows:
            cols = [
                Column(name=c, type=t.upper(), nullable=(n == "YES"), primary_key=(name, c) in pks)
                for c, t, n in self._conn.execute(
                    "select column_name, data_type, is_nullable from information_schema.columns "
                    "where table_schema='main' and table_name=? order by ordinal_position",
                    [name],
                ).fetchall()
            ]
            is_view = ttype == "VIEW"
            definition = None
            if is_view and name not in self._file_tables and views.get(name):
                definition = view_body(views[name])
            t = Table(name=name, kind="view" if is_view else "table", columns=cols, definition=definition)
            if not is_view or name in self._file_tables:
                t.row_count = self.row_count(name)
            tables.append(t)
        return SchemaSnapshot(dialect=self.dialect, tables=tables)

    def row_count(self, table: str) -> int | None:
        return self._conn.execute(f"select count(*) from {quote_ident(table)}").fetchone()[0]

    def fetch_rows(self, table: str, limit: int):
        cur = self._conn.execute(f"select * from {quote_ident(table)} limit ?", [limit + 1])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return cols, rows[:limit], len(rows) > limit

    def query(self, sql: str, limit: int = 1000):
        from ..analysis.sql_parser import assert_single_select

        assert_single_select(sql, self.dialect)
        cur = self._conn.execute(sql)
        return [d[0] for d in cur.description or []], cur.fetchmany(limit)

    def close(self) -> None:
        self._conn.close()
