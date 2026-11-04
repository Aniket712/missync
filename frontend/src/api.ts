export type Severity = "critical" | "high" | "medium" | "low" | "info";

export interface Finding {
  id: string;
  category: string;
  title: string;
  severity: Severity;
  kind: "predicted" | "verified";
  confidence: "high" | "medium" | "low";
  confidence_reason: string;
  summary: string;
  evidence: Record<string, unknown>;
  affected: string[];
  recommendation: string;
  possibly_intended: boolean;
  limitations: string[];
}

export interface GraphNode { id: string; label: string; type: string; impacted: boolean; changed: boolean; detail?: string | null }
export interface GraphEdge { source: string; target: string; complete: boolean }

export interface MetricRow {
  name: string; sql: string; before?: number | null; after?: number | null; delta?: number | null;
  delta_pct?: number | null; tolerance_pct: number; error?: string;
}

export interface TableComparison {
  table: string; status: string; kind?: string; rows_before?: number; rows_after?: number; row_delta?: number;
  row_delta_pct?: number | null;
  columns?: { column: string; null_rate_before: number; null_rate_after: number; null_rate_delta: number; type_before: string; type_after: string }[];
}

export interface Reconciliation {
  table: string; key: string[]; status: string; reason?: string; matched?: number; missing_in_candidate?: number;
  new_in_candidate?: number; changed_rows?: number; changed_by_column?: Record<string, number>; missing_examples?: string[][];
}

export interface SchemaChange { change: string; table: string; column?: string; old?: string; new?: string; type?: string; compatibility?: string }

export interface Analysis {
  id: string; title: string; connection_id: string; created_at: string; sql: string; dialect: string;
  statements: { index: number; kind: string; sql: string }[];
  validation: { mode?: string; engine?: string; outcomes?: { index: number; status: string; message: string; rows_affected?: number }[] };
  schema_diff: SchemaChange[]; table_comparison: TableComparison[]; metric_comparison: MetricRow[];
  reconciliation: Reconciliation[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[]; complete: boolean; notes: string[] };
  findings: Finding[]; limitations: string[];
  summary: {
    highest_severity: Severity; by_severity: Record<Severity, number>; verified: number; predicted: number;
    validated_in_sandbox: boolean; lineage_complete: boolean; impacted_objects: string[]; recommended_actions: string[]; verdict: string;
  };
}

export interface AnalysisListItem { id: string; title: string; created_at: string; connection_id: string; severity: Severity; finding_count: number; summary: Analysis["summary"] }

export interface Column { name: string; type: string; nullable: boolean; primary_key: boolean }
export interface Table { name: string; kind: "table" | "view"; columns: Column[]; definition?: string | null; row_count?: number | null; row_count_estimated?: boolean }
export interface Capabilities { discovery: boolean; views: boolean; view_definitions: boolean; sandbox_validation: boolean; read_only_enforced: string; notes: string }
export interface Connection { id: string; name: string; type: string; builtin: boolean; created_at: string; params: Record<string, unknown> }
export interface MetricIn { name: string; sql: string; tolerance_pct: number }
export interface Scenario { id: string; title: string; description: string; sql: string; metrics: MetricIn[]; keys: Record<string, string[]> }
export interface AppConfig { mode: string; demo: boolean; connector_types: string[]; limits: { sample_limit: number; timeout_s: number; max_sql_chars: number } }
export interface Asset { name: string; kind: string; depends_on: string[]; owner?: string | null }
export interface BaselineItem { id: string; name: string; created_at: string; signature: string; tables: number; has_profile: boolean }
export interface BaselineCompare {
  from: { id: string; name: string; captured_at: string }; to: { name: string; captured_at: string };
  schema_changed: boolean; schema_diff: SchemaChange[]; table_comparison: TableComparison[]; findings: Finding[]; limitations: string[];
}

export interface NewConnection { name: string; type: string; params: Record<string, unknown> }
export interface TestResult { server?: string; read_only?: boolean; latency_ms?: number; objects?: number; capabilities: Capabilities }
export interface Preview { columns: string[]; rows: unknown[][]; truncated: boolean }
export interface SampleStatus { available: boolean; running: boolean; message?: string; params?: Record<string, unknown> | null }

