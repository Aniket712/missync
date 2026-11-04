"""Table/column profiling and baseline-vs-candidate comparison, executed inside the sandbox."""
from __future__ import annotations

from typing import Any, Protocol

from ..models import SchemaSnapshot, Table
from ..security import quote_ident
from .schema_diff import type_family


class Runner(Protocol):
    def query(self, schema: str, sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]: ...


def _num(v: Any) -> Any:
    if v is None:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e15 else round(f, 6)
    except (TypeError, ValueError):
        return str(v)


def profile_table(r: Runner, schema: str, table: Table, key: list[str] | None = None) -> dict[str, Any]:
    q = quote_ident(table.name)
    exprs = ["count(*)"]
    for c in table.columns:
        qc = quote_ident(c.name)
        fam = type_family(c.type)
        exprs += [f"count({qc})", f"count(distinct {qc})"]
        if fam in ("int", "decimal", "float"):
            exprs += [f"min({qc})", f"max({qc})", f"avg({qc})", f"sum({qc})"]
        elif fam in ("date", "timestamp"):
            exprs += [f"min({qc})", f"max({qc})"]
    _, rows = r.query(schema, f"select {', '.join(exprs)} from {q}")
    vals = list(rows[0])
    total = int(vals[0])
    i = 1
    cols: dict[str, Any] = {}
    for c in table.columns:
        fam = type_family(c.type)
        nn, dist = int(vals[i]), int(vals[i + 1])
        i += 2
        info: dict[str, Any] = {
            "type": c.type, "null_count": total - nn, "null_rate": ((total - nn) / total) if total else 0.0,
            "distinct": dist,
        }
        if fam in ("int", "decimal", "float"):
            info.update(min=_num(vals[i]), max=_num(vals[i + 1]), avg=_num(vals[i + 2]), sum=_num(vals[i + 3]))
            i += 4
        elif fam in ("date", "timestamp"):
            info.update(min=str(vals[i]) if vals[i] is not None else None, max=str(vals[i + 1]) if vals[i + 1] is not None else None)
            i += 2
        cols[c.name] = info
    out: dict[str, Any] = {"name": table.name, "kind": table.kind, "row_count": total, "columns": cols}
    if key and all(table.column(k) for k in key):
        kc = ", ".join(quote_ident(k) for k in key)
        nulls_cond = " or ".join(f"{quote_ident(k)} is null" for k in key)
        _, d = r.query(
            schema,
            f"select count(*), coalesce(sum(n),0) from (select count(*) n from {q} "
            f"where not ({nulls_cond}) group by {kc} having count(*) > 1) t",
        )
        _, nk = r.query(schema, f"select count(*) from {q} where {nulls_cond}")
        out["key"] = {"columns": key, "duplicate_keys": int(d[0][0]), "rows_in_duplicate_keys": int(d[0][1] or 0),
                      "null_key_rows": int(nk[0][0])}
    return out


def profile_schema(r: Runner, schema: str, snapshot: SchemaSnapshot, keys: dict[str, list[str]] | None = None,
                   include_views: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keys = {k.lower(): v for k, v in (keys or {}).items()}
    for t in snapshot.tables:
        if t.kind == "view" and not include_views:
            continue
        try:
            out[t.name] = profile_table(r, schema, t, keys.get(t.name.lower()))
        except Exception as e:  # broken view/table: report instead of failing the analysis
            out[t.name] = {"name": t.name, "kind": t.kind, "error": str(e).splitlines()[0][:200]}
    return out


def compare_profiles(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-table comparison of row counts, null rates and key duplicates."""
    result: list[dict[str, Any]] = []
    for name, b in before.items():
        a = after.get(name)
        if a is None:
            result.append({"table": name, "status": "removed", "kind": b.get("kind")})
            continue
        if "error" in b or "error" in a:
            result.append({"table": name, "status": "error", "kind": a.get("kind"), "error": a.get("error") or b.get("error")})
            continue
        entry: dict[str, Any] = {
            "table": name, "status": "compared", "kind": a["kind"],
            "rows_before": b["row_count"], "rows_after": a["row_count"],
            "row_delta": a["row_count"] - b["row_count"],
            "row_delta_pct": ((a["row_count"] - b["row_count"]) / b["row_count"] * 100) if b["row_count"] else None,
            "columns": [],
        }
        for cname, bc in b["columns"].items():
            ac = a["columns"].get(cname)
            if ac is None:
                continue
            col = {
                "column": cname, "type_before": bc["type"], "type_after": ac["type"],
                "null_rate_before": bc["null_rate"], "null_rate_after": ac["null_rate"],
                "null_rate_delta": ac["null_rate"] - bc["null_rate"],
                "distinct_before": bc["distinct"], "distinct_after": ac["distinct"],
            }
            for stat in ("sum", "avg", "min", "max"):
                if stat in bc or stat in ac:
                    col[f"{stat}_before"], col[f"{stat}_after"] = bc.get(stat), ac.get(stat)
            entry["columns"].append(col)
        if "key" in b or "key" in a:
            entry["key"] = {"before": b.get("key"), "after": a.get("key")}
        result.append(entry)
    for name, a in after.items():
        if name not in before:
            result.append({"table": name, "status": "added", "kind": a.get("kind"), "rows_after": a.get("row_count")})
    return result
