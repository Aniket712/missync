"""Disposable DuckDB sandbox holding a baseline copy and a candidate copy of the source data.

The source is only read (bounded sample). Proposed SQL is applied exclusively to the in-memory
`cand` schema; the `base` schema is the untouched copy used for comparison.
"""
from __future__ import annotations

import csv
import os
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..connectors.base import Connector, view_body
from ..models import Column, SchemaSnapshot, Table
from ..security import quote_ident
from .sql_parser import Statement

NULL_SENTINEL = "\\N__missync_null__"
EXECUTABLE_KINDS = {"select", "create_table", "create_view", "alter", "drop", "insert", "update", "delete", "merge"}


class SandboxError(RuntimeError):
    pass


@dataclass
class StatementOutcome:
    index: int
    status: str  # executed | skipped | failed
    message: str = ""
    rows_affected: int | None = None
    executed_sql: str = ""


@dataclass
class Sandbox:
    source: Connector
    snapshot: SchemaSnapshot
    sample_limit: int
    timeout_s: int
    conn: Any = None
    truncated: dict[str, bool] = field(default_factory=dict)
    copied_rows: dict[str, int] = field(default_factory=dict)
    view_errors: dict[str, str] = field(default_factory=dict)
    loaded_tables: list[str] = field(default_factory=list)
    skipped_tables: list[str] = field(default_factory=list)

    # ---- lifecycle -------------------------------------------------------------------
    def load(self) -> None:
        self.conn = duckdb.connect(":memory:")
        self.conn.execute("set memory_limit='1GB'")
        self.conn.execute("set threads=2")
        self.conn.execute("create schema base")
        self.conn.execute("create schema cand")
        tables = [t for t in self.snapshot.tables if t.kind == "table"]
        self.conn.execute("use base")
        with tempfile.TemporaryDirectory() as tmp:
            for t in tables:
                self._copy_table(t, tmp)
        for schema in ("cand",):
            for t in self.loaded_tables:
                self.conn.execute(
                    f"create table {schema}.{quote_ident(t)} as select * from base.{quote_ident(t)}"
                )
        self._create_views()
        # Lock the sandbox down before any user SQL runs: no file or network access.
        self.conn.execute("set enable_external_access=false")
        self.conn.execute("set lock_configuration=true")
        

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # ---- loading ---------------------------------------------------------------------
    def _duck_type(self, declared: str) -> str:
        try:
            return sqlglot.parse_one(f"CAST(x AS {declared})", read=self.snapshot.dialect).to.sql("duckdb")
        except (SqlglotError, AttributeError, ValueError):
            return "VARCHAR"

    def _copy_table(self, t: Table, tmp: str) -> None:
        try:
            cols, rows, truncated = self.source.fetch_rows(t.name, self.sample_limit)
        except Exception as e:  # source error: leave table out and say so
            self.skipped_tables.append(t.name)
            self.view_errors[t.name] = f"table could not be read: {type(e).__name__}"
            return
        coldefs = []
        by_name = {c.name: c for c in t.columns}
        for c in cols:
            declared = by_name[c].type if c in by_name else "VARCHAR"
            coldefs.append(f"{quote_ident(c)} {self._duck_type(declared)}")
        self.conn.execute(f"create table base.{quote_ident(t.name)} ({', '.join(coldefs)})")
        path = os.path.join(tmp, f"{len(self.loaded_tables)}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for r in rows:
                w.writerow([NULL_SENTINEL if v is None else (v.hex() if isinstance(v, (bytes, bytearray)) else v) for v in r])
        self.conn.execute(
            f"copy base.{quote_ident(t.name)} from '{path.replace(chr(92), '/')}' "
            f"(format csv, header false, nullstr '{NULL_SENTINEL}')"
        )
        self.loaded_tables.append(t.name)
        self.truncated[t.name] = truncated
        self.copied_rows[t.name] = len(rows)

    def _create_views(self) -> None:
        pending = [t for t in self.snapshot.tables if t.kind == "view" and t.definition]
        for t in self.snapshot.tables:
            if t.kind == "view" and not t.definition:
                self.view_errors[t.name] = "definition not accessible"
        for _ in range(len(pending) + 1):  # resolve view-on-view ordering by retrying
            remaining = []
            for t in pending:
                try:
                    body = sqlglot.parse_one(t.definition, read=self.snapshot.dialect).sql("duckdb")
                    for schema in ("base", "cand"):
                        self.conn.execute(f"use {schema}")
                        self.conn.execute(f"create view {quote_ident(t.name)} as {body}")
                except (duckdb.Error, SqlglotError) as e:
                    self.conn.execute("use base")
                    try:
                        self.conn.execute(f"drop view if exists base.{quote_ident(t.name)}")
                    except duckdb.Error:
                        pass
                    remaining.append(t)
                    self.view_errors[t.name] = str(e).splitlines()[0][:200]
                else:
                    self.view_errors.pop(t.name, None)
            if not remaining or len(remaining) == len(pending):
                break
            pending = remaining

    # ---- execution -------------------------------------------------------------------
    def _run(self, schema: str, sql: str, params: list | None = None):
        self.conn.execute(f"use {schema}")
        timer = threading.Timer(self.timeout_s, self.conn.interrupt)
        timer.start()
        try:
            return self.conn.execute(sql, params or [])
        except duckdb.InterruptException as e:
            raise SandboxError(f"Statement exceeded the {self.timeout_s}s timeout") from e
        finally:
            timer.cancel()

    def query(self, schema: str, sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]:
        cur = self._run(schema, sql, params)
        cols = [d[0] for d in cur.description or []]
        return cols, cur.fetchall()

    def scalar(self, schema: str, sql: str, params: list | None = None) -> Any:
        _, rows = self.query(schema, sql, params)
        return rows[0][0] if rows else None

    def to_duck_sql(self, st: Statement) -> str:
        """Transpile to DuckDB and strip schema qualifiers so it hits the `cand` schema only."""
        e = st.expression.copy()
        for t in e.find_all(exp.Table):
            t.set("db", None)
            t.set("catalog", None)
        return e.sql("duckdb")

    def apply(self, statements: list[Statement]) -> list[StatementOutcome]:
        outcomes: list[StatementOutcome] = []
        failed = False
        for st in statements:
            if failed:
                outcomes.append(StatementOutcome(st.index, "skipped", "Not run because an earlier statement failed"))
                continue
            if st.kind not in EXECUTABLE_KINDS:
                outcomes.append(StatementOutcome(st.index, "skipped", st.parse_error or f"{st.kind} statements are not executed in the sandbox"))
                continue
            try:
                sql = self.to_duck_sql(st)
                cur = self._run("cand", sql)
                n = None
                if st.kind in ("insert", "update", "delete"):
                    r = cur.fetchone()
                    n = int(r[0]) if r and isinstance(r[0], int) else None
                outcomes.append(StatementOutcome(st.index, "executed", rows_affected=n, executed_sql=sql))
            except (duckdb.Error, SandboxError, SqlglotError) as e:
                failed = True
                outcomes.append(StatementOutcome(st.index, "failed", str(e).splitlines()[0][:300]))
        return outcomes

    # ---- introspection ---------------------------------------------------------------
    def schema_snapshot(self, schema: str) -> SchemaSnapshot:
        tables: dict[str, Table] = {}
        pk_names = {t.name.lower(): {c.name.lower() for c in t.columns if c.primary_key} for t in self.snapshot.tables}
        _, trows = self.query(
            "base" if schema == "base" else "cand",
            "select table_name, table_type from information_schema.tables where table_schema=? order by 1",
            [schema],
        )
        for name, ttype in trows:
            tables[name] = Table(name=name, kind="view" if ttype == "VIEW" else "table")
        _, crows = self.query(
            schema,
            "select table_name, column_name, data_type, is_nullable from information_schema.columns "
            "where table_schema=? order by table_name, ordinal_position",
            [schema],
        )
        for tname, cname, dtype, nullable in crows:
            if tname in tables:
                tables[tname].columns.append(
                    Column(name=cname, type=dtype.upper(), nullable=nullable == "YES",
                           primary_key=cname.lower() in pk_names.get(tname.lower(), set()))
                )
        _, vrows = self.query(schema, "select view_name, sql from duckdb_views() where not internal and schema_name=?", [schema])
        for vname, vsql in vrows:
            if vname in tables:
                tables[vname].definition = view_body(vsql)
        return SchemaSnapshot(dialect="duckdb", tables=list(tables.values()))

    def view_valid(self, schema: str, view: str) -> str | None:
        """Return an error message if the view no longer binds, else None."""
        try:
            self._run(schema, f"select * from {quote_ident(view)} limit 0")
            return None
        except duckdb.Error as e:
            return str(e).splitlines()[0][:300]
