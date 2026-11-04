"""Static SQL analysis with SQLGlot. Nothing here executes SQL."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..config import get_settings


class SqlRejected(ValueError):
    pass


@dataclass
class Statement:
    index: int
    kind: str  # select, create_table, create_view, alter, drop, insert, update, delete, rename, other
    sql: str
    tables_read: list[str] = field(default_factory=list)
    tables_written: list[str] = field(default_factory=list)
    destructive: bool = False
    no_where: bool = False
    changes: list[dict[str, Any]] = field(default_factory=list)  # structural change hints
    parse_error: str | None = None
    expression: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "kind": self.kind, "sql": self.sql,
            "tables_read": self.tables_read, "tables_written": self.tables_written,
            "destructive": self.destructive, "no_where": self.no_where,
            "changes": self.changes, "parse_error": self.parse_error,
        }


def parse(sql: str, dialect: str) -> list[exp.Expression]:
    if len(sql) > get_settings().max_sql_chars:
        raise SqlRejected("SQL is too large")
    try:
        parsed = [e for e in sqlglot.parse(sql, read=dialect) if e is not None]
    except SqlglotError as e:
        raise SqlRejected(f"SQL could not be parsed: {str(e).splitlines()[0]}") from e
    if not parsed:
        raise SqlRejected("No SQL statements found")
    return parsed


def assert_single_select(sql: str, dialect: str) -> exp.Expression:
    """Guard for ad-hoc/metric queries: exactly one read-only SELECT."""
    stmts = parse(sql, dialect)
    if len(stmts) != 1:
        raise SqlRejected("Exactly one statement is allowed")
    e = stmts[0]
    if not isinstance(e, (exp.Select, exp.Union, exp.Subquery, exp.With)) and not isinstance(e, exp.Query):
        raise SqlRejected("Only SELECT statements are allowed here")
    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Into):
        if e.find(bad):
            raise SqlRejected("Statement contains a write or DDL operation")
    return e


def _tname(t: exp.Table) -> str:
    return t.name


def _target(node: exp.Expression) -> exp.Expression | None:
    """First object named by a DROP node (sqlglot versions store it in this/tables/expressions)."""
    if node.this is not None:
        return node.this
    for key in ("tables", "expressions"):
        vals = node.args.get(key)
        if vals:
            return vals[0]
    return None


def _cte_names(e: exp.Expression) -> set[str]:
    return {c.alias_or_name for c in e.find_all(exp.CTE)}


def _read_tables(e: exp.Expression, exclude: set[str] | None = None) -> list[str]:
    ctes = _cte_names(e)
    out: list[str] = []
    for t in e.find_all(exp.Table):
        n = _tname(t)
        if n and n not in ctes and n not in (exclude or set()) and n not in out:
            out.append(n)
    return out


def classify(e: exp.Expression, index: int, dialect: str) -> Statement:
    sql = e.sql(dialect=dialect)
    st = Statement(index=index, kind="other", sql=sql, expression=e)
    if isinstance(e, exp.Create):
        target = e.this.find(exp.Table) if e.this is not None else None
        tname = _tname(target) if target is not None else ""
        kind = (e.args.get("kind") or "").upper()
        st.kind = "create_view" if kind == "VIEW" else "create_table" if kind == "TABLE" else "create_other"
        st.tables_written = [tname] if tname else []
        if e.expression is not None:
            st.tables_read = _read_tables(e.expression, {tname})
        if e.args.get("replace"):
            st.changes.append({"op": "replace_object", "table": tname, "object": kind.lower()})
    elif isinstance(e, exp.Alter):
        tname = _tname(e.this) if isinstance(e.this, exp.Table) else ""
        st.kind = "alter"
        st.tables_written = [tname]
        for action in e.args.get("actions") or []:
            if isinstance(action, exp.Drop):
                tgt = _target(action)
                col = tgt.name if tgt is not None else ""
                st.changes.append({"op": "drop_column", "table": tname, "column": col})
                st.destructive = True
            elif isinstance(action, exp.AlterColumn):
                col = action.this.name
                dtype = action.args.get("dtype")
                if dtype is not None:
                    st.changes.append(
                        {"op": "alter_type", "table": tname, "column": col, "new_type": dtype.sql(dialect=dialect)}
                    )
                elif action.args.get("drop") and action.args.get("allow_null"):
                    st.changes.append({"op": "drop_not_null", "table": tname, "column": col})
                elif action.args.get("allow_null") is False or action.args.get("drop") is False:
                    st.changes.append({"op": "set_not_null", "table": tname, "column": col})
                else:
                    st.changes.append({"op": "alter_column", "table": tname, "column": col})
            elif isinstance(action, exp.RenameColumn):
                st.changes.append(
                    {"op": "rename_column", "table": tname, "column": action.this.name, "new_name": action.args["to"].name}
                )
                st.destructive = True
            elif isinstance(action, exp.ColumnDef):
                st.changes.append({"op": "add_column", "table": tname, "column": action.name})
            elif isinstance(action, exp.AlterRename):
                st.changes.append({"op": "rename_table", "table": tname, "new_name": action.this.name})
                st.destructive = True
        if e.args.get("kind") and str(e.args["kind"]).upper() != "TABLE":
            st.kind = "alter_other"
    elif isinstance(e, exp.Drop):
        kind = (e.args.get("kind") or "").upper()
        tgt = _target(e)
        tname = _tname(tgt) if isinstance(tgt, exp.Table) else ""
        st.kind = "drop"
        st.destructive = True
        st.tables_written = [tname]
        st.changes.append({"op": "drop_object", "table": tname, "object": kind.lower()})
    elif isinstance(e, exp.Insert):
        st.kind = "insert"
        t = e.this.find(exp.Table) if e.this is not None else None
        st.tables_written = [_tname(t)] if t is not None else []
        if e.expression is not None:
            st.tables_read = _read_tables(e.expression)
    elif isinstance(e, exp.Update):
        st.kind = "update"
        st.tables_written = [_tname(e.this)]
        st.no_where = e.args.get("where") is None
        st.destructive = True
        st.tables_read = [t for t in _read_tables(e) if t != _tname(e.this)]
        st.changes.append({"op": "update_rows", "table": _tname(e.this), "no_where": st.no_where})
    elif isinstance(e, exp.Delete):
        st.kind = "delete"
        st.tables_written = [_tname(e.this)]
        st.no_where = e.args.get("where") is None
        st.destructive = True
        st.changes.append({"op": "delete_rows", "table": _tname(e.this), "no_where": st.no_where})
    elif isinstance(e, exp.TruncateTable):
        st.kind = "delete"
        st.destructive = True
        st.no_where = True
        names = [_tname(t) for t in e.find_all(exp.Table)]
        st.tables_written = names
        for n in names:
            st.changes.append({"op": "delete_rows", "table": n, "no_where": True})
    elif isinstance(e, exp.Merge):
        st.kind = "merge"
        st.tables_written = [_tname(e.this)]
        st.destructive = True
        st.tables_read = _read_tables(e)
    elif isinstance(e, exp.Query):
        st.kind = "select"
        st.tables_read = _read_tables(e)
    elif isinstance(e, exp.Command):
        st.kind = "other"
        st.parse_error = f"Unsupported command: {str(e.this).upper()}"
    return st


def analyze_statements(sql: str, dialect: str) -> list[Statement]:
    return [classify(e, i, dialect) for i, e in enumerate(parse(sql, dialect))]


def view_dependencies(definition: str, dialect: str) -> tuple[list[str], bool]:
    """Return (tables read, complete) for a view definition."""
    try:
        e = sqlglot.parse_one(definition, read=dialect)
    except SqlglotError:
        return [], False
    complete = True
    if any(isinstance(s, exp.Star) for s in e.find_all(exp.Star)) and not e.find(exp.Count):
        complete = complete  # SELECT * is resolvable when upstream schema is known
    return _read_tables(e), complete
