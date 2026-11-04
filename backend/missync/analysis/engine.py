"""Analysis orchestrator: static analysis -> sandbox validation -> comparison -> findings."""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..config import get_settings
from ..connectors.base import Connector
from ..models import (
    SEVERITY_ORDER,
    AnalysisRequest,
    AnalysisResult,
    Asset,
    Confidence,
    Finding,
    ImpactGraph,
    Kind,
    Severity,
)
from . import severity as sev
from .lineage import build_lineage, downstream, to_impact_graph
from .profiling import compare_profiles, profile_schema
from .reconcile import reconcile_table
from .sandbox import Sandbox
from .schema_diff import diff_schemas
from .sql_parser import Statement, analyze_statements, assert_single_select


class _Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, category: str, title: str, severity: Severity, kind: Kind, confidence: Confidence, summary: str,
            reason: str = "", evidence: dict[str, Any] | None = None, affected: list[str] | None = None,
            recommendation: str = "", possibly_intended: bool = False, limitations: list[str] | None = None) -> None:
        self.items.append(Finding(
            id=f"F{len(self.items) + 1}", category=category, title=title, severity=severity, kind=kind,
            confidence=confidence, confidence_reason=reason, summary=summary, evidence=evidence or {},
            affected=affected or [], recommendation=recommendation, possibly_intended=possibly_intended,
            limitations=limitations or [],
        ))


