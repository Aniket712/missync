"""Schema signatures and differences between two snapshots."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..models import SchemaSnapshot, Table

_FAMILIES: list[tuple[str, str]] = [
    (r"^(BOOL|BOOLEAN)", "bool"),
    (r"^(TINYINT|SMALLINT|INT2|INT4|INT8|INTEGER|INT|BIGINT|HUGEINT|UBIGINT|SERIAL|BIGSERIAL|INT64)", "int"),
    (r"^(DECIMAL|NUMERIC|NUMBER|BIGNUMERIC)", "decimal"),
    (r"^(REAL|FLOAT|DOUBLE|FLOAT4|FLOAT8|FLOAT64)", "float"),
    (r"^(TIMESTAMP|DATETIME|TIMESTAMPTZ)", "timestamp"),
    (r"^DATE$", "date"),
    (r"^TIME", "time"),
    (r"^(VARCHAR|CHAR|CHARACTER|TEXT|STRING|CLOB|NVARCHAR|NCHAR|UUID)", "text"),
    (r"^(BLOB|BYTEA|BYTES|BINARY|VARBINARY)", "binary"),
    (r"^(JSON|JSONB|VARIANT|STRUCT|ARRAY|MAP|LIST)", "json"),
]

# (old family, new family) -> risk of implicit loss when values are converted
_LOSSY = {
    ("float", "int"), ("decimal", "int"), ("float", "decimal"), ("timestamp", "date"),
    ("text", "int"), ("text", "float"), ("text", "decimal"), ("text", "bool"), ("text", "date"),
    ("text", "timestamp"), ("json", "text"), ("float", "bool"), ("int", "bool"), ("decimal", "bool"),
}
_WIDENING = {("int", "decimal"), ("int", "float"), ("int", "text"), ("date", "timestamp"),
             ("decimal", "float"), ("decimal", "text"), ("float", "text"), ("bool", "int"), ("bool", "text"),
             ("date", "text"), ("timestamp", "text")}


def type_family(t: str) -> str:
    base = (t or "").strip().upper()
    for pat, fam in _FAMILIES:
        if re.match(pat, base):
            return fam
    return "other"


def _precision(t: str) -> tuple[int, ...]:
    m = re.search(r"\(([\d,\s]+)\)", t or "")
    return tuple(int(x) for x in m.group(1).split(",")) if m else ()


def classify_type_change(old: str, new: str) -> str:
    """Return one of: same, widening, narrowing, incompatible."""
    if (old or "").upper() == (new or "").upper():
        return "same"
    fo, fn = type_family(old), type_family(new)
    if fo == fn:
        po, pn = _precision(old), _precision(new)
        if po and pn:
            if all(b >= a for a, b in zip(po, pn, strict=False)):
                return "widening"
            return "narrowing"
        if fo == "int":  # compare integer widths
            order = ["TINYINT", "SMALLINT", "INT2", "INTEGER", "INT", "INT4", "BIGINT", "INT8", "HUGEINT"]
            o = next((i for i, n in enumerate(order) if (old or "").upper().startswith(n)), None)
            n_ = next((i for i, n in enumerate(order) if (new or "").upper().startswith(n)), None)
            if o is not None and n_ is not None and n_ < o:
                return "narrowing"
        return "widening" if fo != "other" else "incompatible"
    if (fo, fn) in _LOSSY:
        return "narrowing"
    if (fo, fn) in _WIDENING:
        return "widening"
    return "incompatible"


def signature(snapshot: SchemaSnapshot) -> str:
    """Stable hash of the structural schema (names, types, nullability)."""
    payload = [
        [t.name.lower(), t.kind, [[c.name.lower(), c.type.upper(), c.nullable] for c in t.columns],
         (t.definition or "").strip() if t.kind == "view" else ""]
        for t in sorted(snapshot.tables, key=lambda t: t.name.lower())
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _view_def_norm(t: Table, dialect: str) -> str:
    try:
        import sqlglot

        return sqlglot.parse_one(t.definition, read=dialect).sql(dialect=dialect, normalize=True) if t.definition else ""
    except Exception:
        return (t.definition or "").strip()


def diff_schemas(before: SchemaSnapshot, after: SchemaSnapshot) -> list[dict[str, Any]]:
    """Return a list of change dicts with `change` in:
    table_added, table_removed, column_added, column_removed, type_changed, nullability_changed,
    view_definition_changed, kind_changed."""
    out: list[dict[str, Any]] = []
    b = {t.name.lower(): t for t in before.tables}
    a = {t.name.lower(): t for t in after.tables}
    for key, t in b.items():
        if key not in a:
            out.append({"change": "table_removed", "table": t.name, "kind": t.kind,
                        "columns": [c.name for c in t.columns]})
    for key, t in a.items():
        if key not in b:
            out.append({"change": "table_added", "table": t.name, "kind": t.kind,
                        "columns": [c.name for c in t.columns]})
    for key in b.keys() & a.keys():
        tb, ta = b[key], a[key]
        if tb.kind != ta.kind:
            out.append({"change": "kind_changed", "table": tb.name, "old": tb.kind, "new": ta.kind})
        cb = {c.name.lower(): c for c in tb.columns}
        ca = {c.name.lower(): c for c in ta.columns}
        for ck, c in cb.items():
            if ck not in ca:
                out.append({"change": "column_removed", "table": tb.name, "column": c.name, "type": c.type})
        for ck, c in ca.items():
            if ck not in cb:
                out.append({"change": "column_added", "table": tb.name, "column": c.name, "type": c.type,
                            "nullable": c.nullable})
        for ck in cb.keys() & ca.keys():
            o, n = cb[ck], ca[ck]
            if o.type.upper() != n.type.upper():
                out.append({"change": "type_changed", "table": tb.name, "column": o.name, "old": o.type,
                            "new": n.type, "compatibility": classify_type_change(o.type, n.type)})
            if o.nullable != n.nullable:
                out.append({"change": "nullability_changed", "table": tb.name, "column": o.name,
                            "old": "NULL" if o.nullable else "NOT NULL", "new": "NULL" if n.nullable else "NOT NULL"})
        if tb.kind == "view" and ta.kind == "view":
            if _view_def_norm(tb, before.dialect) != _view_def_norm(ta, after.dialect):
                out.append({"change": "view_definition_changed", "table": tb.name,
                            "old": tb.definition, "new": ta.definition})
    return sorted(out, key=lambda c: (c["table"].lower(), c["change"], c.get("column", "")))
