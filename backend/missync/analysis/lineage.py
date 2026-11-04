"""Dependency graph from accessible view definitions plus registered downstream assets."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.lineage import lineage as sg_lineage

from ..models import Asset, GraphEdge, GraphNode, ImpactGraph, SchemaSnapshot
from .sql_parser import view_dependencies


@dataclass
class LineageGraph:
    table_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # src -> {dst}
    col_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # "t.c" -> {"v.c"}
    incomplete_views: dict[str, str] = field(default_factory=dict)  # view -> reason
    kinds: dict[str, str] = field(default_factory=dict)
    assets: list[Asset] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _schema_dict(snapshot: SchemaSnapshot) -> dict[str, dict[str, str]]:
    return {t.name: {c.name: c.type or "TEXT" for c in t.columns} for t in snapshot.tables}


def build_lineage(snapshot: SchemaSnapshot, assets: list[Asset] | None = None) -> LineageGraph:
    g = LineageGraph(assets=list(assets or []))
    known = {t.name.lower(): t.name for t in snapshot.tables}
    schema = _schema_dict(snapshot)
    for t in snapshot.tables:
        g.kinds[t.name] = t.kind
    for t in snapshot.tables:
        if t.kind != "view":
            continue
        if not t.definition:
            g.incomplete_views[t.name] = "view definition is not accessible"
            continue
        deps, _ = view_dependencies(t.definition, snapshot.dialect)
        if not deps and not _parses(t.definition, snapshot.dialect):
            g.incomplete_views[t.name] = "view definition could not be parsed"
            continue
        for d in deps:
            src = known.get(d.lower())
            if src:
                g.table_edges[src].add(t.name)
            else:
                g.incomplete_views.setdefault(t.name, f"depends on '{d}' which is outside the discovered schema")
        for col in t.columns:
            try:
                node = sg_lineage(col.name, t.definition, schema=schema, dialect=snapshot.dialect)
            except (SqlglotError, KeyError, ValueError, AttributeError, TypeError) as e:
                g.incomplete_views.setdefault(t.name, f"column lineage unavailable for '{col.name}'")
                _ = e
                continue
            for leaf in node.walk():
                if leaf.downstream:
                    continue
                src_expr = leaf.expression
                tbl = src_expr.this if isinstance(src_expr, exp.Table) else None
                tname = tbl.name if tbl is not None else None
                cname = leaf.name.split(".")[-1]
                if tname and tname.lower() in known:
                    g.col_edges[f"{known[tname.lower()]}.{cname}"].add(f"{t.name}.{col.name}")
    return g


def _parses(sql: str, dialect: str) -> bool:
    try:
        sqlglot.parse_one(sql, read=dialect)
        return True
    except SqlglotError:
        return False


def _norm(s: str) -> str:
    return s.lower()


def downstream(g: LineageGraph, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute impacted objects for structural changes.

    changes: dicts with 'table' and optional 'column'. Returns dict with impacted tables/views,
    impacted columns, impacted assets and whether the answer is partial.
    """
    impacted_cols: set[str] = set()
    impacted_objs: dict[str, str] = {}  # object -> reason ("column"|"object"|"possible")
    partial = False
    queue: deque[tuple[str, str | None]] = deque()
    seen: set[tuple[str, str | None]] = set()
    for ch in changes:
        queue.append((ch["table"], ch.get("column")))
    ci_col = {k.lower(): (k, v) for k, v in g.col_edges.items()}
    ci_tbl = {k.lower(): (k, v) for k, v in g.table_edges.items()}
    while queue:
        table, column = queue.popleft()
        key = (table.lower(), column.lower() if column else None)
        if key in seen:
            continue
        seen.add(key)
        if column:
            hit = ci_col.get(f"{table}.{column}".lower())
            dsts = hit[1] if hit else set()
            for dst in dsts:
                impacted_cols.add(dst)
                vt, vc = dst.split(".", 1)
                impacted_objs.setdefault(vt, "column")
                queue.append((vt, vc))
            # Views that read the table but whose column lineage is incomplete may still be affected
            for v in (ci_tbl.get(table.lower(), (None, set()))[1]):
                if v in g.incomplete_views:
                    impacted_objs.setdefault(v, "possible")
                    partial = True
                    queue.append((v, None))
        else:
            for v in (ci_tbl.get(table.lower(), (None, set()))[1]):
                impacted_objs.setdefault(v, "object")
                queue.append((v, None))
    # Whole-object changes cascade to every column-edge from the object
    for table, column in list(seen):
        if column is None:
            for k, (_orig, dsts) in ci_col.items():
                if k.startswith(f"{table}."):
                    for dst in dsts:
                        impacted_cols.add(dst)
    if g.incomplete_views:
        partial = True
    impacted_assets: list[tuple[Asset, str]] = []
    for a in g.assets:
        reason = None
        for dep in a.depends_on:
            d = dep.lower()
            if "." in d:
                t, c = d.split(".", 1)
                if any(ch["table"].lower() == t and ch.get("column", "").lower() == c for ch in changes) or any(
                    ic.lower() == d for ic in impacted_cols
                ):
                    reason = f"depends on {dep}"
                    break
                if any(ch["table"].lower() == t and not ch.get("column") for ch in changes):
                    reason = f"depends on {dep} (object changed)"
                    break
            else:
                if any(ch["table"].lower() == d for ch in changes) or d in {o.lower() for o in impacted_objs}:
                    # Asset declared at table level: possible, column-level use unknown
                    col_level = any(ch.get("column") for ch in changes)
                    reason = f"depends on {dep}" + (" (column usage unknown)" if col_level and d not in {
                        o.lower() for o in impacted_objs if impacted_objs[o] == "column"} else "")
                    break
        if reason:
            impacted_assets.append((a, reason))
    return {
        "objects": impacted_objs, "columns": sorted(impacted_cols), "assets": impacted_assets, "partial": partial,
    }


