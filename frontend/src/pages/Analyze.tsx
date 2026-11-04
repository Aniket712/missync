import { sql } from "@codemirror/lang-sql";
import CodeMirror from "@uiw/react-codemirror";
import { Loader2, Plus, ScanSearch, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../App";
import { api, type Job, type MetricIn, type Scenario } from "../api";
import { ErrorBox, PageHeader } from "../components/ui";
import { suggestChanges, type Suggestion } from "../lib/connection";

const DIALECTS = ["", "postgres", "sqlite", "duckdb", "bigquery", "snowflake", "mysql"];

export default function Analyze() {
  const { connections, connectionId, setConnectionId } = useApp();
  const nav = useNavigate();
  const [query, setQueryRaw] = useState("");
  const [touched, setTouched] = useState(false);
  const setQuery = (v: string) => { setTouched(true); setQueryRaw(v); };
  const [title, setTitle] = useState("");
  const [dialect, setDialect] = useState("postgres");
  const [metrics, setMetrics] = useState<MetricIn[]>([]);
  const [keys, setKeys] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dark = document.documentElement.dataset.theme === "dark";

  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const hasSql = query.split("\n").some((l) => l.trim() && !l.trim().startsWith("--"));

  // Start from the bundled demo's example, but leave the editor empty (with a hint) for the user's own connections.
  useEffect(() => {
    if (!touched) setQueryRaw(connectionId === "demo" ? "ALTER TABLE orders ALTER COLUMN amount TYPE INTEGER;" : "");
  }, [connectionId, touched]);

  useEffect(() => {
    api.scenarios().then(setScenarios).catch(() => undefined);
  }, []);

  // Starter changes built from the connected schema, so a fresh connection can be analyzed without writing SQL.
  useEffect(() => {
    setSuggestions([]);
    api.schema(connectionId).then((r) => setSuggestions(suggestChanges(r.schema.tables))).catch(() => undefined);
  }, [connectionId]);

  const load = (s: Scenario) => {
    setQuery(s.sql);
    setTitle(s.title);
    setDialect("postgres");
    setMetrics(s.metrics);
    setKeys(Object.entries(s.keys).map(([t, c]) => `${t}: ${c.join(", ")}`).join("\n"));
  };

  const parseKeys = () =>
    Object.fromEntries(
      keys.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
        const [t, c = ""] = l.split(":");
        return [t.trim(), c.split(",").map((x) => x.trim()).filter(Boolean)];
      }),
    );

  const submit = async () => {
    if (busy || !hasSql) return;
    setBusy(true);
    setError(null);
    try {
      let j = await api.startJob({
        connection_id: connectionId, sql: query, title: title || undefined, sql_dialect: dialect || undefined,
        metrics: metrics.filter((m) => m.name && m.sql), keys: parseKeys(),
      });
      setJob(j);
      while (j.status === "queued" || j.status === "running") {
        await new Promise((r) => setTimeout(r, 400));
        j = await api.job(j.id);
        setJob(j);
      }
      if (j.status === "done" && j.result_id) { nav(`/analyses/${j.result_id}`); return; }
      if (j.status === "failed") setError(j.error ?? "The analysis failed");
    } catch (e) {
      setError((e as Error).message);
    }
    setJob(null);
    setBusy(false);
  };
  const cancel = () => { if (job) api.cancelJob(job.id).catch(() => undefined); };

  // Ctrl/Cmd+Enter runs the analysis from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); void submit(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div>
      <PageHeader
        title="Analyze a change"
        subtitle="Paste a SQL change or migration. It is analyzed statically, then applied only to a throw-away copy of your data — never to the source."
        actions={
          <button className="btn btn-primary px-5 py-2.5 text-base" onClick={submit} disabled={busy || !hasSql} title="Ctrl+Enter">
            {busy ? <Loader2 size={17} className="animate-spin" /> : <ScanSearch size={17} />} {busy ? "Analyzing…" : "Analyze change"}
          </button>
        }
      />
      <ErrorBox error={error} />
      {job && (
        <div role="status" aria-live="polite" className="card mb-4 p-4">
          <div className="mb-2 flex items-center justify-between gap-3 text-sm">
            <span className="font-medium">{job.status === "queued" ? "Waiting for a free worker…" : job.stage}</span>
            <button className="btn py-1" onClick={cancel}><X size={14} /> Cancel</button>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-bg" role="progressbar" aria-valuenow={job.percent} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-brand transition-all duration-300" style={{ width: `${Math.max(job.percent, 4)}%` }} />
          </div>
        </div>
      )}

      {scenarios.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Load a sample:</span>
          {scenarios.map((s) => (
            <button key={s.id} className="btn py-1" onClick={() => load(s)}>{s.id}</button>
          ))}
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Try a change on this connection:</span>
          {suggestions.map((s) => (
            <button key={s.label} className="btn py-1" onClick={() => { setQuery(s.sql); setTitle(s.label); setMetrics([]); setKeys(""); }}>{s.label}</button>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="card overflow-hidden">
            <CodeMirror value={query} height="280px" extensions={[sql()]} placeholder="-- Paste a SQL change or migration here, or pick a suggestion above. Ctrl+Enter to analyze." onChange={setQuery} theme={dark ? "dark" : "light"} aria-label="SQL editor"
              basicSetup={{ lineNumbers: true, foldGutter: false }} />
          </div>
          <details className="card p-4" open={metrics.length > 0}>
            <summary className="cursor-pointer font-medium">Business metrics to compare <span className="font-normal text-muted">(optional)</span></summary>
            <p className="my-2 text-sm text-muted">Single-value SELECT queries evaluated before and after. Drift beyond the tolerance is flagged; it may still be intended.</p>
            {metrics.map((m, i) => (
              <div key={i} className="mb-2 grid gap-2 sm:grid-cols-[1fr_2fr_90px_auto]">
                <input className="input" placeholder="Name" aria-label="Metric name" value={m.name} onChange={(e) => setMetrics(metrics.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input className="input font-mono" placeholder="SELECT SUM(amount) FROM orders" aria-label="Metric SQL" value={m.sql} onChange={(e) => setMetrics(metrics.map((x, j) => (j === i ? { ...x, sql: e.target.value } : x)))} />
                <input className="input" type="number" min={0} step={0.1} aria-label="Tolerance percent" value={m.tolerance_pct} onChange={(e) => setMetrics(metrics.map((x, j) => (j === i ? { ...x, tolerance_pct: Number(e.target.value) } : x)))} />
                <button className="btn" aria-label="Remove metric" onClick={() => setMetrics(metrics.filter((_, j) => j !== i))}><Trash2 size={15} /></button>
              </div>
            ))}
            <button className="btn" onClick={() => setMetrics([...metrics, { name: "", sql: "", tolerance_pct: 1 }])}><Plus size={15} /> Add metric</button>
          </details>
        </div>

        <div className="card space-y-3 self-start p-4">
          <label className="block text-sm font-medium">Connection
            <select className="input mt-1" value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.type})</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium">SQL dialect of the change
            <select className="input mt-1" value={dialect} onChange={(e) => setDialect(e.target.value)}>
              {DIALECTS.map((d) => <option key={d} value={d}>{d || "same as connection"}</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium">Title
            <input className="input mt-1" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Orders cleanup migration" />
          </label>
          <label className="block text-sm font-medium">Comparison keys
            <textarea className="input mt-1 font-mono" rows={3} value={keys} onChange={(e) => setKeys(e.target.value)} placeholder={"orders: order_id\ncustomers: customer_id"} />
            <span className="mt-1 block text-xs font-normal text-muted">Used for record-level comparison. Primary keys are used when omitted. A non-unique key is never used.</span>
          </label>
        </div>
      </div>
    </div>
  );
}
