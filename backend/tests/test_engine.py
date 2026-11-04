import pytest

from missync.analysis.engine import run_analysis
from missync.demo.scenarios import SCENARIOS, scenario_request
from missync.models import AnalysisRequest


def run(conn, assets, sid=None, **kw):
    req = scenario_request(sid, "demo") if sid else {"connection_id": "demo", **kw}
    return run_analysis(conn, AnalysisRequest(**req), assets)


def test_type_change_scenario(sqlite_conn, assets):
    r = run(sqlite_conn, assets, "type-change")
    f = next(f for f in r.findings if f.category == "schema")
    assert f.severity == "critical" and f.kind == "verified" and f.evidence["compatibility"] == "narrowing"
    vc = next(f for f in r.findings if f.category == "value_change")
    assert vc.evidence["changed_rows"] > 4900  # measured, not guessed
    assert "Revenue Dashboard" in r.summary["impacted_objects"]


def test_missing_records_scenario_matches_ground_truth(sqlite_conn, assets):
    expected = sqlite_conn.query("select count(*) from customers where email like '%shop-demo.test' and country in ('BR','IN')")[1][0][0]
    r = run(sqlite_conn, assets, "missing-records")
    f = next(f for f in r.findings if f.category == "missing_records")
    assert f.evidence["missing_in_candidate"] == expected
    assert f.possibly_intended  # a DELETE with WHERE: may be intended
    assert any(x.category == "row_count" and x.affected[0] == "v_order_details" for x in r.findings)


def test_metric_drift_scenario(sqlite_conn, assets):
    r = run(sqlite_conn, assets, "metric-drift")
    m = next(f for f in r.findings if f.category == "metric" and "revenue" in f.title.lower())
    assert m.evidence["delta_pct"] > 1 and m.possibly_intended
    assert not any(f.severity == "critical" for f in r.findings)


def test_data_quality_scenario(sqlite_conn, assets):
    r = run(sqlite_conn, assets, "data-quality")
    n = next(f for f in r.findings if f.category == "null_rate")
    assert n.evidence["null_rate_before"] == 0 and 0.4 < n.evidence["null_rate_after"] < 0.6


def test_no_change_reports_no_guarantee(sqlite_conn, assets):
    r = run(sqlite_conn, assets, sql="SELECT 1", sql_dialect="postgres")
    assert r.findings == [] and "not a guarantee" in r.summary["verdict"].lower()


def test_failed_statement_is_reported_not_hidden(sqlite_conn, assets):
    r = run(sqlite_conn, assets, sql="ALTER TABLE orders ALTER COLUMN status TYPE INTEGER;", sql_dialect="postgres")
    assert any(f.category == "execution" and f.severity == "high" for f in r.findings)
    assert any("partial" in line for line in r.limitations)


def test_source_is_never_modified(sqlite_conn, assets):
    run(sqlite_conn, assets, sql="DELETE FROM customers; DROP TABLE orders;", sql_dialect="postgres")
    assert sqlite_conn.row_count("customers") == 1000
    assert sqlite_conn.row_count("orders") == 5000


def test_sandbox_blocks_file_access(sqlite_conn, assets):
    r = run(sqlite_conn, assets, sql="CREATE TABLE leak AS SELECT * FROM read_csv('/etc/passwd');", sql_dialect="duckdb")
    assert any(f.category == "execution" for f in r.findings)
    r = run(sqlite_conn, assets, sql="COPY customers TO 'out.csv';", sql_dialect="duckdb")
    assert not any(o["status"] == "executed" for o in r.validation["outcomes"])


def test_sampling_is_disclosed(sqlite_conn, assets):
    r = run(sqlite_conn, assets, "type-change")
    r2 = run_analysis(sqlite_conn, AnalysisRequest(**{**scenario_request("type-change", "demo"), "sample_limit": 100}), assets)
    assert any("sampled" in line for line in r2.limitations)
    assert not any("sampled" in line for line in r.limitations)


def test_unregistered_assets_are_disclosed(sqlite_conn):
    r = run(sqlite_conn, [], "type-change")
    assert any("No downstream assets" in line for line in r.limitations)


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_all_scenarios_deterministic(sqlite_conn, assets, sid):
    a = run(sqlite_conn, assets, sid)
    b = run(sqlite_conn, assets, sid)
    assert [(f.title, f.severity) for f in a.findings] == [(f.title, f.severity) for f in b.findings]


def test_duplicate_keys_detected(sqlite_conn, assets):
    r = run(sqlite_conn, assets, sql="INSERT INTO customers SELECT * FROM customers WHERE country = 'US';", sql_dialect="postgres")
    assert any(f.category == "duplicate_keys" and f.severity == "high" for f in r.findings)
