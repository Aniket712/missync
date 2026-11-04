import { ArrowRight, Plus, CheckCircle2, Database, Eye, EyeOff, FileText, Loader2, Lock, PlayCircle, RefreshCw, Search, Trash2, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../App";
import { api, type Asset, type Capabilities, type Preview, type Table, type TestResult } from "../api";
import { Empty, ErrorBox, fmt, PageHeader, Pill } from "../components/ui";
import { parsePgUrl } from "../lib/connection";

type Field = { key: string; label: string; secret?: boolean; placeholder?: string; options?: string[]; wide?: boolean };

const TYPE_META: Record<string, { label: string; blurb: string }> = {
  postgres: { label: "PostgreSQL", blurb: "Live database over the network" },
  sqlite: { label: "SQLite", blurb: "Local .sqlite file" },
  duckdb: { label: "DuckDB", blurb: "Local .duckdb file" },
  bigquery: { label: "BigQuery", blurb: "Google Cloud dataset" },
  snowflake: { label: "Snowflake", blurb: "Warehouse account" },
};
const ORDER = ["postgres", "sqlite", "duckdb", "bigquery", "snowflake"];

const FIELDS: Record<string, Field[]> = {
  sqlite: [{ key: "path", label: "File path (inside the data directory)", wide: true }],
  duckdb: [{ key: "path", label: "File path (inside the data directory)", wide: true }],
  postgres: [
    { key: "host", label: "Host", placeholder: "localhost" }, { key: "port", label: "Port", placeholder: "5432" },
    { key: "database", label: "Database", placeholder: "shop" }, { key: "schema", label: "Schema", placeholder: "public" },
    { key: "user", label: "Read-only user" }, { key: "password", label: "Password", secret: true },
    { key: "sslmode", label: "SSL mode", options: ["prefer", "disable", "require", "verify-full"] },
  ],
  bigquery: [{ key: "project", label: "Project" }, { key: "dataset", label: "Dataset" }, { key: "credentials_json", label: "Service-account JSON (blank = Application Default Credentials)", secret: true, wide: true }],
  snowflake: [
    { key: "account", label: "Account" }, { key: "user", label: "User" }, { key: "database", label: "Database" }, { key: "schema", label: "Schema", placeholder: "PUBLIC" },
    { key: "warehouse", label: "Warehouse" }, { key: "role", label: "Role (SELECT-only)" }, { key: "private_key", label: "Private key PEM (preferred)", secret: true, wide: true },
  ],
};
const DEFAULTS: Record<string, Record<string, string>> = {
  postgres: { host: "localhost", port: "5432", schema: "public", sslmode: "prefer" },
};

function AddConnection({ types, onAdded }: { types: string[]; onAdded: (id: string, name: string) => void }) {
  const available = ORDER.filter((t) => types.includes(t));
  const [type, setType] = useState(available[0] ?? "sqlite");
  const [name, setName] = useState("");
  const [vals, setVals] = useState<Record<string, string>>(DEFAULTS[available[0] ?? ""] ?? {});
  const [urlText, setUrlText] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | "sample" | null>(null);
  const [step, setStep] = useState(0); // 0 idle, 1 starting server, 2 testing
  const fields = FIELDS[type] ?? [];

  const edit = (patch: Record<string, string>) => { setVals((v) => ({ ...v, ...patch })); setResult(null); setError(null); };
  const pick = (t: string) => { setType(t); setVals(DEFAULTS[t] ?? {}); setResult(null); setError(null); setUrlText(""); };
  const body = (v = vals, n = name) => {
    const params: Record<string, unknown> = {};
    fields.forEach((f) => { if (v[f.key]) params[f.key] = f.key === "port" ? Number(v[f.key]) : v[f.key]; });
    return { name: n || TYPE_META[type]?.label || type, type, params };
  };

  const run = async (kind: "test" | "save") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "test") setResult(await api.testNewConnection(body()));
      else {
        const b = body();
        const r = await api.addConnection(b);
        setVals(DEFAULTS[type] ?? {}); setName(""); setResult(null); setUrlText("");
        onAdded(r.id, b.name);
      }
    } catch (e) {
      setResult(null);
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const launchSample = async () => {
    setBusy("sample");
    setError(null);
    setStep(1);
    try {
      const s = await api.startSample();
      setStep(2);
      const p = Object.fromEntries(Object.entries(s.params ?? {}).map(([k, v]) => [k, String(v)]));
      const v = { ...DEFAULTS.postgres, ...p, sslmode: "disable" };
      setVals(v);
      setName("Sample shop (PostgreSQL)");
      setResult(await api.testNewConnection(body(v, "Sample shop (PostgreSQL)")));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      setStep(0);
    }
  };

  const applyUrl = (text: string) => {
    setUrlText(text);
    const parsed = parsePgUrl(text);
    if (parsed) edit(parsed);
  };

  return (
    <div className="card p-4">
      <h3 className="mb-1 font-semibold">Add a connection</h3>
      <p className="mb-3 flex items-center gap-1.5 text-xs text-muted"><Lock size={12} /> Use a read-only database user. Secrets are encrypted at rest and never shown again.</p>

      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Connector type">
        {available.map((t) => (
          <button key={t} role="radio" aria-checked={type === t} onClick={() => pick(t)}
            className={`rounded-lg border p-2.5 text-left text-sm transition ${type === t ? "border-brand bg-brand/10 ring-1 ring-brand" : "border-line hover:bg-bg"}`}>
            <Database size={15} className="mb-1 text-brand" />
            <div className="font-medium">{TYPE_META[t]?.label ?? t}</div>
            <div className="text-xs text-muted">{TYPE_META[t]?.blurb}</div>
          </button>
        ))}
      </div>

      {type === "postgres" && (
        <div className="mb-4 space-y-3 rounded-lg border border-dashed border-line bg-bg p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm"><b>No database handy?</b> <span className="text-muted">Start a built-in sample PostgreSQL with demo shop data.</span></div>
            <button className="btn" onClick={launchSample} disabled={busy !== null}>
              {busy === "sample" ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />} {busy === "sample" ? "Starting…" : "Launch sample database"}
            </button>
          </div>
          {busy === "sample" && (
            <ol className="flex flex-wrap gap-x-5 gap-y-1 text-xs" aria-live="polite" aria-label="Sample database progress">
              {["Starting PostgreSQL & loading shop data (first run ~15 s)", "Testing the connection"].map((t, i) => (
                <li key={t} className={`flex items-center gap-1.5 ${step > i + 1 ? "text-ok" : step === i + 1 ? "font-medium text-fg" : "text-muted"}`}>
                  {step > i + 1 ? <CheckCircle2 size={13} /> : step === i + 1 ? <Loader2 size={13} className="animate-spin" /> : <span className="h-3 w-3 rounded-full border border-line" />} {t}
                </li>
              ))}
            </ol>
          )}
          <label className="block text-xs font-medium text-muted">Or paste a connection URL
            <input className="input mt-1 font-mono" autoComplete="off" placeholder="postgresql://user:password@host:5432/database" value={urlText} onChange={(e) => applyUrl(e.target.value)} />
          </label>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium sm:col-span-2">Connection name
          <input className="input mt-1" value={name} placeholder={TYPE_META[type]?.label} onChange={(e) => { setName(e.target.value); }} />
        </label>
        {fields.map((f) => (
          <label key={f.key} className={`text-sm font-medium ${f.wide ? "sm:col-span-2" : ""}`}>{f.label}
            {f.options ? (
              <select className="input mt-1" value={vals[f.key] ?? f.options[0]} onChange={(e) => edit({ [f.key]: e.target.value })}>
                {f.options.map((o) => <option key={o}>{o}</option>)}
              </select>
            ) : (
              <span className="relative block">
                <input className="input mt-1 pr-9" type={f.secret && !showPw ? "password" : "text"} autoComplete="off" placeholder={f.placeholder}
                  value={vals[f.key] ?? ""} onChange={(e) => edit({ [f.key]: e.target.value })} />
                {f.key === "password" && (
                  <button type="button" className="absolute right-2 top-[18px] text-muted" aria-label={showPw ? "Hide password" : "Show password"} onClick={() => setShowPw(!showPw)}>
                    {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                )}
              </span>
            )}
          </label>
        ))}
      </div>

      <div className="mt-4"><ErrorBox error={error} /></div>
      {result && (
        <div role="status" className="mb-3 rounded-lg border border-ok/40 bg-ok/10 p-3 text-sm">
          <div className="flex items-center gap-1.5 font-medium text-ok"><CheckCircle2 size={16} /> Connection works</div>
          <div className="mt-1 text-xs text-muted">
            {[result.server, result.latency_ms != null && `${result.latency_ms} ms`, result.objects != null && `${result.objects} tables/views found`,
              result.read_only === true && "read-only session confirmed", result.read_only === false && "⚠ session is not read-only"].filter(Boolean).join(" · ")}
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button className="btn" onClick={() => run("test")} disabled={busy !== null}>
          {busy === "test" ? <Loader2 size={15} className="animate-spin" /> : <PlayCircle size={15} />} {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        <button className="btn btn-primary" onClick={() => run("save")} disabled={busy !== null || !result} title={result ? "" : "Test the connection first"}>
          {busy === "save" ? "Saving…" : "Save connection"}
        </button>
      </div>
    </div>
  );
}

function PreviewTable({ id, table }: { id: string; table: string }) {
  const [data, setData] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setData(null); setError(null);
    api.preview(id, table).then(setData).catch((e) => setError(e.message));
  }, [id, table]);
  if (error) return <p className="mt-2 text-xs text-critical">{error}</p>;
  if (!data) return <p className="mt-2 text-xs text-muted">Loading rows…</p>;
  return (
    <div className="mt-2 overflow-auto rounded-lg border border-line bg-surface">
      <table className="w-full text-xs">
        <thead><tr>{data.columns.map((c) => <th key={c} className="whitespace-nowrap px-2 py-1 text-left font-semibold">{c}</th>)}</tr></thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} className="border-t border-line">{r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1 font-mono">{v === null ? <span className="text-muted">NULL</span> : String(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <p className="px-2 py-1 text-xs text-muted">First {data.rows.length} rows{data.truncated ? " (more in source)" : ""}. Read-only sample.</p>
    </div>
  );
}

function SchemaBrowser({ id }: { id: string }) {
  const [data, setData] = useState<{ tables: Table[]; caps: Capabilities; dialect: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [rows, setRows] = useState<string | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    setData(null); setError(null); setOpen(null); setRows(null); setQ("");
    api.schema(id).then((r) => setData({ tables: r.schema.tables, caps: r.capabilities, dialect: r.schema.dialect })).catch((e) => setError(e.message));
  }, [id]);
  const shown = useMemo(() => (data?.tables ?? []).filter((t) => t.name.toLowerCase().includes(q.toLowerCase())), [data, q]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" /> Discovering schema…</p>;
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <Pill tone="ok"><Eye size={12} className="mr-1" /> Read-only discovery</Pill>
        <Pill>{data.tables.length} objects</Pill>
        <Pill>{data.caps.sandbox_validation ? "Sandbox validation supported" : "Static analysis only"}</Pill>
      </div>
      <p className="mb-3 text-xs text-muted">{data.caps.read_only_enforced}</p>
      <label className="relative mb-3 block">
        <Search size={14} className="absolute left-2.5 top-3 text-muted" />
        <input className="input !pl-8" placeholder="Search tables and views" aria-label="Search tables and views" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {shown.length === 0 && <li className="px-3 py-3 text-sm text-muted">No matches.</li>}
        {shown.map((t) => (
          <li key={t.name}>
            <button className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-bg" aria-expanded={open === t.name} onClick={() => { setOpen(open === t.name ? null : t.name); setRows(null); }}>
              <span className="font-medium">{t.name} <Pill>{t.kind}</Pill></span>
              <span className="text-xs text-muted">{t.columns.length} columns{t.row_count != null ? ` · ${t.row_count_estimated ? "~" : ""}${fmt(t.row_count)} rows` : ""}</span>
            </button>
            {open === t.name && (
              <div className="bg-bg px-3 pb-3">
                <table className="w-full text-xs">
                  <tbody>
                    {t.columns.map((c) => (
                      <tr key={c.name} className="border-t border-line">
                        <td className="py-1 font-mono">{c.name}{c.primary_key ? " 🔑" : ""}</td>
                        <td className="text-muted">{c.type}</td>
                        <td className="text-right text-muted">{c.nullable ? "nullable" : "not null"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {t.definition && <pre className="mt-2 overflow-auto rounded-lg border border-line bg-surface p-2 font-mono text-xs">{t.definition}</pre>}
                <button className="btn mt-2 py-1" onClick={() => setRows(rows === t.name ? null : t.name)}><FileText size={14} /> {rows === t.name ? "Hide rows" : "Preview rows"}</button>
                {rows === t.name && <PreviewTable id={id} table={t.name} />}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const ASSET_KINDS = ["dashboard", "report", "model", "export", "service"];

/** Downstream consumers (dashboards, reports, jobs) that depend on tables; they make impact analysis meaningful. */
function AssetsPanel({ id, readOnly }: { id: string; readOnly: boolean }) {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", kind: "dashboard", deps: "", owner: "" });

  useEffect(() => {
    setAssets(null);
    setError(null);
    api.assets(id).then(setAssets).catch((e) => setError(e.message));
  }, [id]);

  const save = async (next: Asset[]) => {
    setError(null);
    try { await api.setAssets(id, next); setAssets(next); } catch (e) { setError((e as Error).message); }
  };
  const add = async () => {
    const deps = form.deps.split(",").map((d) => d.trim()).filter(Boolean);
    if (!form.name.trim() || deps.length === 0) { setError("Give the asset a name and at least one table or table.column it depends on."); return; }
    await save([...(assets ?? []), { name: form.name.trim(), kind: form.kind, depends_on: deps, owner: form.owner.trim() || null }]);
    setForm({ name: "", kind: "dashboard", deps: "", owner: "" });
  };

  return (
    <div className="card mt-5 p-4">
      <h2 className="font-semibold">Downstream assets</h2>
      <p className="mb-3 text-xs text-muted">Register what depends on this data (dashboards, reports, jobs). Analyses then show which of them a change would affect.</p>
      <ErrorBox error={error} />
      {assets === null ? <p className="text-sm text-muted">Loading…</p> : assets.length === 0 ? (
        <p className="mb-3 text-sm text-muted">None registered yet; impact is limited to database objects.</p>
      ) : (
        <ul className="mb-3 divide-y divide-line rounded-lg border border-line text-sm">
          {assets.map((a, i) => (
            <li key={`${a.name}-${i}`} className="flex items-center justify-between gap-2 px-3 py-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{a.name} <Pill>{a.kind}</Pill></div>
                <div className="truncate font-mono text-xs text-muted">{a.depends_on.join(", ")}{a.owner ? ` · ${a.owner}` : ""}</div>
              </div>
              {!readOnly && <button className="btn" aria-label={`Remove ${a.name}`} onClick={() => save(assets.filter((_, j) => j !== i))}><Trash2 size={14} /></button>}
            </li>
          ))}
        </ul>
      )}
      {readOnly ? <p className="text-xs text-muted">Assets are read-only in the public demo.</p> : (
        <div className="grid gap-2 sm:grid-cols-2">
          <input className="input" aria-label="Asset name" placeholder="Name, e.g. Revenue dashboard" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="input" aria-label="Asset kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {ASSET_KINDS.map((k) => <option key={k}>{k}</option>)}
          </select>
          <input className="input font-mono sm:col-span-2" aria-label="Depends on" placeholder="Depends on: orders, customers.email, v_daily_revenue" value={form.deps} onChange={(e) => setForm({ ...form, deps: e.target.value })} />
          <input className="input" aria-label="Owner" placeholder="Owner (optional)" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} />
          <button className="btn" onClick={add}><Plus size={15} /> Add asset</button>
        </div>
      )}
    </div>
  );
}

export default function Connections() {
  const { connections, config, reload, connectionId, setConnectionId } = useApp();
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [status, setStatus] = useState<Record<string, { ok: boolean; text: string } | "busy">>({});

  const remove = async (id: string) => {
    setConfirmId(null);
    try { await api.deleteConnection(id); reload(); } catch (e) { setError((e as Error).message); }
  };
  const retest = async (id: string) => {
    setStatus((s) => ({ ...s, [id]: "busy" }));
    try {
      const r = await api.testConnection(id);
      setStatus((s) => ({ ...s, [id]: { ok: true, text: [r.server, r.latency_ms != null && `${r.latency_ms} ms`].filter(Boolean).join(" · ") || "OK" } }));
    } catch (e) {
      setStatus((s) => ({ ...s, [id]: { ok: false, text: (e as Error).message } }));
    }
  };
  const isSample = (c: { type: string; params: Record<string, unknown> }) =>
    c.type === "postgres" && ["127.0.0.1", "localhost"].includes(String(c.params.host)) && c.params.user === "missync_ro" && c.params.database === "shop";
  const relaunch = async (id: string) => {
    setStatus((s) => ({ ...s, [id]: "busy" }));
    try { await api.startSample(); } catch (e) { setStatus((s) => ({ ...s, [id]: { ok: false, text: (e as Error).message } })); return; }
    await retest(id);
  };
  const onAdded = (id: string, name: string) => { setAdded(name); setConnectionId(id); reload(); };

  return (
    <div>
      <PageHeader title="Connections" subtitle="Missync reads metadata and a bounded sample of rows. It never writes to a connected database." />
      <ErrorBox error={error} />
      {added && (
        <div role="status" className="card mb-5 flex flex-wrap items-center justify-between gap-3 border-ok/40 bg-ok/10 p-4">
          <div className="flex items-center gap-2 text-sm"><CheckCircle2 size={18} className="text-ok" /> <span><b>{added}</b> is connected. Browse its schema on the right, then analyze a change against it.</span></div>
          <Link to="/analyze" className="btn btn-primary">Analyze a change <ArrowRight size={15} /></Link>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-2">
          {connections.length === 0 ? <Empty>No connections.</Empty> : connections.map((c) => {
            const st = status[c.id];
            return (
              <div key={c.id} className={`card p-3 ${c.id === connectionId ? "ring-2 ring-brand" : ""}`}>
                <div className="flex items-center justify-between gap-2">
                  <button className="min-w-0 flex-1 text-left" onClick={() => setConnectionId(c.id)}>
                    <div className="flex items-center gap-2 truncate font-medium">
                      {st && st !== "busy" && <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${st.ok ? "bg-ok" : "bg-critical"}`} aria-hidden />}
                      {c.name}
                    </div>
                    <div className="text-xs text-muted">{TYPE_META[c.type]?.label ?? c.type}{c.builtin ? " · bundled" : ""}</div>
                  </button>
                  <button className="btn" aria-label={`Re-test ${c.name}`} title="Re-test connection" onClick={() => retest(c.id)} disabled={st === "busy"}>
                    <RefreshCw size={15} className={st === "busy" ? "animate-spin" : ""} />
                  </button>
                  {!c.builtin && !config?.demo && (confirmId === c.id ? (
                    <button className="btn text-critical" onClick={() => remove(c.id)}>Confirm</button>
                  ) : (
                    <button className="btn" aria-label={`Delete ${c.name}`} onClick={() => setConfirmId(c.id)}><Trash2 size={15} /></button>
                  ))}
                </div>
                {st && st !== "busy" && <p className={`mt-1.5 text-xs ${st.ok ? "text-ok" : "text-critical"}`}>{st.ok ? `✓ ${st.text}` : st.text}</p>}
                {st && st !== "busy" && !st.ok && isSample(c) && (
                  <button className="btn mt-2 py-1 text-xs" onClick={() => relaunch(c.id)}><Zap size={13} /> Sample database stopped? Relaunch it</button>
                )}
              </div>
            );
          })}
          {config?.demo ? (
            <div className="card p-4 text-sm text-muted">
              <Lock size={14} className="mb-1" />
              <p>Custom connections are disabled in the public demo so nobody can point the server at arbitrary hosts. Run Missync locally (<code>.\start.ps1</code> or <code>docker compose up</code>) to connect PostgreSQL, SQLite, DuckDB, BigQuery or Snowflake.</p>
            </div>
          ) : (
            config ? <AddConnection types={config.connector_types} onAdded={onAdded} /> : <div className="card p-4 text-sm text-muted">Loading…</div>
          )}
        </div>
        <div className="card p-4 lg:col-span-3">
          <h2 className="mb-3 font-semibold">Schema discovery</h2>
          <SchemaBrowser id={connectionId} />
        </div>
        <div className="lg:col-span-3 lg:col-start-3">
          <AssetsPanel id={connectionId} readOnly={!!config?.demo} />
        </div>
      </div>
    </div>
  );
}
