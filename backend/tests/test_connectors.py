from types import SimpleNamespace

import duckdb
import pytest

from missync.connectors import ConnectorError, build_connector
from missync.connectors.bigquery import BigQueryConnector
from missync.connectors.duckdb_conn import DuckDBConnector
from missync.connectors.postgres import PostgresConnector
from missync.connectors.snowflake import SnowflakeConnector
from missync.security import SecurityError


def test_sqlite_discovery(sqlite_conn):
    snap = sqlite_conn.discover()
    names = {t.name: t for t in snap.tables}
    assert {"customers", "orders", "v_daily_revenue"} <= set(names)
    assert names["orders"].column("order_id").primary_key and names["orders"].row_count == 5000
    assert names["v_daily_revenue"].kind == "view" and names["v_daily_revenue"].definition.lower().startswith("select")
    assert sqlite_conn.test()["read_only"] is True


def test_sqlite_is_read_only(demo_db):
    import sqlite3

    from missync.connectors.sqlite import SQLiteConnector

    c = SQLiteConnector(str(demo_db), enforce_path=False)
    with pytest.raises(sqlite3.OperationalError):
        c._conn.execute("delete from customers")
    with pytest.raises(sqlite3.OperationalError):
        c._conn.execute("create table x(a)")


def test_fetch_rows_bounded_and_truncated(sqlite_conn):
    cols, rows, truncated = sqlite_conn.fetch_rows("orders", 10)
    assert len(rows) == 10 and truncated and "order_id" in cols
    assert not sqlite_conn.fetch_rows("segment_map", 100)[2]


def test_query_only_allows_select(sqlite_conn):
    assert sqlite_conn.query("select count(*) from customers")[1][0][0] == 1000
    from missync.analysis.sql_parser import SqlRejected

    with pytest.raises(SqlRejected):
        sqlite_conn.query("delete from customers")


def test_sqlite_path_traversal_blocked(tmp_path, monkeypatch):
    from missync.config import get_settings

    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MISSYNC_ALLOW_LOCAL_PATHS", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SecurityError):
        build_connector("sqlite", {"path": str(tmp_path.parent / "other.db")})
    with pytest.raises(SecurityError):
        build_connector("sqlite", {"path": "../../etc/passwd"})
    get_settings.cache_clear()


def test_duckdb_file_and_views(tmp_path, monkeypatch):
    p = tmp_path / "x.duckdb"
    con = duckdb.connect(str(p))
    con.execute("create table t(id integer primary key, v double); insert into t values (1, 2.5);")
    con.execute("create view vt as select id, v * 2 as v2 from t")
    con.close()
    c = DuckDBConnector(path=str(p), enforce_path=False)
    snap = c.discover()
    t = snap.table("t")
    assert t.row_count == 1 and t.column("id").primary_key
    assert snap.table("vt").kind == "view" and snap.table("vt").definition.lower().startswith("select")
    with pytest.raises(duckdb.Error):
        c._conn.execute("insert into t values (2, 1)")


def test_csv_and_parquet_sources(tmp_path):
    csv = tmp_path / "people.csv"
    csv.write_text("id,name\n1,a\n2,b\n")
    pq = tmp_path / "scores.parquet"
    duckdb.execute(f"copy (select 1 as id, 9.5 as score) to '{pq.as_posix()}' (format parquet)")
    c = DuckDBConnector(files=[str(csv), str(pq)], enforce_path=False)
    snap = c.discover()
    assert snap.table("people").row_count == 2 and snap.table("scores").column("score") is not None
    assert c.fetch_rows("people", 10)[1] == [(1, "a"), (2, "b")]
    with pytest.raises(ConnectorError):
        DuckDBConnector(files=[str(tmp_path / "x.txt")], enforce_path=False)


def test_unknown_and_incomplete_connector_params():
    with pytest.raises(ConnectorError):
        build_connector("mysql", {})
    with pytest.raises(ConnectorError):
        build_connector("postgres", {"host": "h"})


# --- Postgres: no server available in the test environment; verify queries and safety settings only --------
class FakeResult(list):
    def keys(self):
        return ["a"]


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.log.append((sql, params))
        if "information_schema.tables" in sql:
            return [("orders", "BASE TABLE"), ("v_o", "VIEW")]
        if "key_column_usage" in sql:
            return [("orders", "id")]
        if "pg_attribute" in sql:
            return [("orders", "id", "integer", True), ("orders", "amt", "numeric(10,2)", False), ("v_o", "id", "integer", False)]
        if "pg_views" in sql:
            return [("v_o", "SELECT id FROM orders;")]
        if "count(*)" in sql:
            return SimpleNamespace(scalar=lambda: 42)
        return []


