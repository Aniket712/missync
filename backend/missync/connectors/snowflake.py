"""Snowflake adapter using snowflake-connector-python.

Authentication: key-pair (`private_key` PEM, optional passphrase) preferred; password supported.
Use a role with USAGE + SELECT only. Validation is static analysis (no sandbox copy).
"""
from __future__ import annotations

from typing import Any

from ..models import Capabilities, Column, SchemaSnapshot, Table
from ..security import validate_host
from .base import Connector, ConnectorError


class SnowflakeConnector(Connector):
    type = "snowflake"
    dialect = "snowflake"
    capabilities = Capabilities(
        sandbox_validation=False,
        read_only_enforced="Use a SELECT-only role; Missync only issues INFORMATION_SCHEMA reads and SELECT.",
        notes="Static analysis only. Not tested against a live Snowflake account.",
    )

    def __init__(
        self,
        account: str,
        user: str,
        database: str,
        schema: str = "PUBLIC",
        warehouse: str | None = None,
        role: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        connection=None,
    ):
        self.database, self.schema = database, schema
        if connection is not None:
            self._conn = connection
            return
        try:
            import snowflake.connector as sf
        except ImportError as e:  # pragma: no cover
            raise ConnectorError("Install snowflake-connector-python to use Snowflake") from e
        validate_host(f"{account}.snowflakecomputing.com" if "." not in account else account)
        kwargs: dict[str, Any] = dict(
            account=account, user=user, database=database, schema=schema, warehouse=warehouse, role=role,
            login_timeout=15, network_timeout=30, session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 30},
        )
        if private_key:
            from cryptography.hazmat.primitives import serialization

            key = serialization.load_pem_private_key(
                private_key.encode(), password=private_key_passphrase.encode() if private_key_passphrase else None
            )
            kwargs["private_key"] = key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        elif password:
            kwargs["password"] = password
        else:
            raise ConnectorError("Provide a private_key (preferred) or password")
        self._conn = sf.connect(**kwargs)

    def _run(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def test(self) -> dict[str, Any]:
        v = self._run("select current_version()")[0][0]
        return {"server": f"Snowflake {v}", "read_only": None}

    def discover(self) -> SchemaSnapshot:
        tables: dict[str, Table] = {}
        for name, ttype, rows in self._run(
            "select table_name, table_type, row_count from information_schema.tables where table_schema = %s",
            (self.schema.upper(),),
        ):
            tables[name] = Table(
                name=name, schema_name=self.schema, kind="view" if ttype == "VIEW" else "table",
                row_count=rows if ttype != "VIEW" else None,
            )
        for tname, cname, dtype, nullable in self._run(
            "select table_name, column_name, data_type, is_nullable from information_schema.columns "
            "where table_schema = %s order by table_name, ordinal_position",
            (self.schema.upper(),),
        ):
            if tname in tables:
                tables[tname].columns.append(Column(name=cname, type=dtype.upper(), nullable=nullable == "YES"))
        for vname, vdef in self._run(
            "select table_name, view_definition from information_schema.views where table_schema = %s",
            (self.schema.upper(),),
        ):
            if vname in tables and vdef:
                tables[vname].definition = vdef
        return SchemaSnapshot(dialect=self.dialect, tables=list(tables.values()))

    def fetch_rows(self, table: str, limit: int):
        raise ConnectorError("Snowflake connector does not copy data; analysis is static")

    def query(self, sql: str, limit: int = 1000):
        from ..analysis.sql_parser import assert_single_select

        assert_single_select(sql, self.dialect)
        cur = self._conn.cursor()
        try:
            cur.execute(sql)
            return [d[0] for d in cur.description], cur.fetchmany(limit)
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()
