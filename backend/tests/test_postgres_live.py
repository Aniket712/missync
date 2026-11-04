"""Integration tests against a real PostgreSQL seeded with docker/postgres-init.sql.

Skipped unless MISSYNC_TEST_PG_PORT is set (host defaults to 127.0.0.1, user missync_ro, db shop).
"""
import os

import pytest
from sqlalchemy import text

from missync.analysis.engine import run_analysis
from missync.connectors.postgres import PostgresConnector
from missync.demo.scenarios import scenario_request
from missync.models import AnalysisRequest

PORT = os.environ.get("MISSYNC_TEST_PG_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="set MISSYNC_TEST_PG_PORT to run against a live PostgreSQL")


@pytest.fixture()
def pg():
    c = PostgresConnector(os.environ.get("MISSYNC_TEST_PG_HOST", "127.0.0.1"), "shop", "missync_ro", os.environ.get("MISSYNC_TEST_PG_PASSWORD", ""), port=int(PORT))
    yield c
    c.close()


def test_discovery_and_types(pg):
    snap = pg.discover()
    assert snap.table("orders").row_count == 5000
    assert snap.table("orders").column("amount").type == "NUMERIC(10,2)"
    assert snap.table("v_daily_revenue").definition.upper().startswith("SELECT")
    assert pg.test()["read_only"] is True


def test_writes_are_rejected(pg):
    for stmt in ("delete from customers", "create table x(a int)"):
        with pytest.raises(Exception, match="read-only"), pg.engine.connect() as c:
            c.execute(text(stmt))


def test_scenario_and_source_untouched(pg, assets):
    r = run_analysis(pg, AnalysisRequest(**scenario_request("missing-records", "pg")), assets)
    f = next(f for f in r.findings if f.category == "missing_records")
    assert f.evidence["missing_in_candidate"] == 250
    with pg.engine.connect() as c:
        assert c.execute(text("select count(*) from customers")).scalar() == 1000