def test_postgres_discovery_with_fake_engine():
    log = []
    engine = SimpleNamespace(connect=lambda: FakeConn(log))
    snap = PostgresConnector("h", "d", "u", engine=engine).discover()
    orders = snap.table("orders")
    assert orders.column("id").primary_key and orders.column("amt").nullable and orders.column("amt").type == "NUMERIC(10,2)" and orders.row_count == 42
    assert snap.table("v_o").definition == "SELECT id FROM orders"
    assert all(p is None or isinstance(p, dict) for _, p in log)  # values are always bound parameters
    assert any('"public"."orders"' in s for s, _ in log)  # identifiers are quoted


def test_postgres_engine_is_configured_read_only(monkeypatch):
    seen = {}
    monkeypatch.setattr("missync.connectors.postgres.validate_host", lambda h: seen.setdefault("host", h))
    monkeypatch.setattr("missync.connectors.postgres.create_engine", lambda url, **kw: seen.update(kw=kw, url=url) or SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr("missync.connectors.postgres.event", SimpleNamespace(listens_for=lambda *a, **k: (lambda f: f)))
    PostgresConnector("db.internal", "d", "u", "secret-pw")
    opts = seen["kw"]["connect_args"]["options"]
    assert "default_transaction_read_only=on" in opts and "statement_timeout=" in opts
    assert seen["host"] == "db.internal"
    assert "secret-pw" not in repr(seen["url"])  # sqlalchemy masks passwords in repr


# --- BigQuery / Snowflake: official clients replaced by fakes (no cloud access in tests) ------------------
def test_bigquery_adapter_with_fake_client():
    field = lambda n, t, m="NULLABLE": SimpleNamespace(name=n, field_type=t, mode=m)  # noqa: E731
    tables = {
        "orders": SimpleNamespace(table_id="orders", table_type="TABLE", schema=[field("id", "INTEGER", "REQUIRED"), field("amt", "NUMERIC")], num_rows=7, view_query=None),
        "v": SimpleNamespace(table_id="v", table_type="VIEW", schema=[field("id", "INTEGER")], num_rows=None, view_query="SELECT id FROM `p.d.orders`"),
    }
    client = SimpleNamespace(
        get_dataset=lambda ref: object(),
        list_tables=lambda ds: [SimpleNamespace(reference=k) for k in tables],
        get_table=lambda ref: tables[ref],
    )
    c = BigQueryConnector("p", "d", client=client)
    snap = c.discover()
    assert snap.dialect == "bigquery" and snap.table("orders").column("id").nullable is False
    assert snap.table("v").definition.startswith("SELECT") and snap.table("orders").row_count == 7
    assert c.capabilities.sandbox_validation is False
    with pytest.raises(ConnectorError):
        c.fetch_rows("orders", 10)


def test_snowflake_adapter_with_fake_connection():
    class Cur:
        def __init__(self):
            self.rows = []

        def execute(self, sql, params=()):
            if "information_schema.tables" in sql:
                self.rows = [("ORDERS", "BASE TABLE", 5), ("V", "VIEW", None)]
            elif "information_schema.columns" in sql:
                self.rows = [("ORDERS", "ID", "NUMBER", "NO"), ("V", "ID", "NUMBER", "YES")]
            elif "information_schema.views" in sql:
                self.rows = [("V", "SELECT ID FROM ORDERS")]
            else:
                self.rows = [("8.0",)]
            assert "%s" in sql or "information_schema" not in sql  # parameterised

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    conn = SimpleNamespace(cursor=Cur, close=lambda: None)
    c = SnowflakeConnector("acct", "u", "DB", connection=conn)
    snap = c.discover()
    assert snap.table("ORDERS").row_count == 5 and snap.table("V").definition == "SELECT ID FROM ORDERS"
    assert "Snowflake" in c.test()["server"]


def test_snowflake_requires_credentials():
    pytest.importorskip("snowflake.connector")
    with pytest.raises(ConnectorError):
        SnowflakeConnector("8.8.8.8", "u", "DB")