export interface AnalyzeBody { connection_id: string; sql: string; title?: string; sql_dialect?: string; metrics: MetricIn[]; keys: Record<string, string[]> }
export interface Job { id: string; status: "queued" | "running" | "done" | "failed" | "cancelled"; stage: string; percent: number; result_id: string | null; error: string | null }

export class ApiError extends Error {}

const TOKEN_KEY = "missync.token";
export const getToken = (): string => {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
};
export const setToken = (t: string) => {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
};
const authHeaders = (): Record<string, string> => (getToken() ? { Authorization: `Bearer ${getToken()}` } : {});

async function failure(r: Response): Promise<ApiError> {
  if (r.status === 401) window.dispatchEvent(new Event("missync:unauthorized"));
  let msg = r.statusText;
  try {
    const j = await r.json();
    msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* keep status text */
  }
  return new ApiError(msg);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { ...init, headers: { "Content-Type": "application/json", ...authHeaders() } });
  if (!r.ok) throw await failure(r);
  return r.status === 204 ? (undefined as T) : r.json();
}

/** Downloads a report through fetch so the auth header is sent (a plain link cannot carry it). */
export async function downloadReport(id: string, kind: "html" | "json"): Promise<void> {
  const r = await fetch(`/api/analyses/${id}/report.${kind}`, { headers: authHeaders() });
  if (!r.ok) throw await failure(r);
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `missync-${id}.${kind}` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const post = (b: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(b) });

export const api = {
  config: () => req<AppConfig>("/config"),
  connections: () => req<Connection[]>("/connections"),
  addConnection: (b: NewConnection) => req<{ id: string; test: TestResult }>("/connections", post(b)),
  testNewConnection: (b: NewConnection) => req<TestResult>("/connections/test", post(b)),
  testConnection: (id: string) => req<TestResult>(`/connections/${id}/test`, { method: "POST" }),
  preview: (id: string, table: string) => req<Preview>(`/connections/${id}/preview?table=${encodeURIComponent(table)}&limit=20`),
  sampleStatus: () => req<SampleStatus>("/sample-postgres"),
  startSample: () => req<SampleStatus>("/sample-postgres/start", { method: "POST" }),
  deleteConnection: (id: string) => req<void>(`/connections/${id}`, { method: "DELETE" }),
  schema: (id: string) => req<{ schema: { dialect: string; tables: Table[] }; capabilities: Capabilities; type: string }>(`/connections/${id}/schema`),
  assets: (id: string) => req<Asset[]>(`/connections/${id}/assets`),
  scenarios: () => req<Scenario[]>("/scenarios"),
  runScenario: (id: string) => req<Analysis>(`/scenarios/${id}/run`, { method: "POST" }),
  analyze: (b: AnalyzeBody) => req<Analysis>("/analyses", post(b)),
  health: () => fetch("/api/health").then((r) => r.json() as Promise<{ ok: boolean; auth_required: boolean; version: string }>),
  startJob: (b: AnalyzeBody) => req<Job>("/jobs", post(b)),
  job: (id: string) => req<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => req<unknown>(`/jobs/${id}`, { method: "DELETE" }),
  analyses: (p: { q?: string; severity?: string; offset?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();
    return req<AnalysisListItem[]>(`/analyses${qs ? `?${qs}` : ""}`);
  },
  deleteAnalysis: (id: string) => req<void>(`/analyses/${id}`, { method: "DELETE" }),
  setAssets: (id: string, assets: Asset[]) => req<{ ok: boolean }>(`/connections/${id}/assets`, { method: "PUT", body: JSON.stringify(assets) }),
  analysis: (id: string) => req<Analysis>(`/analyses/${id}`),
  baselines: (cid: string) => req<BaselineItem[]>(`/connections/${cid}/baselines`),
  captureBaseline: (cid: string, name: string) => req<BaselineItem>(`/connections/${cid}/baselines`, post({ name })),
  deleteBaseline: (id: string) => req<void>(`/baselines/${id}`, { method: "DELETE" }),
  compareBaseline: (id: string, to = "current") => req<BaselineCompare>(`/baselines/${id}/compare?to=${encodeURIComponent(to)}`),
};
