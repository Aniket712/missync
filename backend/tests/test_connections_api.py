import shutil

import pytest

from missync.api.app import friendly_error
from missync.config import get_settings


@pytest.fixture()
def selfhosted(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MISSYNC_MODE", "self-hosted")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from missync.api.app import create_app
    from missync.store.db import Store

    with TestClient(create_app(Store(f"sqlite:///{(tmp_path / 'meta.db').as_posix()}"))) as c:
        yield c, tmp_path
    get_settings.cache_clear()


def _sqlite_body(tmp_path, demo_db):
    shutil.copy(demo_db, tmp_path / "copy.sqlite")
    return {"name": "Copy", "type": "sqlite", "params": {"path": "copy.sqlite"}}


def test_stateless_test_does_not_save(selfhosted, demo_db):
    c, tmp = selfhosted
    before = len(c.get("/api/connections").json())
    r = c.post("/api/connections/test", json=_sqlite_body(tmp, demo_db))
    assert r.status_code == 200, r.text
    assert r.json()["objects"] > 0 and "latency_ms" in r.json()
    assert len(c.get("/api/connections").json()) == before


def test_add_preview_and_delete(selfhosted, demo_db):
    c, tmp = selfhosted
    cid = c.post("/api/connections", json=_sqlite_body(tmp, demo_db)).json()["id"]
    r = c.get(f"/api/connections/{cid}/preview", params={"table": "orders", "limit": 5})
    assert r.status_code == 200 and len(r.json()["rows"]) == 5 and "order_id" in r.json()["columns"]
    assert c.get(f"/api/connections/{cid}/preview", params={"table": "orders; drop table orders"}).status_code == 404
    assert c.delete(f"/api/connections/{cid}").status_code == 204


def test_demo_mode_blocks_test_and_sample(client):
    body = {"name": "x", "type": "sqlite", "params": {"path": "a.sqlite"}}
    assert client.post("/api/connections/test", json=body).status_code == 403
    assert client.post("/api/sample-postgres/start").status_code == 403


def test_unknown_type_rejected(selfhosted):
    c, _ = selfhosted
    assert c.post("/api/connections/test", json={"name": "x", "type": "nope", "params": {}}).status_code == 422


@pytest.mark.parametrize(
    "msg,expect",
    [
        ('FATAL: password authentication failed for user "bob"', "Authentication failed"),
        ('FATAL: database "zzz" does not exist', "database does not exist"),
        ("connection refused", "Could not reach the server"),
    ],
)
def test_friendly_errors_do_not_echo_driver_text(msg, expect):
    out = friendly_error(Exception(msg))
    assert expect in out and "bob" not in out and "zzz" not in out


def test_builtin_demo_path_is_repaired_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MISSYNC_MODE", "demo")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from missync.api.app import create_app
    from missync.store.db import Store

    st = Store(f"sqlite:///{(tmp_path / 'meta.db').as_posix()}")
    st.add_connection("Demo", "sqlite", {"path": "../stale/demo.sqlite"}, builtin=True, id_="demo")
    with TestClient(create_app(st)) as c:
        assert c.post("/api/connections/demo/test").status_code == 200
    get_settings.cache_clear()
