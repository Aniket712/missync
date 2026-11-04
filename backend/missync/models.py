"""Shared Pydantic models: schema snapshots, findings and analysis results."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Confidence = Literal["high", "medium", "low"]
Kind = Literal["predicted", "verified"]

SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class Column(BaseModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False


class Table(BaseModel):
    name: str
    schema_name: str | None = None
    kind: Literal["table", "view"] = "table"
    columns: list[Column] = Field(default_factory=list)
    definition: str | None = None  # SQL of a view, if accessible
    row_count: int | None = None
    row_count_estimated: bool = False

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name.lower() == name.lower():
                return c
        return None


class SchemaSnapshot(BaseModel):
    dialect: str
    tables: list[Table] = Field(default_factory=list)

    def table(self, name: str) -> Table | None:
        for t in self.tables:
            if t.name.lower() == name.lower():
                return t
        return None


class Capabilities(BaseModel):
    discovery: bool = True
    views: bool = True
    view_definitions: bool = True
    sandbox_validation: bool = True
    read_only_enforced: str = ""
    notes: str = ""


class Asset(BaseModel):
    """A registered downstream consumer (dashboard, ML feature, export...)."""

    id: str | None = None
    name: str
    kind: str = "dashboard"
    depends_on: list[str] = Field(default_factory=list)  # "table" or "table.column"
    owner: str | None = None


class Finding(BaseModel):
    id: str
    category: str
    title: str
    severity: Severity
    kind: Kind
    confidence: Confidence
    confidence_reason: str = ""
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    affected: list[str] = Field(default_factory=list)
    recommendation: str = ""
    possibly_intended: bool = False
    limitations: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["table", "view", "column", "asset"]
    impacted: bool = False
    changed: bool = False
    detail: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    complete: bool = True


class ImpactGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    complete: bool = True
    notes: list[str] = Field(default_factory=list)


class MetricSpec(BaseModel):
    name: str
    sql: str  # single SELECT returning one numeric value
    tolerance_pct: float = 1.0


class AnalysisRequest(BaseModel):
    connection_id: str
    sql: str
    sql_dialect: str | None = None  # dialect of the proposed SQL; defaults to the connector dialect
    title: str | None = None
    metrics: list[MetricSpec] = Field(default_factory=list, max_length=25)
    keys: dict[str, list[str]] = Field(default_factory=dict, max_length=200)  # table -> key columns
    sample_limit: int | None = Field(default=None, ge=1)


class AnalysisResult(BaseModel):
    id: str
    title: str
    connection_id: str
    created_at: str
    sql: str
    dialect: str
    statements: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    schema_diff: list[dict[str, Any]] = Field(default_factory=list)
    table_comparison: list[dict[str, Any]] = Field(default_factory=list)
    metric_comparison: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation: list[dict[str, Any]] = Field(default_factory=list)
    graph: ImpactGraph = Field(default_factory=ImpactGraph)
    findings: list[Finding] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
