import json
import sqlite3
import time

import pytest

from missync.api.jobs import Cancelled, JobManager
from missync.config import get_settings
from missync.connectors import ConnectorError, build_connector


def _app_client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MISSYNC_MODE", env.pop("MODE", "demo"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from missync.api.app import create_app
    from missync.store.db import Store

    return TestClient(create_app(Store(f"sqlite:///{(tmp_path / 'meta.db').as_posix()}")))


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    get_settings.cache_clear()


# ---- auth ------------------------------------------------------------------------
def test_token_required_when_configured(tmp_path, monkeypatch):
    with _app_client(tmp_path, monkeypatch, MISSYNC_API_TOKEN="s3cret-token") as c:
        assert c.get("/api/health").json()["auth_required"] is True
        assert c.get("/api/ready").status_code == 200
        assert c.get("/api/connections").status_code == 401
        assert c.get("/api/connections", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/connections", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_no_token_means_open(client):
    assert client.get("/api/health").json()["auth_required"] is False
    assert client.get("/api/connections").status_code == 200


def test_body_too_large_and_request_id(tmp_path, monkeypatch):
    with _app_client(tmp_path, monkeypatch, MISSYNC_MAX_BODY_BYTES="1000") as c:
        r = c.post("/api/analyses", content=b"x" * 5000, headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        assert c.get("/api/health").headers["x-request-id"]
        assert c.get("/api/health").headers["x-content-type-options"] == "nosniff"


# ---- connector params ------------------------------------------------------------
def test_unsupported_params_rejected():
    with pytest.raises(ConnectorError, match="Unsupported parameters"):
        build_connector("postgres", {"host": "h", "database": "d", "user": "u", "engine": "x"})
    with pytest.raises(ConnectorError, match="sslmode"):
        build_connector("postgres", {"host": "h", "database": "d", "user": "u", "sslmode": "bogus"})
    with pytest.raises(ConnectorError, match="schema"):
        build_connector("postgres", {"host": "h", "database": "d", "user": "u", "schema": "x; drop table y"})
    with pytest.raises(ConnectorError, match="Port"):
        build_connector("postgres", {"host": "h", "database": "d", "user": "u", "port": 99999})


def test_sample_limit_must_be_positive(client):
    r = client.post("/api/analyses", json={"connection_id": "demo", "sql": "select 1", "sample_limit": 0})
    assert r.status_code == 422


# ---- jobs ------------------------------------------------------------------------
def test_job_lifecycle_over_api(client):
    j = client.post("/api/jobs", json={"connection_id": "demo", "sql": "ALTER TABLE orders DROP COLUMN discount_code;", "sql_dialect": "postgres"})
    assert j.status_code == 202
    jid = j.json()["id"]
    for _ in range(200):
        st = client.get(f"/api/jobs/{jid}").json()
        if st["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert st["percent"] == 100 and st["result_id"]
    assert client.get(f"/api/analyses/{st['result_id']}").status_code == 200
    assert client.get("/api/jobs/nope").status_code == 404


def test_job_failure_is_reported(client):
    j = client.post("/api/jobs", json={"connection_id": "demo", "sql": "SELEC (("}).json()
    for _ in range(100):
        st = client.get(f"/api/jobs/{j['id']}").json()
        if st["status"] != "queued" and st["status"] != "running":
            break
        time.sleep(0.1)
    assert st["status"] == "failed" and st["error"]


def test_job_cancel_and_deadline():
    jm = JobManager(workers=1, deadline_s=1)

    def slow(progress):
        for i in range(100):
            progress(f"step {i}", i)
            time.sleep(0.05)
        return "never"

    job = jm.submit(slow, lambda e: (500, str(e)))
    time.sleep(0.2)
    assert jm.cancel(job.id)
    assert job.done.wait(3) and job.status == "cancelled"

    def stuck(progress):
        while True:
            progress("working", 10)
            time.sleep(0.05)

    j2 = jm.submit(stuck, lambda e: (500, str(e)))
    assert j2.done.wait(5) and j2.status == "failed" and "limit" in j2.error
    jm.shutdown()
    assert issubclass(Cancelled, Exception)


# ---- history ---------------------------------------------------------------------
def test_history_filter_search_delete(tmp_path, monkeypatch):
    with _app_client(tmp_path, monkeypatch, MODE="self-hosted") as c:
        a = c.post("/api/analyses", json={"connection_id": "demo", "title": "Alpha drop", "sql": "ALTER TABLE orders DROP COLUMN discount_code;", "sql_dialect": "postgres"}).json()
        c.post("/api/analyses", json={"connection_id": "demo", "title": "Beta noop", "sql": "SELECT 1", "sql_dialect": "postgres"})
        assert len(c.get("/api/analyses").json()) == 2
        assert [x["title"] for x in c.get("/api/analyses", params={"q": "alpha"}).json()] == ["Alpha drop"]
        assert all(x["severity"] == a["summary"]["highest_severity"] for x in c.get("/api/analyses", params={"severity": a["summary"]["highest_severity"]}).json())
        assert len(c.get("/api/analyses", params={"limit": 1, "offset": 1}).json()) == 1
        assert c.delete(f"/api/analyses/{a['id']}").status_code == 204
        assert c.delete(f"/api/analyses/{a['id']}").status_code == 404


def test_history_is_pruned(tmp_path, monkeypatch):
    with _app_client(tmp_path, monkeypatch, MISSYNC_HISTORY_LIMIT="2") as c:
        for i in range(4):
            c.post("/api/analyses", json={"connection_id": "demo", "title": f"t{i}", "sql": "SELECT 1", "sql_dialect": "postgres"})
        assert len(c.get("/api/analyses").json()) == 2


def test_demo_blocks_history_and_baseline_delete(client):
    assert client.delete("/api/analyses/x").status_code == 403
    assert client.delete("/api/baselines/x").status_code == 403


# ---- store migration -------------------------------------------------------------
def test_store_migrates_old_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("create table analyses (id varchar primary key, connection_id varchar, title varchar, created_at varchar, severity varchar, data text not null)")
    data = {"summary": {"highest_severity": "low"}, "findings": [{}, {}]}
    con.execute("insert into analyses values ('a1','demo','Old one','2024-01-01','low',?)", (json.dumps(data),))
    con.commit()
    con.close()

    from missync.store.db import SCHEMA_VERSION, Store

    st = Store(f"sqlite:///{db.as_posix()}")
    rows = st.list_analyses()
    assert rows[0]["title"] == "Old one" and rows[0]["finding_count"] == 2
    with st.engine.connect() as c:
        assert c.exec_driver_sql("select max(version) from schema_version").scalar() == SCHEMA_VERSION
        assert c.exec_driver_sql("pragma journal_mode").scalar() == "wal"
    Store(f"sqlite:///{db.as_posix()}")  # re-opening is a no-op


# ---- CLI -------------------------------------------------------------------------
def test_cli_exit_codes_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path / "d"))
    get_settings.cache_clear()
    from missync.cli import main

    bad = tmp_path / "bad.sql"
    bad.write_text("ALTER TABLE orders DROP COLUMN discount_code;")
    ok = tmp_path / "ok.sql"
    ok.write_text("SELECT 1")
    report = tmp_path / "r.json"

    assert main(["analyze", "--demo", "--sql", str(bad), "--dialect", "postgres"]) == 1
    assert "discount_code" in capsys.readouterr().out
    assert main(["analyze", "--demo", "--sql", str(bad), "--fail-on", "never"]) == 0
    assert main(["analyze", "--demo", "--sql", str(ok), "--format", "json", "--output", str(report)]) == 0
    assert json.loads(report.read_text())["generator"] == "missync"
    assert main(["analyze", "--demo", "--sql", str(ok), "--format", "html"]) == 2  # html needs --output
    assert main(["analyze", "--demo"]) == 2  # no SQL
    assert main(["analyze", "--sql", str(ok)]) == 2  # no source


def test_cli_migration_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path / "d"))
    get_settings.cache_clear()
    from missync.cli import main

    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_a.sql").write_text("ALTER TABLE orders ADD COLUMN note text;")
    (mig / "002_b.sql").write_text("ALTER TABLE orders DROP COLUMN discount_code;")
    assert main(["analyze", "--demo", "--dir", str(mig), "--dialect", "postgres", "--fail-on", "high"]) == 1


def test_cli_refuses_open_nonlocal_bind(monkeypatch, capsys):
    monkeypatch.setenv("MISSYNC_MODE", "self-hosted")
    monkeypatch.delenv("MISSYNC_API_TOKEN", raising=False)
    get_settings.cache_clear()
    from missync.cli import main

    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "MISSYNC_API_TOKEN" in capsys.readouterr().err


# ---- packaging ---------------------------------------------------------------------
def test_packaged_seed_sql_matches_docker_copy():
    from pathlib import Path

    from missync.demo import sample_pg

    docker_copy = Path(__file__).resolve().parents[2] / "docker" / "postgres-init.sql"
    if docker_copy.exists():  # absent when tests run from an sdist
        assert sample_pg.SEED_SQL.read_text(encoding="utf-8") == docker_copy.read_text(encoding="utf-8")
    assert sample_pg.SEED_SQL.exists()


def test_frontend_dist_override(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setenv("MISSYNC_FRONTEND_DIST", str(tmp_path))
    get_settings.cache_clear()
    from missync.api.app import find_frontend_dist

    assert find_frontend_dist(get_settings()) == tmp_path
