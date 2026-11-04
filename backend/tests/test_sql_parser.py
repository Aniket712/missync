import pytest

from missync.analysis.sql_parser import SqlRejected, analyze_statements, assert_single_select


def ops(sql, dialect="postgres"):
    return [c["op"] for s in analyze_statements(sql, dialect) for c in s.changes]


def test_alter_operations():
    sql = (
        "ALTER TABLE orders DROP COLUMN discount_code; ALTER TABLE orders ALTER COLUMN amount TYPE INTEGER;"
        "ALTER TABLE orders RENAME COLUMN status TO state; ALTER TABLE orders ADD COLUMN note TEXT;"
    )
    assert ops(sql) == ["drop_column", "alter_type", "rename_column", "add_column"]
    first = analyze_statements(sql, "postgres")[0].changes[0]
    assert first["column"] == "discount_code" and first["table"] == "orders"


def test_drop_and_destructive_flags():
    s = analyze_statements("DROP TABLE orders", "postgres")[0]
    assert s.kind == "drop" and s.destructive and s.tables_written == ["orders"]


def test_delete_update_without_where():
    d, u, ok = analyze_statements("DELETE FROM t; UPDATE t SET a=1; DELETE FROM t WHERE a=1", "postgres")
    assert d.no_where and u.no_where and not ok.no_where


def test_tables_read_ignores_ctes():
    s = analyze_statements("CREATE TABLE x AS WITH c AS (SELECT * FROM a) SELECT * FROM c JOIN b ON 1=1", "postgres")[0]
    assert sorted(s.tables_read) == ["a", "b"] and s.tables_written == ["x"]


def test_create_or_replace_view_is_flagged():
    s = analyze_statements("CREATE OR REPLACE VIEW v AS SELECT 1 AS a", "postgres")[0]
    assert s.kind == "create_view" and s.changes[0]["op"] == "replace_object"


def test_parse_errors_and_empty():
    with pytest.raises(SqlRejected):
        analyze_statements("SELEC FROM WHERE ((", "postgres")
    with pytest.raises(SqlRejected):
        analyze_statements("   ", "postgres")


def test_assert_single_select_blocks_writes():
    assert_single_select("SELECT 1", "postgres")
    for bad in ("SELECT 1; SELECT 2", "DELETE FROM t", "DROP TABLE t", "SELECT * INTO x FROM t"):
        with pytest.raises(SqlRejected):
            assert_single_select(bad, "postgres")
