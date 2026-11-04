from missync.analysis.lineage import build_lineage, downstream, to_impact_graph
from missync.analysis.sql_parser import view_dependencies
from missync.models import Column, SchemaSnapshot, Table


def test_view_dependencies():
    deps, _ = view_dependencies("SELECT a.x, b.y FROM a JOIN b ON a.id=b.id", "sqlite")
    assert deps == ["a", "b"]


def test_graph_structure(sqlite_conn, assets):
    g = build_lineage(sqlite_conn.discover(), assets)
    assert g.table_edges["orders"] == {"v_daily_revenue", "v_customer_ltv", "v_order_details"}
    assert "v_daily_revenue.revenue" in g.col_edges["orders.amount"]
    assert not g.incomplete_views


def test_column_level_impact_is_precise(sqlite_conn, assets):
    g = build_lineage(sqlite_conn.discover(), assets)
    r = downstream(g, [{"table": "orders", "column": "discount_code"}])
    assert r["objects"] == {} and r["assets"] == []
    r = downstream(g, [{"table": "orders", "column": "amount"}])
    assert "v_daily_revenue.revenue" in r["columns"]
    names = {a.name for a, _ in r["assets"]}
    assert {"Revenue Dashboard", "Finance Monthly Export", "Churn Model Features"} <= names
    graph = to_impact_graph(g, [{"table": "orders", "column": "amount"}], r)
    assert any(n.changed for n in graph.nodes) and any(n.type == "asset" and n.impacted for n in graph.nodes)


def test_table_level_change_cascades(sqlite_conn, assets):
    g = build_lineage(sqlite_conn.discover(), assets)
    r = downstream(g, [{"table": "customers"}])
    assert {"v_customer_ltv", "v_order_details"} <= set(r["objects"])


def test_unparsable_view_marks_lineage_incomplete():
    snap = SchemaSnapshot(
        dialect="sqlite",
        tables=[
            Table(name="t", columns=[Column(name="a", type="INTEGER")]),
            Table(name="v", kind="view", columns=[Column(name="a", type="INTEGER")], definition="SELEC((("),
            Table(name="w", kind="view", columns=[Column(name="a", type="INTEGER")], definition=None),
        ],
    )
    g = build_lineage(snap)
    assert set(g.incomplete_views) == {"v", "w"}
    assert downstream(g, [{"table": "t"}])["partial"] is True
