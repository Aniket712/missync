import json
import logging

import pytest

from missync.config import Settings
from missync.security import SecurityError, decrypt, encrypt, install_log_redaction, redact, validate_host, validate_local_path


def test_redact_secrets_and_urls():
    d = redact({"host": "h", "password": "pw", "nested": {"private_key": "k"}, "url": "postgresql://u:hunter2@h/db"})
    assert d["password"] == "***" and d["nested"]["private_key"] == "***" and "hunter2" not in d["url"]


def test_log_redaction(caplog):
    install_log_redaction()
    log = logging.getLogger("missync")
    log.addHandler(caplog.handler)
    log.warning("connecting to postgresql://u:hunter2@h/db")
    assert "hunter2" not in caplog.text


def test_encrypt_roundtrip(tmp_path):
    s = Settings(data_dir=tmp_path)
    tok = encrypt("secret", s)
    assert tok != "secret" and decrypt(tok, s) == "secret"


@pytest.mark.parametrize("host", ["169.254.169.254", "0.0.0.0", "bad host!", "", "224.0.0.1"])
def test_ssrf_blocks_metadata_and_invalid(host):
    with pytest.raises(SecurityError):
        validate_host(host, Settings())


def test_ssrf_private_toggle_and_allowlist():
    with pytest.raises(SecurityError):
        validate_host("127.0.0.1", Settings(allow_private_hosts=False))
    validate_host("127.0.0.1", Settings(allow_private_hosts=True))
    with pytest.raises(SecurityError):
        validate_host("127.0.0.1", Settings(allowed_hosts="db.example.com"))


def test_local_path_confined(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert validate_local_path("a.db", s).parent == tmp_path.resolve()
    with pytest.raises(SecurityError):
        validate_local_path("../x.db", s)
    assert validate_local_path(str(tmp_path.parent / "x.db"), Settings(data_dir=tmp_path, allow_local_paths=True))


# ---- API ------------------------------------------------------------------------------------
def test_config_and_demo_connection(client):
    assert client.get("/api/config").json()["demo"] is True
    conns = client.get("/api/connections").json()
    assert [c["id"] for c in conns] == ["demo"]
    schema = client.get("/api/connections/demo/schema").json()
    assert any(t["name"] == "orders" for t in schema["schema"]["tables"])


def test_demo_mode_blocks_custom_connections(client):
    r = client.post("/api/connections", json={"name": "x", "type": "postgres", "params": {"host": "127.0.0.1", "database": "d", "user": "u"}})
    assert r.status_code == 403
    r = client.post("/api/analyses", json={"connection_id": "other", "sql": "select 1"})
    assert r.status_code in (403, 404)


def test_scenario_run_report_exports(client):
    r = client.post("/api/scenarios/type-change/run")
    assert r.status_code == 200
    a = r.json()
    assert a["summary"]["highest_severity"] == "critical"
    aid = a["id"]
    assert client.get("/api/analyses").json()[0]["id"] == aid
    j = client.get(f"/api/analyses/{aid}/report.json")
    assert json.loads(j.text)["id"] == aid and "attachment" in j.headers["content-disposition"]
    h = client.get(f"/api/analyses/{aid}/report.html")
    assert h.status_code == 200 and "Missync report" in h.text and "orders.amount" in h.text
    assert "default-src 'none'" in h.headers["content-security-policy"]


def test_html_report_escapes_user_content(client):
    r = client.post("/api/analyses", json={"connection_id": "demo", "title": "<script>alert(1)</script>", "sql": "SELECT 1", "sql_dialect": "postgres"})
    assert r.status_code == 200
    html = client.get(f"/api/analyses/{r.json()['id']}/report.html").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_bad_sql_returns_422(client):
    r = client.post("/api/analyses", json={"connection_id": "demo", "sql": "SELEC (("})
    assert r.status_code == 422
    r = client.post("/api/analyses", json={"connection_id": "demo", "sql": "x" * 300_000})
    assert r.status_code in (413, 422)


def test_unsafe_metric_is_rejected_not_executed(client):
    r = client.post("/api/analyses", json={"connection_id": "demo", "sql": "SELECT 1", "sql_dialect": "postgres",
                                           "metrics": [{"name": "evil", "sql": "DELETE FROM orders"}]})
    assert r.status_code == 200
    m = r.json()["metric_comparison"][0]
    assert "rejected" in m["error"]
    assert client.get("/api/connections/demo/schema").json()["schema"]["tables"][0]["row_count"] is not None


def test_baselines_capture_and_compare(client):
    b = client.post("/api/connections/demo/baselines", json={"name": "before"})
    assert b.status_code == 201
    bid = b.json()["id"]
    same = client.get(f"/api/baselines/{bid}/compare").json()
    assert same["schema_changed"] is False and same["schema_diff"] == []
    assert client.get("/api/connections/demo/baselines").json()[0]["has_profile"] is True
    # tamper with the stored baseline to simulate a previous schema state
    store = client.app.state.store
    data = store.get_baseline(bid)
    data["schema"]["tables"] = [t for t in data["schema"]["tables"] if t["name"] != "segment_map"]
    for t in data["schema"]["tables"]:
        if t["name"] == "orders":
            t["columns"] = [c for c in t["columns"] if c["name"] != "discount_code"]
    data["signature"] = "old"
    import json as _j

    from missync.store.db import BaselineRow
    with store.session() as s:
        row = s.get(BaselineRow, bid)
        row.data = _j.dumps({k: v for k, v in data.items() if k not in ("id", "connection_id", "name", "created_at")})
        s.commit()
    cmp = client.get(f"/api/baselines/{bid}/compare").json()
    kinds = {(d["change"], d["table"]) for d in cmp["schema_diff"]}
    assert ("table_added", "segment_map") in kinds and ("column_added", "orders") in kinds
    assert cmp["schema_changed"] is True


def test_secrets_never_returned(tmp_path, monkeypatch):
    from missync.store.db import Store

    monkeypatch.setenv("MISSYNC_DATA_DIR", str(tmp_path))
    from missync.config import get_settings

    get_settings.cache_clear()
    st = Store(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    cid = st.add_connection("pg", "postgres", {"host": "h", "password": "topsecret"})
    listed = json.dumps(st.list_connections())
    assert "topsecret" not in listed
    with st.session() as s:
        from missync.store.db import ConnectionRow

        assert "topsecret" not in s.get(ConnectionRow, cid).params_enc  # encrypted at rest
    get_settings.cache_clear()
