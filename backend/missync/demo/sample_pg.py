"""Embedded sample PostgreSQL (via the optional `pgserver` package) so the UI demo needs no Docker or external database."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

SEED_SQL = Path(__file__).resolve().parent / "postgres-init.sql"  # packaged copy of docker/postgres-init.sql
DB_NAME = "shop"
RO_USER = "missync_ro"
RO_PASSWORD = "missync_ro_dev_only"

_lock = threading.Lock()
_server: Any = None


class SampleUnavailable(Exception):
    pass


def _import_pgserver():
    try:
        import pgserver
    except ImportError as e:
        raise SampleUnavailable('The sample database needs the optional "pgserver" package: pip install -e "backend[sample]"') from e
    return pgserver


def _params(port: int) -> dict[str, Any]:
    return {"host": "127.0.0.1", "port": port, "database": DB_NAME, "user": RO_USER, "password": RO_PASSWORD, "schema": "public"}


def _seed(uri: str) -> None:
    import psycopg2

    admin = make_url(uri)
    if not SEED_SQL.exists():
        raise SampleUnavailable("The packaged sample data file (postgres-init.sql) is missing from this install")
    conn = psycopg2.connect(host=admin.host, port=admin.port, user=admin.username, dbname="postgres")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("select 1 from pg_database where datname=%s", (DB_NAME,))
            if not cur.fetchone():
                cur.execute(f"create database {DB_NAME}")
    finally:
        conn.close()
    shop = psycopg2.connect(host=admin.host, port=admin.port, user=admin.username, dbname=DB_NAME)
    try:
        with shop, shop.cursor() as cur:
            cur.execute("select to_regclass('public.customers')")
            if cur.fetchone()[0] is None:  # seed script is transactional, so a failed run leaves nothing behind
                cur.execute(SEED_SQL.read_text(encoding="utf-8"))
    finally:
        shop.close()


def status() -> dict[str, Any]:
    try:
        _import_pgserver()
    except SampleUnavailable as e:
        return {"available": False, "running": False, "message": str(e)}
    return {"available": True, "running": _server is not None, "params": _params(_server_port()) if _server is not None else None}


def _server_port() -> int:
    return make_url(_server.get_uri()).port


def start(data_dir: Path) -> dict[str, Any]:
    """Start (or reuse) the embedded server, seed the shop data once, and return connection params for the read-only role."""
    global _server
    pgserver = _import_pgserver()
    with _lock:
        if _server is None:
            pgdata = data_dir / "sample_pg"
            pgdata.mkdir(parents=True, exist_ok=True)
            _server = pgserver.get_server(pgdata, cleanup_mode="stop")
        try:
            _seed(_server.get_uri())
        except SampleUnavailable:
            raise
        except Exception as e:  # pragma: no cover - environment specific
            raise SampleUnavailable(f"Could not prepare the sample database: {type(e).__name__}") from e
        return {"available": True, "running": True, "params": _params(_server_port())}


def stop() -> None:
    global _server
    with _lock:
        if _server is not None:
            _server.cleanup()
            _server = None