def to_impact_graph(g: LineageGraph, changes: list[dict[str, Any]], result: dict[str, Any]) -> ImpactGraph:
    changed_tables = {c["table"].lower(): c for c in changes}
    nodes: dict[str, GraphNode] = {}

    def add(id_: str, type_: str, **kw: Any) -> None:
        if id_ not in nodes:
            nodes[id_] = GraphNode(id=id_, label=id_, type=type_, **kw)

    detail_by_table: dict[str, list[str]] = defaultdict(list)
    for ch in changes:
        if ch.get("column"):
            detail_by_table[ch["table"].lower()].append(ch["column"])
    for t in changed_tables.values():
        add(t["table"], g.kinds.get(t["table"], "table"), changed=True,
            detail=("changed: " + ", ".join(sorted(set(detail_by_table[t["table"].lower()])))) if detail_by_table.get(t["table"].lower()) else "changed")
    impacted_cols_by_obj: dict[str, list[str]] = defaultdict(list)
    for c in result["columns"]:
        o, col = c.split(".", 1)
        impacted_cols_by_obj[o].append(col)
    for obj in result["objects"]:
        add(obj, g.kinds.get(obj, "view"), impacted=True,
            detail=("affected columns: " + ", ".join(sorted(impacted_cols_by_obj[obj]))) if impacted_cols_by_obj.get(obj) else None)
    edges: list[GraphEdge] = []
    for src, dsts in g.table_edges.items():
        for dst in dsts:
            if src in nodes and dst in nodes:
                edges.append(GraphEdge(source=src, target=dst, complete=dst not in g.incomplete_views))
    for a, reason in result["assets"]:
        aid = f"asset:{a.name}"
        add(aid, "asset", impacted=True, detail=reason)
        nodes[aid].label = a.name
        for dep in a.depends_on:
            dep_obj = dep.split(".")[0]
            for cand in nodes:
                if cand.lower() == dep_obj.lower():
                    edges.append(GraphEdge(source=cand, target=aid, complete=True))
    notes = [f"Lineage for view '{v}' is incomplete: {r}" for v, r in g.incomplete_views.items()]
    if not g.assets:
        notes.append("No downstream assets (dashboards, models) are registered; only database objects are traced.")
    return ImpactGraph(nodes=list(nodes.values()), edges=edges, complete=not result["partial"], notes=notes)
