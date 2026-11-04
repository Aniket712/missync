"""Rule-based severity assignment. No numeric scores: each rule is explicit and documented.

Rules (base severity, then escalated one level if a dependent view/asset is affected):
  removed table/column, renamed column/table ...... high
  type change: narrowing / incompatible ........... high ; widening ........ low
  NOT NULL added .................................. medium
  statement without WHERE (UPDATE/DELETE) ......... high
  rows lost (verified):   >= 10% of rows .......... high ; > 0 ............. medium
  records missing by key: >= 5% of rows ........... high ; > 0 ............. medium
  null-rate increase (percentage points): >= 20 ... high ; >= 5 ........... medium ; > 0.1 ... low
  new duplicate keys ............................... high
  metric drift vs tolerance: >= 10x tolerance or >= 10% .. high ; > tolerance .. medium
  view no longer valid ............................ high
Escalation: +1 level (capped at critical) when a registered asset or dependent view is impacted.
"""
from __future__ import annotations

from ..models import SEVERITY_ORDER, Severity

_LEVELS: list[Severity] = ["info", "low", "medium", "high", "critical"]


def escalate(sev: Severity, has_dependents: bool) -> Severity:
    if not has_dependents or sev == "info":
        return sev
    return _LEVELS[min(_LEVELS.index(sev) + 1, len(_LEVELS) - 1)]


def severity_for_removal() -> Severity:
    return "high"


def severity_for_type_change(compatibility: str) -> Severity:
    return "low" if compatibility == "widening" else "high"


def severity_for_row_loss(rows_before: int, rows_after: int) -> Severity:
    lost = rows_before - rows_after
    if lost <= 0 or rows_before <= 0:
        return "info"
    return "high" if lost / rows_before >= 0.10 else "medium"


def severity_for_missing_records(missing: int, rows_before: int) -> Severity:
    if missing <= 0 or rows_before <= 0:
        return "info"
    return "high" if missing / rows_before >= 0.05 else "medium"


def severity_for_null_increase(delta: float) -> Severity:
    pp = delta * 100
    if pp >= 20:
        return "high"
    if pp >= 5:
        return "medium"
    if pp > 0.1:
        return "low"
    return "info"


def severity_for_metric_drift(pct: float | None, tolerance_pct: float) -> Severity:
    if pct is None:
        return "medium"
    a = abs(pct)
    if a <= tolerance_pct:
        return "info"
    return "high" if (a >= 10 or a >= 10 * tolerance_pct) else "medium"


def worst(severities: list[str]) -> str:
    return min(severities, key=lambda s: SEVERITY_ORDER[s]) if severities else "info"
