from missync.analysis.schema_diff import classify_type_change, diff_schemas, signature, type_family
from missync.models import Column, SchemaSnapshot, Table


def snap(*tables):
    return SchemaSnapshot(dialect="duckdb", tables=list(tables))


def tbl(name, cols, kind="table", definition=None):
    return Table(name=name, kind=kind, columns=[Column(name=n, type=t, nullable=nl) for n, t, nl in cols], definition=definition)


def test_type_families():
    assert type_family("DECIMAL(10,2)") == "decimal"
    assert type_family("bigint") == "int"
    assert type_family("VARCHAR(20)") == "text"


def test_type_change_classification():
    assert classify_type_change("DECIMAL(10,2)", "INTEGER") == "narrowing"
    assert classify_type_change("INTEGER", "BIGINT") == "widening"
    assert classify_type_change("BIGINT", "INTEGER") == "narrowing"
    assert classify_type_change("DECIMAL(10,2)", "DECIMAL(12,2)") == "widening"
    assert classify_type_change("DECIMAL(12,2)", "DECIMAL(8,2)") == "narrowing"
    assert classify_type_change("INTEGER", "DOUBLE") == "widening"
    assert classify_type_change("VARCHAR", "INTEGER") == "narrowing"
    assert classify_type_change("JSON", "BOOLEAN") == "incompatible"
    assert classify_type_change("INTEGER", "integer") == "same"


def test_diff_all_change_kinds():
    before = snap(tbl("a", [("id", "INTEGER", False), ("x", "VARCHAR", True), ("n", "INTEGER", True)]), tbl("gone", [("c", "INTEGER", True)]))
    after = snap(tbl("a", [("id", "BIGINT", False), ("y", "VARCHAR", True), ("n", "INTEGER", False)]), tbl("new", [("c", "INTEGER", True)]))
    kinds = {(d["change"], d["table"], d.get("column")) for d in diff_schemas(before, after)}
    assert ("table_removed", "gone", None) in kinds
    assert ("table_added", "new", None) in kinds
    assert ("column_removed", "a", "x") in kinds
    assert ("column_added", "a", "y") in kinds
    assert ("type_changed", "a", "id") in kinds
    assert ("nullability_changed", "a", "n") in kinds


def test_view_definition_change_and_formatting_noise():
    v1 = snap(tbl("v", [("a", "INTEGER", True)], "view", "SELECT a FROM t"))
    v2 = snap(tbl("v", [("a", "INTEGER", True)], "view", "select  a\nfrom t"))
    v3 = snap(tbl("v", [("a", "INTEGER", True)], "view", "SELECT a FROM t WHERE a > 1"))
    assert diff_schemas(v1, v2) == []
    assert [d["change"] for d in diff_schemas(v1, v3)] == ["view_definition_changed"]


def test_signature_stable_and_sensitive():
    a = snap(tbl("a", [("id", "INTEGER", False)]))
    assert signature(a) == signature(snap(tbl("a", [("id", "INTEGER", False)])))
    assert signature(a) != signature(snap(tbl("a", [("id", "BIGINT", False)])))
