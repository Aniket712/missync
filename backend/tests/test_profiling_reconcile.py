import duckdb

from missync.analysis.profiling import compare_profiles, profile_schema
from missync.analysis.reconcile import reconcile_table
from missync.models import Column, SchemaSnapshot, Table


class R:
    def __init__(self):
        self.c = duckdb.connect()
        self.c.execute("create schema base; create schema cand")

    def query(self, schema, sql, params=None):
        self.c.execute(f"use {schema}")
        cur = self.c.execute(sql, params or [])
        return [d[0] for d in cur.description or []], cur.fetchall()


def snap():
    return SchemaSnapshot(
        dialect="duckdb",
        tables=[Table(name="t", columns=[Column(name="id", type="INTEGER"), Column(name="v", type="DOUBLE"), Column(name="s", type="VARCHAR")])],
    )


def setup():
    r = R()
    r.c.execute("create table base.t as select * from (values (1,10.0,'a'),(2,20.0,NULL),(3,30.0,'c'),(3,5.0,'c')) x(id,v,s)")
    r.c.execute("create table cand.t as select * from (values (1,10.0,'a'),(2,25.0,NULL),(4,1.0,'z')) x(id,v,s)")
    return r


def test_profile_values_and_duplicate_keys():
    r = setup()
    p = profile_schema(r, "base", snap(), {"t": ["id"]})["t"]
    assert p["row_count"] == 4
    assert p["columns"]["s"]["null_count"] == 1 and p["columns"]["s"]["null_rate"] == 0.25
    assert p["columns"]["v"]["sum"] == 65 and p["columns"]["v"]["max"] == 30
    assert p["key"]["duplicate_keys"] == 1 and p["key"]["rows_in_duplicate_keys"] == 2


def test_compare_profiles_row_and_null_deltas():
    r = setup()
    c = compare_profiles(profile_schema(r, "base", snap()), profile_schema(r, "cand", snap()))[0]
    assert c["row_delta"] == -1 and c["row_delta_pct"] == -25.0
    s = next(x for x in c["columns"] if x["column"] == "s")
    assert round(s["null_rate_delta"], 4) == round(1 / 3 - 0.25, 4)


def test_reconcile_refuses_nonunique_baseline_key():
    r = setup()
    prof = profile_schema(r, "base", snap(), {"t": ["id"]})["t"]
    res = reconcile_table(r, snap(), snap(), "t", ["id"], prof)
    assert res["status"] == "unavailable" and "not unique" in res["reason"]


def test_reconcile_counts():
    r = setup()
    r.c.execute("delete from base.t where id=3 and v=5.0")
    prof = profile_schema(r, "base", snap(), {"t": ["id"]})["t"]
    res = reconcile_table(r, snap(), snap(), "t", ["id"], prof)
    assert res["status"] == "compared"
    assert res["missing_in_candidate"] == 1 and res["new_in_candidate"] == 1 and res["matched"] == 2
    assert res["changed_rows"] == 1 and res["changed_by_column"] == {"v": 1}
    assert res["missing_examples"] == [["3"]]


def test_reconcile_missing_key_column():
    r = setup()
    assert reconcile_table(r, snap(), snap(), "t", ["nope"])["status"] == "unavailable"