def _changes_from_diff(diff: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in diff:
        c = d["change"]
        if c in ("column_removed", "type_changed", "nullability_changed"):
            out.append({"table": d["table"], "column": d["column"]})
        elif c in ("table_removed", "view_definition_changed", "kind_changed"):
            out.append({"table": d["table"]})
    return out


def _changes_from_statements(stmts: list[Statement]) -> list[dict[str, Any]]:
    out = []
    for s in stmts:
        for ch in s.changes:
            if ch["op"] in ("drop_column", "alter_type", "rename_column", "drop_not_null", "set_not_null", "alter_column"):
                out.append({"table": ch["table"], "column": ch["column"]})
            elif ch["op"] in ("drop_object", "rename_table", "replace_object"):
                out.append({"table": ch["table"]})
    return out


def _pct(a: float, b: float) -> float | None:
    return None if not b else (a - b) / abs(b) * 100


def run_analysis(connector: Connector, req: AnalysisRequest, assets: list[Asset] | None = None,
                 progress: Callable[[str, int], None] | None = None) -> AnalysisResult:
    """Run one analysis. `progress(stage, percent)` is optional; it may raise to cancel the run between stages."""
    settings = get_settings()
    dialect = connector.dialect
    limits: list[str] = []

    def step(stage: str, pct: int) -> None:
        if progress:
            progress(stage, pct)

    step("Parsing the change", 5)
    sql_dialect = req.sql_dialect or dialect
    stmts = analyze_statements(req.sql, sql_dialect)
    step("Reading the schema", 12)
    snapshot = connector.discover()
    g = build_lineage(snapshot, assets)
    F = _Findings()
    result = AnalysisResult(
        id=uuid.uuid4().hex[:12], title=req.title or "Untitled analysis", connection_id=req.connection_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"), sql=req.sql, dialect=sql_dialect,
        statements=[s.to_dict() for s in stmts],
    )
    for v, why in g.incomplete_views.items():
        limits.append(f"Lineage for view '{v}' is incomplete: {why}.")
    if not assets:
        limits.append("No downstream assets are registered, so impact is limited to database objects.")

    def dependents(change: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        r = downstream(g, [change])
        return bool(r["objects"] or r["assets"]), r

    def names(r: dict[str, Any]) -> list[str]:
        return sorted(r["objects"]) + [f"asset:{a.name}" for a, _ in r["assets"]]

    sandbox: Sandbox | None = None
    diff: list[dict[str, Any]] = []
    if connector.capabilities.sandbox_validation:
        step("Copying a sample into the sandbox", 25)
        sample = min(req.sample_limit or settings.sample_limit, settings.sample_limit)
        sandbox = Sandbox(connector, snapshot, sample, settings.statement_timeout_s)
        try:
            sandbox.load()
        except Exception as e:
            sandbox = None
            limits.append(f"Sandbox could not be created ({type(e).__name__}); results are predicted only.")
    else:
        limits.append(f"{connector.type} does not support sandbox validation; results are predicted from static analysis only.")

    validated = False
    try:
        if sandbox is not None:
            for t, trunc in sandbox.truncated.items():
                if trunc:
                    limits.append(f"Table '{t}' was sampled to the first {sandbox.copied_rows[t]:,} rows; measured values reflect the sample.")
            for t in sandbox.skipped_tables:
                limits.append(f"Table '{t}' could not be copied into the sandbox and is excluded from validation.")
            for v, e in sandbox.view_errors.items():
                if v not in sandbox.skipped_tables:
                    limits.append(f"View '{v}' could not be recreated in the sandbox: {e}")

            step("Profiling the current data", 45)
            before_snap = sandbox.schema_snapshot("base")
            keys = {k: v for k, v in req.keys.items()}
            for t in snapshot.tables:  # default to primary keys when no key was declared
                pk = [c.name for c in t.columns if c.primary_key]
                if pk and t.name.lower() not in {k.lower() for k in keys}:
                    keys[t.name] = pk
            base_prof = profile_schema(sandbox, "base", before_snap, keys)

            step("Applying the change to the copy", 60)
            outcomes = sandbox.apply(stmts)
            result.validation = {
                "mode": "sandbox", "engine": "DuckDB (in-memory, no file/network access)",
                "outcomes": [o.__dict__ for o in outcomes],
                "tables_copied": {t: {"rows": sandbox.copied_rows[t], "sampled": sandbox.truncated[t]} for t in sandbox.loaded_tables},
            }
            failed = [o for o in outcomes if o.status == "failed"]
            for o in outcomes:
                if o.status == "skipped" and "earlier statement failed" not in o.message:
                    limits.append(f"Statement {o.index + 1} was not executed: {o.message}")
            for o in failed:
                st = stmts[o.index]
                F.add("execution", f"Statement {o.index + 1} fails when applied", "high", "verified", "high",
                      f"The {st.kind.replace('_', ' ')} statement failed in the sandbox: {o.message}",
                      "Executed on a copy of the current data and raised an error.",
                      {"statement": st.sql, "error": o.message}, st.tables_written,
                      "Fix the statement or the data it conflicts with before deploying; the same failure is likely in production.",
                      limitations=["Sandbox runs DuckDB; a few dialect-specific behaviours can differ from your database."])
            validated = not failed
            step("Comparing before and after", 72)
            after_snap = sandbox.schema_snapshot("cand")
            diff = diff_schemas(before_snap, after_snap)
            after_prof = profile_schema(sandbox, "cand", after_snap, keys)
            comparison = compare_profiles(base_prof, after_prof)
            for c in comparison:
                if c.get("status") == "error":
                    limits.append(f"'{c['table']}' could not be profiled after the change: {c['error']}")

            step("Reconciling records", 84)
            recon = []
            for tname, key in keys.items():
                if before_snap.table(tname) and before_snap.table(tname).kind == "table":
                    recon.append(reconcile_table(sandbox, before_snap, after_snap, tname, key, base_prof.get(tname)))
            result.reconciliation = recon

            mc = []
            for m in req.metrics:
                try:
                    assert_single_select(m.sql, sql_dialect)
                    import sqlglot
                    duck = sqlglot.parse_one(m.sql, read=sql_dialect).sql("duckdb")
                    b = sandbox.scalar("base", duck)
                    try:
                        a = sandbox.scalar("cand", duck)
                    except Exception as e:  # metric broke after the change
                        mc.append({"name": m.name, "sql": m.sql, "before": _f(b), "after": None, "error": str(e).splitlines()[0][:200], "tolerance_pct": m.tolerance_pct})
                        continue
                    bf, af = _f(b), _f(a)
                    mc.append({"name": m.name, "sql": m.sql, "before": bf, "after": af,
                               "delta": None if bf is None or af is None else af - bf,
                               "delta_pct": None if bf is None or af is None else _pct(af, bf),
                               "tolerance_pct": m.tolerance_pct})
                except Exception as e:
                    mc.append({"name": m.name, "sql": m.sql, "error": f"metric rejected or failed: {str(e).splitlines()[0][:200]}",
                               "tolerance_pct": m.tolerance_pct})
            result.metric_comparison = mc
            result.table_comparison = comparison
            result.schema_diff = diff

            # views that stopped binding
            for t in before_snap.tables:
                if t.kind == "view" and sandbox.view_valid("base", t.name) is None:
                    err = sandbox.view_valid("cand", t.name)
                    if err and after_snap.table(t.name):
                        dep, r = dependents({"table": t.name})
                        F.add("broken_view", f"View '{t.name}' no longer works", sev.escalate("high", dep), "verified", "high",
                              f"After the change, selecting from view '{t.name}' fails: {err}",
                              "The view bound successfully on the baseline copy and fails on the candidate copy.",
                              {"error": err}, [t.name] + names(r),
                              "Update the view definition in the same change, or keep the removed/renamed column available.")

            _structure_findings(F, diff, dependents, names, stmts, validated, sandbox, before_snap)
            _data_findings(F, comparison, result.reconciliation, mc, stmts, sandbox, base_prof, dependents, names)
        else:
            _predicted_findings(F, stmts, snapshot, dependents, names)
    finally:
        if sandbox is not None:
            sandbox.close()

    step("Tracing downstream impact", 94)
    # impact graph (based on the baseline lineage)
    changes = _changes_from_diff(diff) if sandbox is not None and validated else _changes_from_statements(stmts)
    if sandbox is not None:
        for c in result.table_comparison:
            if c.get("status") == "compared" and c.get("row_delta"):
                changes.append({"table": c["table"]})
        for f in F.items:
            if f.category in ("null_rate", "value_change", "duplicate_keys") and f.evidence.get("column"):
                changes.append({"table": f.evidence["table"], "column": f.evidence["column"]})
    seen, uniq = set(), []
    for c in changes:
        k = (c["table"].lower(), (c.get("column") or "").lower())
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    impact = downstream(g, uniq)
    result.graph = to_impact_graph(g, uniq, impact) if uniq else ImpactGraph(
        complete=not bool(g.incomplete_views), notes=["No structural or data changes were detected to trace."])

    if not validated and sandbox is not None:
        limits.append("Because a statement failed, the candidate state is partial; data comparisons reflect only the statements that ran.")

    result.findings = sorted(F.items, key=lambda f: (SEVERITY_ORDER[f.severity], 0 if f.kind == "verified" else 1))
    for i, f in enumerate(result.findings, 1):
        f.id = f"F{i}"
    counts = Counter(f.severity for f in result.findings)
    result.limitations = limits
    result.summary = {
        "highest_severity": sev.worst([f.severity for f in result.findings]),
        "by_severity": {k: counts.get(k, 0) for k in ("critical", "high", "medium", "low", "info")},
        "verified": sum(1 for f in result.findings if f.kind == "verified"),
        "predicted": sum(1 for f in result.findings if f.kind == "predicted"),
        "validated_in_sandbox": sandbox is not None and validated,
        "lineage_complete": result.graph.complete,
        "impacted_objects": [n.label for n in result.graph.nodes if n.impacted],
        "recommended_actions": list(dict.fromkeys(f.recommendation for f in result.findings if f.recommendation and f.severity in ("critical", "high", "medium")))[:6],
        "verdict": _verdict(result.findings, sandbox is not None and validated),
    }
    return result


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _verdict(findings: list[Finding], validated: bool) -> str:
    worst = sev.worst([f.severity for f in findings])
    scope = "verified in an isolated copy of the data" if validated else "predicted from static analysis only"
    if worst in ("critical", "high"):
        return f"Potentially breaking changes found ({scope}). Review before deploying."
    if worst == "medium":
        return f"Changes that need review were found ({scope})."
    if findings:
        return f"Only low-impact differences were found ({scope}). This is not a guarantee of safety."
    return f"No differences were detected ({scope}). This is not a guarantee of safety: unobserved data, dependencies or workloads may still be affected."


def _structure_findings(F, diff, dependents, names, stmts, validated, sandbox, before_snap):
    for d in diff:
        c, t = d["change"], d["table"]
        if c == "column_removed":
            dep, r = dependents({"table": t, "column": d["column"]})
            F.add("schema", f"Column {t}.{d['column']} removed", sev.escalate(sev.severity_for_removal(), dep), "verified", "high",
                  f"Column '{d['column']}' ({d['type']}) no longer exists on '{t}' after the change.",
                  "Observed by comparing schemas of the baseline and candidate copies.",
                  d, [f"{t}.{d['column']}"] + names(r),
                  "Keep the column (or a compatible alias) until all consumers are migrated, or update dependents in the same release.",
                  limitations=([] if not dep else []) + ([] if not r["partial"] else ["Lineage is incomplete, so additional dependents may exist."]))
        elif c == "table_removed":
            dep, r = dependents({"table": t})
            F.add("schema", f"{d['kind'].capitalize()} {t} removed", sev.escalate("high", dep), "verified", "high",
                  f"'{t}' does not exist after the change.", "Observed by comparing schemas.", d, [t] + names(r),
                  "Deprecate first: keep a compatibility view and migrate consumers before dropping.")
        elif c == "type_changed":
            sevr = sev.severity_for_type_change(d["compatibility"])
            dep, r = dependents({"table": t, "column": d["column"]})
            F.add("schema", f"Type of {t}.{d['column']} changed {d['old']} → {d['new']}", sev.escalate(sevr, dep), "verified", "high",
                  f"The {d['compatibility']} type change on '{t}.{d['column']}' may alter values, precision or how consumers parse the column.",
                  "Observed by comparing schemas; value effects are measured separately.", d,
                  [f"{t}.{d['column']}"] + names(r),
                  "Confirm consumers handle the new type; compare values on the changed rows before rollout." if sevr != "low"
                  else "Widening is usually safe, but verify consumers that parse or cast this column.",
                  possibly_intended=True)
        elif c == "nullability_changed":
            F.add("schema", f"Nullability of {t}.{d['column']} changed", "medium" if d["new"] == "NOT NULL" else "low", "verified", "high",
                  f"{d['old']} → {d['new']}.", "Observed by comparing schemas.", d, [f"{t}.{d['column']}"],
                  "Make sure writers never produce NULL for this column." if d["new"] == "NOT NULL" else "Consumers may now receive NULLs where they did not before.",
                  possibly_intended=True)
        elif c == "view_definition_changed":
            dep, r = dependents({"table": t})
            F.add("schema", f"View {t} definition changed", sev.escalate("low", dep), "verified", "high",
                  f"The SQL of view '{t}' changed; row-level effects are shown in the data comparison.",
                  "Observed by comparing view definitions.", {k: d[k] for k in ("table", "old", "new")}, [t] + names(r),
                  "Review the metric and row comparisons below.", possibly_intended=True)
        elif c == "column_added":
            F.add("schema", f"Column {t}.{d['column']} added", "info", "verified", "high",
                  "Additive change; existing consumers that select named columns are not affected.", "Observed by comparing schemas.",
                  d, [f"{t}.{d['column']}"], "", possibly_intended=True,
                  limitations=["Consumers using SELECT * or positional inserts may still be affected."])
        elif c == "table_added":
            F.add("schema", f"{d['kind'].capitalize()} {t} added", "info", "verified", "high", "New object; no existing dependents.",
                  "Observed by comparing schemas.", d, [t], "", possibly_intended=True)

    # no-WHERE statements: verified row counts come from the data comparison; flag the risk statically
    for s in stmts:
        if s.no_where and s.kind in ("delete", "update"):
            F.add("unfiltered_statement", f"{s.kind.upper()} on {', '.join(s.tables_written)} has no WHERE clause", "high",
                  "verified" if validated else "predicted", "high" if validated else "medium",
                  "The statement touches every row of the table.", "Determined from the parsed statement.",
                  {"statement": s.sql}, s.tables_written,
                  "Add a WHERE clause or confirm that a full-table change is intended.")


def _data_findings(F, comparison, recon, metrics, stmts, sandbox, base_prof, dependents, names):
    written = {t.lower(): s for s in stmts for t in s.tables_written}

    def intended(table: str, kinds: tuple[str, ...]) -> bool:
        s = written.get(table.lower())
        return bool(s and s.kind in kinds and not s.no_where)

    for c in comparison:
        if c.get("status") != "compared":
            continue
        t = c["table"]
        sampled = sandbox.truncated.get(t, False)
        conf: Confidence = "medium" if sampled else "high"
        why = "Measured on a sample of the table." if sampled else "Measured on a full copy of the table."
        if c["kind"] == "view":
            conf, why = "medium", "Measured through a view recreated in the sandbox from its accessible definition."
        if c["row_delta"] < 0:
            lost = -c["row_delta"]
            sevr = sev.severity_for_row_loss(c["rows_before"], c["rows_after"])
            dep, r = dependents({"table": t})
            F.add("row_count", f"{t}: {lost:,} rows lost ({abs(c['row_delta_pct']):.1f}%)", sev.escalate(sevr, dep), "verified", conf,
                  f"Row count went from {c['rows_before']:,} to {c['rows_after']:,}.", why,
                  {"table": t, "rows_before": c["rows_before"], "rows_after": c["rows_after"], "row_delta_pct": c["row_delta_pct"]},
                  [t] + names(r), "Confirm the removed rows are intended (compare the missing-key list below); otherwise adjust the filter or join that drops them.",
                  possibly_intended=intended(t, ("delete", "merge")))
        elif c["row_delta"] > 0:
            F.add("row_count", f"{t}: {c['row_delta']:,} rows added", "low" if c["kind"] == "table" else "medium", "verified", conf,
                  f"Row count went from {c['rows_before']:,} to {c['rows_after']:,}.", why,
                  {"table": t, "rows_before": c["rows_before"], "rows_after": c["rows_after"]}, [t],
                  "If unexpected, look for join fan-out or duplicated inserts.", possibly_intended=intended(t, ("insert", "merge")))
        for col in c["columns"]:
            d = col["null_rate_delta"]
            s = sev.severity_for_null_increase(d)
            if d > 0 and s != "info":
                F.add("null_rate", f"{t}.{col['column']}: NULL rate rose {col['null_rate_before']*100:.1f}% → {col['null_rate_after']*100:.1f}%",
                      s, "verified", conf, "More values are NULL than before the change.", why,
                      {"table": t, "column": col["column"], "null_rate_before": col["null_rate_before"], "null_rate_after": col["null_rate_after"]},
                      [f"{t}.{col['column']}"], "Check joins/casts feeding this column; NULLs usually indicate unmatched joins or failed conversions.",
                      possibly_intended=intended(t, ("update",)))
        k = c.get("key")
        if k and k["before"] and k["after"] and k["after"]["duplicate_keys"] > k["before"]["duplicate_keys"]:
            n = k["after"]["duplicate_keys"] - k["before"]["duplicate_keys"]
            F.add("duplicate_keys", f"{t}: {n:,} new duplicate keys on ({', '.join(k['after']['columns'])})", "high", "verified", conf,
                  "Rows that were unique by this key now repeat, which typically double-counts downstream aggregates.", why,
                  {"table": t, "column": k["after"]["columns"][0], "duplicate_keys_before": k["before"]["duplicate_keys"],
                   "duplicate_keys_after": k["after"]["duplicate_keys"], "rows_in_duplicate_keys": k["after"]["rows_in_duplicate_keys"]},
                  [t], "Deduplicate or fix the join that multiplies rows; restore key uniqueness before release.")

    for r in recon:
        if r.get("status") != "compared":
            continue
        t = r["table"]
        row = next((c for c in comparison if c["table"] == t and c.get("status") == "compared"), None)
        rows_before = row["rows_before"] if row else 0
        if r["missing_in_candidate"]:
            sevr = sev.severity_for_missing_records(r["missing_in_candidate"], rows_before)
            F.add("missing_records", f"{t}: {r['missing_in_candidate']:,} records missing by key ({', '.join(r['key'])})", sevr, "verified",
                  "medium" if sandbox.truncated.get(t) else "high",
                  "Keys present before the change are absent afterwards.", "Record-level comparison on a key that is unique in the baseline.",
                  {"table": t, **{k: r[k] for k in ("missing_in_candidate", "matched", "missing_examples") if k in r}}, [t],
                  "Review the example keys; if not intentional, relax the filter/join that excludes them.",
                  possibly_intended=intended(t, ("delete", "merge")))
        for col, n in r["changed_by_column"].items():
            pct = n / r["matched"] * 100 if r["matched"] else 0
            F.add("value_change", f"{t}.{col}: values changed in {n:,} matched rows ({pct:.1f}%)", "high" if pct >= 10 else "medium", "verified",
                  "medium" if sandbox.truncated.get(t) else "high", "Same key, different value after the change.",
                  "Compared row by row (values cast to text) on a key that is unique in the baseline.",
                  {"table": t, "column": col, "changed_rows": n, "matched": r["matched"],
                   **({"examples": r["changed_examples"]} if r.get("changed_examples", {}).get("column") == col else {})},
                  [f"{t}.{col}"], "Confirm the new values are intended; type conversions can round or truncate silently.",
                  possibly_intended=intended(t, ("update", "merge")))

    for m in metrics:
        if m.get("error"):
            F.add("metric", f"Metric '{m['name']}' could not be computed after the change", "high", "verified", "high",
                  m["error"], "The metric query succeeded on the baseline copy only.", {"metric": m["name"]}, [],
                  "Update the metric definition or restore the objects it depends on.")
            continue
        s = sev.severity_for_metric_drift(m.get("delta_pct"), m["tolerance_pct"])
        if s == "info":
            continue
        pct = m.get("delta_pct")
        F.add("metric", f"Metric '{m['name']}' drifted {pct:+.2f}%" if pct is not None else f"Metric '{m['name']}' changed from zero/NULL",
              s, "verified", "high", f"{m['before']:,.2f} → {m['after']:,.2f} (tolerance ±{m['tolerance_pct']}%)." if m.get("before") is not None and m.get("after") is not None
              else "Metric is NULL before or after.", "Computed on the baseline and candidate copies with the same query.",
              {"metric": m["name"], "before": m.get("before"), "after": m.get("after"), "delta_pct": pct, "tolerance_pct": m["tolerance_pct"]}, [],
              "Decide whether the drift is an intended definition change; if so, communicate it to metric owners and update expectations.",
              possibly_intended=True)


def _predicted_findings(F, stmts, snapshot, dependents, names):
    for s in stmts:
        for ch in s.changes:
            op, t = ch["op"], ch["table"]
            tbl = snapshot.table(t)
            if tbl is None and op not in ("replace_object",):
                continue
            if op in ("drop_column", "rename_column"):
                dep, r = dependents({"table": t, "column": ch["column"]})
                F.add("schema", f"Column {t}.{ch['column']} {'dropped' if op == 'drop_column' else 'renamed'}",
                      sev.escalate("high", dep), "predicted", "low" if r["partial"] else "medium",
                      "Static analysis of the statement indicates consumers of this column will break.",
                      "Predicted from the SQL text and accessible lineage; not run against data.", ch, [f"{t}.{ch['column']}"] + names(r),
                      "Keep the column until dependents migrate.", limitations=["Not verified against data."])
            elif op in ("drop_object", "rename_table"):
                dep, r = dependents({"table": t})
                F.add("schema", f"{t} {'dropped' if op == 'drop_object' else 'renamed'}", sev.escalate("high", dep), "predicted",
                      "low" if r["partial"] else "medium", "Objects that reference it will fail.", "Predicted from SQL text and accessible lineage.",
                      ch, [t] + names(r), "Deprecate first with a compatibility view.", limitations=["Not verified against data."])
            elif op == "alter_type":
                col = tbl.column(ch["column"]) if tbl else None
                from .schema_diff import classify_type_change
                comp = classify_type_change(col.type, ch["new_type"]) if col else "incompatible"
                dep, r = dependents({"table": t, "column": ch["column"]})
                F.add("schema", f"Type of {t}.{ch['column']} → {ch['new_type']}", sev.escalate(sev.severity_for_type_change(comp), dep),
                      "predicted", "medium", f"Classified as {comp} from declared types.", "Predicted from declared types; values not inspected.",
                      {**ch, "old_type": col.type if col else None, "compatibility": comp}, [f"{t}.{ch['column']}"] + names(r),
                      "Run the change against a staging copy to measure value effects.", limitations=["Not verified against data."])
            elif op in ("delete_rows", "update_rows"):
                F.add("unfiltered_statement" if ch["no_where"] else "row_change",
                      f"{'DELETE' if op == 'delete_rows' else 'UPDATE'} on {t}{' without WHERE' if ch['no_where'] else ''}",
                      "high" if ch["no_where"] else "medium", "predicted", "medium", "Rows will be modified; the number affected is unknown without execution.",
                      "Predicted from SQL text.", ch, [t], "Validate in staging and compare row counts before production.", limitations=["Not verified against data."])
