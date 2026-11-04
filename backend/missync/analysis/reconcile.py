"""Record-level reconciliation between baseline and candidate tables using a reliable key."""
from __future__ import annotations

from typing import Any

from ..models import SchemaSnapshot
from ..security import quote_ident
from .profiling import Runner


def reconcile_table(r: Runner, before: SchemaSnapshot, after: SchemaSnapshot, table: str, key: list[str],
                    base_profile: dict[str, Any] | None = None, examples: int = 5) -> dict[str, Any]:
    tb, ta = before.table(table), after.table(table)
    res: dict[str, Any] = {"table": table, "key": key}
    if tb is None or ta is None:
        return {**res, "status": "unavailable", "reason": "table missing from baseline or candidate"}
    if not all(tb.column(k) and ta.column(k) for k in key):
        return {**res, "status": "unavailable", "reason": "key column missing in baseline or candidate"}
    kinfo = (base_profile or {}).get("key")
    if kinfo and kinfo["duplicate_keys"] > 0:
        return {**res, "status": "unavailable",
                "reason": f"key is not unique in the baseline ({kinfo['duplicate_keys']} duplicated keys); "
                          "record-level comparison would be unreliable"}
    q = quote_ident(table)
    kcols = [quote_ident(k) for k in key]
    join = " and ".join(f"b.{k} = c.{k}" for k in kcols)
    not_null_b = " and ".join(f"b.{k} is not null" for k in kcols)
    not_null_c = " and ".join(f"c.{k} is not null" for k in kcols)
    sel_keys_b = ", ".join(f"b.{k}" for k in kcols)

    def one(sql: str) -> int:
        _, rows = r.query("base", sql)
        return int(rows[0][0])

    # Both schemas are addressable explicitly from the same connection.
    bq, cq = f"base.{q}", f"cand.{q}"
    missing = one(f"select count(*) from {bq} b where {not_null_b} and not exists (select 1 from {cq} c where {join})")
    added = one(f"select count(*) from {cq} c where {not_null_c} and not exists (select 1 from {bq} b where {join})")
    common = [c.name for c in tb.columns if ta.column(c.name) and c.name not in key]
    changed_by_col: dict[str, int] = {}
    changed_rows = 0
    if common:
        diffs = {c: f"cast(b.{quote_ident(c)} as varchar) is distinct from cast(c.{quote_ident(c)} as varchar)" for c in common}
        parts = ", ".join(f"sum(case when {d} then 1 else 0 end)" for d in diffs.values())
        any_diff = " or ".join(diffs.values())
        _, rows = r.query("base", f"select count(*), {parts} from {bq} b join {cq} c on {join} where {any_diff}")
        changed_rows = int(rows[0][0])
        for c, n in zip(common, rows[0][1:], strict=False):
            if n:
                changed_by_col[c] = int(n)
    matched = one(f"select count(*) from {bq} b join {cq} c on {join}")
    res.update(status="compared", matched=matched, missing_in_candidate=missing, new_in_candidate=added,
               changed_rows=changed_rows, changed_by_column=changed_by_col, columns_compared=common)
    if missing:
        _, ex = r.query("base", f"select {sel_keys_b} from {bq} b where {not_null_b} and not exists "
                                    f"(select 1 from {cq} c where {join}) order by 1 limit {examples}")
        res["missing_examples"] = [[str(v) for v in row] for row in ex]
    if changed_by_col:
        first = next(iter(changed_by_col))
        qc = quote_ident(first)
        _, ex = r.query("base", f"select {sel_keys_b}, cast(b.{qc} as varchar), cast(c.{qc} as varchar) "
                                    f"from {bq} b join {cq} c on {join} where cast(b.{qc} as varchar) is distinct from "
                                    f"cast(c.{qc} as varchar) order by 1 limit {examples}")
        res["changed_examples"] = {"column": first, "rows": [[str(v) for v in row] for row in ex]}
    return res
