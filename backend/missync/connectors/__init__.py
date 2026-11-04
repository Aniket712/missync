from __future__ import annotations

import re
from typing import Any

from .base import Connector, ConnectorError

# type -> (module, class, required params)
REGISTRY: dict[str, tuple[str, str, list[str]]] = {
    "sqlite": ("sqlite", "SQLiteConnector", ["path"]),
    "duckdb": ("duckdb_conn", "DuckDBConnector", []),  # path and/or files
    "files": ("duckdb_conn", "DuckDBConnector", ["files"]),
    "postgres": ("postgres", "PostgresConnector", ["host", "database", "user"]),
    "bigquery": ("bigquery", "BigQueryConnector", ["project", "dataset"]),
    "snowflake": ("snowflake", "SnowflakeConnector", ["account", "user", "database"]),
}

NETWORK_TYPES = {"postgres", "bigquery", "snowflake"}

# Only these user-supplied keys ever reach a connector constructor (blocks injected internals such as `engine`).
ALLOWED_PARAMS: dict[str, set[str]] = {
    "sqlite": {"path"},
    "duckdb": {"path", "files"},
    "files": {"files"},
    "postgres": {"host", "port", "database", "user", "password", "schema", "sslmode"},
    "bigquery": {"project", "dataset", "credentials_json"},
    "snowflake": {"account", "user", "database", "schema", "warehouse", "role", "password", "private_key", "private_key_passphrase"},
}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,62}")


def _validate_params(type_: str, params: dict[str, Any]) -> None:
    extra = sorted(set(params) - ALLOWED_PARAMS[type_])
    if extra:
        raise ConnectorError(f"Unsupported parameters for {type_}: {', '.join(extra)}")
    if type_ == "postgres":
        if "sslmode" in params and params["sslmode"] not in SSL_MODES:
            raise ConnectorError("Invalid sslmode")
        if "schema" in params and not _IDENT.fullmatch(str(params["schema"])):
            raise ConnectorError("Invalid schema name")
        if "port" in params and not (isinstance(params["port"], int) and 0 < params["port"] < 65536):
            raise ConnectorError("Port must be a number between 1 and 65535")


def build_connector(type_: str, params: dict[str, Any], enforce_path: bool = True) -> Connector:
    if type_ not in REGISTRY:
        raise ConnectorError(f"Unknown connector type: {type_}")
    mod_name, cls_name, required = REGISTRY[type_]
    _validate_params(type_, params)
    missing = [r for r in required if not params.get(r)]
    if missing:
        raise ConnectorError(f"Missing parameters: {', '.join(missing)}")
    if type_ == "duckdb" and not (params.get("path") or params.get("files")):
        raise ConnectorError("Provide a DuckDB 'path' or a list of 'files'")
    import importlib

    cls = getattr(importlib.import_module(f"{__package__}.{mod_name}"), cls_name)
    kwargs = dict(params)
    if type_ in ("sqlite", "duckdb", "files"):
        kwargs["enforce_path"] = enforce_path
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ConnectorError(f"Invalid parameters for {type_}: {e}") from e


__all__ = ["NETWORK_TYPES", "REGISTRY", "Connector", "ConnectorError", "build_connector"]
