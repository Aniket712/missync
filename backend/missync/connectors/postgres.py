from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL

from ..config import get_settings
from ..models import Capabilities, Column, SchemaSnapshot, Table
from ..security import quote_ident, validate_host
from .base import Connector


class PostgresConnector(Connector):
    type = "postgres"
    dialect = "postgres"
    capabilities = Capabilities(
        read_only_enforced="Session set to default_transaction_read_only=on with statement_timeout; "
        "use a database role that only has SELECT as defence in depth",
        notes="View definitions via pg_get_viewdef. Sandbox copies a bounded sample into DuckDB.",
    )

    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        password: str = "",
        port: int = 5432,
        schema: str = "public",
        sslmode: str = "prefer",
        engine=None,
    ):
        self.schema = schema
        if engine is not None:  # injected for tests
            self.engine = engine
            return
        ip = validate_host(host)
        timeout_ms = get_settings().statement_timeout_s * 1000
        url = URL.create("postgresql+psycopg2", username=user, password=password, host=host, port=port, database=database)
        self.engine = create_engine(
            url,
            connect_args={
                "sslmode": sslmode,
                "hostaddr": ip,  # connect to the address that passed validation (host is still used for TLS checks)
                "connect_timeout": 10,
                "options": f"-c default_transaction_read_only=on -c statement_timeout={timeout_ms}",
            },
            pool_pre_ping=True,
            pool_size=2,
        )

        @event.listens_for(self.engine, "connect")
        def _ro(dbapi_conn, _):  # belt and braces
            dbapi_conn.set_session(readonly=True, autocommit=False)

    def test(self) -> dict[str, Any]:
        with self.engine.connect() as c:
            v = c.execute(text("select version()")).scalar()
            ro = c.execute(text("show transaction_read_only")).scalar()
        return {"server": str(v).split(",")[0], "read_only": ro == "on"}

    def discover(self) -> SchemaSnapshot:
        tables: dict[str, Table] = {}
        with self.engine.connect() as c:
            for name, ttype in c.execute(
                text(
                    "select table_name, table_type from information_schema.tables "
                    "where table_schema=:s and table_type in ('BASE TABLE','VIEW') order by table_name"
                ),
                {"s": self.schema},
            ):
                tables[name] = Table(
                    name=name, schema_name=self.schema, kind="view" if ttype == "VIEW" else "table"
                )
            pks = {
                (r[0], r[1])
                for r in c.execute(
                    text(
                        "select kcu.table_name, kcu.column_name from information_schema.table_constraints tc "
                        "join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name "
                        "and tc.table_schema=kcu.table_schema where tc.constraint_type='PRIMARY KEY' "
                        "and tc.table_schema=:s"
                    ),
                    {"s": self.schema},
                )
            }
            for tname, cname, dtype, notnull in c.execute(
                text(
                    "select c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull "
                    "from pg_attribute a join pg_class c on c.oid = a.attrelid "
                    "join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = :s and a.attnum > 0 and not a.attisdropped and c.relkind in ('r','v','p') "
                    "order by c.relname, a.attnum"
                ),
                {"s": self.schema},
            ):
                if tname in tables:
                    tables[tname].columns.append(
                        Column(name=cname, type=dtype.upper(), nullable=not notnull, primary_key=(tname, cname) in pks)
                    )
            for vname, vdef in c.execute(
                text("select viewname, definition from pg_views where schemaname=:s"), {"s": self.schema}
            ):
                if vname in tables:
                    tables[vname].definition = str(vdef).strip().rstrip(";")
            # Planner estimates avoid a full count(*) per table (slow on big tables); exact counts only where stats are missing.
            est = {
                r[0]: int(r[1])
                for r in c.execute(
                    text(
                        "select c.relname, c.reltuples::bigint from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = :s and c.relkind in ('r','p') and c.reltuples >= 0"
                    ),
                    {"s": self.schema},
                )
            }
        for t in tables.values():
            if t.kind != "table":
                continue
            if t.name in est:
                t.row_count, t.row_count_estimated = est[t.name], True
            else:
                try:
                    t.row_count = self.row_count(t.name)
                except Exception:
                    t.row_count = None
        return SchemaSnapshot(dialect=self.dialect, tables=list(tables.values()))

    def _qualified(self, table: str) -> str:
        return f"{quote_ident(self.schema)}.{quote_ident(table)}"

    def row_count(self, table: str) -> int | None:
        with self.engine.connect() as c:
            return c.execute(text(f"select count(*) from {self._qualified(table)}")).scalar()

    def fetch_rows(self, table: str, limit: int):
        with self.engine.connect() as c:
            res = c.execute(text(f"select * from {self._qualified(table)} limit :n"), {"n": limit + 1})
            cols = list(res.keys())
            rows = [tuple(r) for r in res.fetchall()]
        return cols, rows[:limit], len(rows) > limit

    def query(self, sql: str, limit: int = 1000):
        from ..analysis.sql_parser import assert_single_select

        assert_single_select(sql, self.dialect)
        with self.engine.connect() as c:
            res = c.exec_driver_sql(sql)
            return list(res.keys()), [tuple(r) for r in res.fetchmany(limit)]

    def close(self) -> None:
        self.engine.dispose()
