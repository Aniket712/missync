"""Capture schema signatures + profiles and compare against earlier states."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from ..config import get_settings
from ..connectors.base import Connector
from ..models import SEVERITY_ORDER, Asset, SchemaSnapshot
from .engine import _data_findings, _Findings, _structure_findings
from .lineage import build_lineage, downstream
from .profiling import compare_profiles, profile_schema
from .sandbox import Sandbox
from .schema_diff import diff_schemas, signature


def capture(connector: Connector) -> dict[str, Any]:
    """Snapshot schema and (when the connector can copy data) profiling statistics."""
    snap = connector.discover()
    out: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "signature": signature(snap), "schema": snap.model_dump(), "profile": None, "profile_notes": [],
    }
    if connector.capabilities.sandbox_validation:
        s = get_settings()
        sb = Sandbox(connector, snap, s.sample_limit, s.statement_timeout_s)
        try:
            sb.load()
            keys = {t.name: [c.name for c in t.columns if c.primary_key] for t in snap.tables if any(c.primary_key for c in t.columns)}
            out["profile"] = profile_schema(sb, "base", sb.schema_snapshot("base"), keys)
            out["profile_notes"] = [f"Table '{t}' profiled on a sample of {sb.copied_rows[t]:,} rows." for t, tr in sb.truncated.items() if tr]
        except Exception as e:
            out["profile_notes"].append(f"Profiling unavailable: {type(e).__name__}")
        finally:
            sb.close()
    else:
        out["profile_notes"].append(f"{connector.type} does not support data profiling; schema signature only.")
    return out


def compare(old: dict[str, Any], new: dict[str, Any], assets: list[Asset] | None = None) -> dict[str, Any]:
    a, b = SchemaSnapshot(**old["schema"]), SchemaSnapshot(**new["schema"])
    diff = diff_schemas(a, b)
    g = build_lineage(a, assets)

    def dependents(ch):
        r = downstream(g, [ch])
        return bool(r["objects"] or r["assets"]), r

    def names(r):
        return sorted(r["objects"]) + [f"asset:{x.name}" for x, _ in r["assets"]]

    F = _Findings()
    _structure_findings(F, diff, dependents, names, [], True, None, a)
    comparison: list[dict[str, Any]] = []
    limits: list[str] = []
    if old.get("profile") and new.get("profile"):
        comparison = compare_profiles(old["profile"], new["profile"])
        stub = SimpleNamespace(truncated={})
        _data_findings(F, comparison, [], [], [], stub, old["profile"], dependents, names)
        limits.append("Row counts and statistics compare two profiling runs; changes may be legitimate data growth, not defects.")
    else:
        limits.append("One of the states has no data profile, so only the schema was compared.")
    limits.extend(old.get("profile_notes", []) + new.get("profile_notes", []))
    findings = sorted(F.items, key=lambda f: SEVERITY_ORDER[f.severity])
    for i, f in enumerate(findings, 1):
        f.id = f"F{i}"
    return {
        "schema_changed": old["signature"] != new["signature"], "schema_diff": diff, "table_comparison": comparison,
        "findings": [f.model_dump() for f in findings], "limitations": limits,
    }
