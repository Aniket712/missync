import * as Tabs from "@radix-ui/react-tabs";
import { Download, FlaskConical, Wand2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { downloadReport, type Analysis, type Finding, type SchemaChange, type TableComparison } from "../api";
import { fmt, Pill, pct, SeverityBadge, when } from "./ui";
import { BlastRadius, MetricDrift, NullRateBars, ReconBars, RowCountBars, SchemaChips, SeverityBar, StatTile } from "./viz";

const ImpactGraph = lazy(() => import("./ImpactGraph"));

const tabCls =
  "px-3 py-2 text-sm font-medium text-muted border-b-2 border-transparent data-[state=active]:border-brand data-[state=active]:text-fg hover:text-fg";

const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const STRIPE: Record<string, string> = { critical: "border-l-critical", high: "border-l-high", medium: "border-l-medium", low: "border-l-low", info: "border-l-line" };

export function FindingCard({ f }: { f: Finding }) {
  return (
    <article className={`card border-l-4 p-3.5 ${STRIPE[f.severity]}`}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge s={f.severity} />
        <Pill tone={f.kind === "verified" ? "ok" : "neutral"}>{f.kind === "verified" ? "Verified" : "Predicted"}</Pill>
        {f.possibly_intended && <Pill tone="brand">May be intended</Pill>}
        <h3 className="min-w-0 flex-1 basis-60 font-semibold">{f.title}</h3>
      </div>
      <p className="mt-1.5 text-sm text-muted">{f.summary}</p>
      {f.affected.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Affected objects">
          {f.affected.slice(0, 8).map((a) => <span key={a} className="rounded-md bg-bg px-1.5 py-0.5 font-mono text-xs">{a.replace(/^asset:/, "★ ")}</span>)}
          {f.affected.length > 8 && <span className="text-xs text-muted">+{f.affected.length - 8} more</span>}
        </div>
      )}
      {f.recommendation && (
        <p className="mt-2 rounded-lg bg-brand/10 px-2.5 py-1.5 text-sm"><span className="font-semibold text-brand">Next step · </span>{f.recommendation}</p>
      )}
      <details className="mt-2 text-xs text-muted">
        <summary className="cursor-pointer">Evidence &amp; basis · confidence {f.confidence}</summary>
        <p className="mt-1">{f.confidence_reason}</p>
        {f.limitations.map((l) => (
          <p key={l}>Limitation: {l}</p>
        ))}
        <pre className="mt-2 overflow-auto rounded-lg bg-bg p-2 font-mono">{JSON.stringify(f.evidence, null, 2)}</pre>
      </details>
    </article>
  );
}

function SchemaTable({ diff }: { diff: SchemaChange[] }) {
  if (!diff.length) return <p className="text-sm text-muted">No schema differences observed.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3">Change</th>
            <th className="pr-3">Object</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {diff.map((d, i) => (
            <tr key={i} className="border-t border-line">
              <td className="py-1.5 pr-3 font-mono text-xs">{d.change}</td>
              <td className="pr-3">
                {d.table}
                {d.column ? `.${d.column}` : ""}
              </td>
              <td className="text-muted">
                {d.change === "type_changed" ? `${d.old} → ${d.new} (${d.compatibility})` : d.change === "nullability_changed" ? `${d.old} → ${d.new}` : (d.type ?? "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TableComparisonView({ rows }: { rows: TableComparison[] }) {
  const compared = rows.filter((r) => r.status === "compared");
  if (!compared.length) return <p className="text-sm text-muted">No comparison data available.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3">Table</th>
            <th className="pr-3 text-right">Before</th>
            <th className="pr-3 text-right">After</th>
            <th className="text-right">Change</th>
          </tr>
        </thead>
        <tbody>
          {compared.map((r) => (
            <tr key={r.table} className="border-t border-line">
              <td className="py-1.5 pr-3">
                {r.table} {r.kind === "view" && <Pill>view</Pill>}
              </td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.rows_before)}</td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.rows_after)}</td>
              <td className={`text-right tabular-nums ${r.row_delta ? "font-medium" : "text-muted"}`}>
                {r.row_delta ? `${r.row_delta > 0 ? "+" : ""}${fmt(r.row_delta)} (${pct(r.row_delta_pct)})` : "none"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {compared.some((r) => r.columns?.some((c) => c.null_rate_delta !== 0)) && (
        <>
          <h4 className="mb-1 mt-4 text-sm font-semibold">NULL-rate changes</h4>
          <ul className="text-sm">
            {compared.flatMap((r) =>
              (r.columns ?? [])
                .filter((c) => Math.abs(c.null_rate_delta) > 0.0005)
                .map((c) => (
                  <li key={r.table + c.column} className="text-muted">
                    <span className="font-medium text-fg">
                      {r.table}.{c.column}
                    </span>{" "}
                    {(c.null_rate_before * 100).toFixed(1)}% → {(c.null_rate_after * 100).toFixed(1)}%
                  </li>
                )),
            )}
          </ul>
        </>
      )}
    </div>
  );
}

function Metrics({ a }: { a: Analysis }) {
  if (!a.metric_comparison.length) return <p className="text-sm text-muted">No business metrics were selected for this analysis.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3">Metric</th>
            <th className="pr-3 text-right">Before</th>
            <th className="pr-3 text-right">After</th>
            <th className="pr-3 text-right">Drift</th>
            <th className="text-right">Tolerance</th>
          </tr>
        </thead>
        <tbody>
          {a.metric_comparison.map((m) => {
            const out = m.delta_pct !== null && m.delta_pct !== undefined && Math.abs(m.delta_pct) > m.tolerance_pct;
            return (
              <tr key={m.name} className="border-t border-line">
                <td className="py-1.5 pr-3">{m.name}</td>
                <td className="pr-3 text-right tabular-nums">{fmt(m.before, 2)}</td>
                <td className="pr-3 text-right tabular-nums">{fmt(m.after, 2)}</td>
                <td className={`pr-3 text-right tabular-nums ${out ? "font-semibold text-high" : "text-muted"}`}>{m.error ?? pct(m.delta_pct, 2)}</td>
                <td className="text-right text-muted">±{m.tolerance_pct}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const SEVTONE: Record<string, "critical" | "high" | "medium" | "ok" | "fg"> = { critical: "critical", high: "high", medium: "medium", low: "fg", info: "ok" };

export default function Result({ a }: { a: Analysis }) {
  const s = a.summary;
  return (
    <div>
      <section className="card mb-5 p-5" aria-label="Risk summary">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge s={s.highest_severity} />
              <Pill tone={s.validated_in_sandbox ? "ok" : "neutral"}>
                {s.validated_in_sandbox ? <><FlaskConical size={12} className="mr-1" /> Validated in isolated copy</> : "Static analysis only"}
              </Pill>
              {!s.lineage_complete && <Pill>Lineage incomplete</Pill>}
            </div>
            <h2 className="mt-2 text-lg font-semibold">{s.verdict}</h2>
            <p className="mt-1 text-xs text-muted">
              {a.title} · {when(a.created_at)} · {s.verified} verified, {s.predicted} predicted finding{s.verified + s.predicted === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex gap-2">
            <button className="btn" onClick={() => downloadReport(a.id, "html").catch(() => undefined)}>
              <Download size={15} /> HTML
            </button>
            <button className="btn" onClick={() => downloadReport(a.id, "json").catch(() => undefined)}>
              <Download size={15} /> JSON
            </button>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile value={a.findings.length} label="findings" tone={a.findings.length ? SEVTONE[s.highest_severity] : "ok"} />
          <StatTile value={a.graph.nodes.filter((n) => n.changed).length} label="objects changed" />
          <StatTile value={a.graph.nodes.filter((n) => n.impacted && n.type !== "asset").length} label="dependent objects" tone={a.graph.nodes.some((n) => n.impacted && n.type !== "asset") ? "medium" : "ok"} />
          <StatTile value={a.graph.nodes.filter((n) => n.type === "asset").length} label="downstream assets" tone={a.graph.nodes.some((n) => n.type === "asset") ? "high" : "ok"} />
        </div>
        <div className="mt-4"><SeverityBar counts={s.by_severity} /></div>
        <h3 className="mb-2 mt-5 text-sm font-semibold">Blast radius</h3>
        <BlastRadius a={a} />
        {s.recommended_actions.length > 0 && (
          <div className="mt-4 rounded-lg bg-bg p-3">
            <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
              <Wand2 size={14} /> Recommended actions
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {s.recommended_actions.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <Tabs.Root defaultValue="findings">
        <Tabs.List className="mb-4 flex flex-wrap border-b border-line" aria-label="Result sections">
          <Tabs.Trigger className={tabCls} value="findings">Findings ({a.findings.length})</Tabs.Trigger>
          <Tabs.Trigger className={tabCls} value="schema">Schema ({a.schema_diff.length})</Tabs.Trigger>
          <Tabs.Trigger className={tabCls} value="data">Data &amp; metrics</Tabs.Trigger>
          <Tabs.Trigger className={tabCls} value="impact">Impact graph</Tabs.Trigger>
          <Tabs.Trigger className={tabCls} value="sql">SQL &amp; limits</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="findings" className="space-y-3">
          {a.findings.length === 0 && <div className="card p-6 text-sm text-muted">No differences were detected in the isolated copy. This is not a guarantee of safety — see limitations.</div>}
          {[...a.findings].sort((x, y) => SEV_RANK[x.severity] - SEV_RANK[y.severity]).map((f) => <FindingCard key={f.id} f={f} />)}
        </Tabs.Content>

        <Tabs.Content value="schema" className="card p-4">
          <SchemaChips diff={a.schema_diff} />
          {a.schema_diff.length > 0 && <details className="mt-3 text-sm"><summary className="cursor-pointer text-muted">Show as table</summary><div className="mt-2"><SchemaTable diff={a.schema_diff} /></div></details>}
        </Tabs.Content>

        <Tabs.Content value="data" className="space-y-4">
          <div className="card p-4"><h3 className="mb-3 font-semibold">Business metrics vs tolerance</h3><MetricDrift metrics={a.metric_comparison} />
            {a.metric_comparison.length > 0 && <details className="mt-3 text-sm"><summary className="cursor-pointer text-muted">Show as table</summary><div className="mt-2"><Metrics a={a} /></div></details>}</div>
          <div className="card p-4"><h3 className="mb-3 font-semibold">Where did the records go?</h3><ReconBars items={a.reconciliation} /></div>
          <div className="card p-4"><h3 className="mb-3 font-semibold">Row counts before / after</h3><RowCountBars rows={a.table_comparison} /><NullRateBars rows={a.table_comparison} />
            <details className="mt-3 text-sm"><summary className="cursor-pointer text-muted">Show as table</summary><div className="mt-2"><TableComparisonView rows={a.table_comparison} /></div></details></div>
        </Tabs.Content>

        <Tabs.Content value="impact" className="card p-4">
          <Suspense fallback={<p className="text-sm text-muted">Loading graph…</p>}>
            <ImpactGraph graph={a.graph} />
          </Suspense>
        </Tabs.Content>

        <Tabs.Content value="sql" className="space-y-4">
          <div className="card p-4">
            <h3 className="mb-2 font-semibold">Proposed SQL ({a.dialect})</h3>
            <pre className="overflow-auto rounded-lg bg-bg p-3 font-mono text-xs">{a.sql}</pre>
            {a.validation.outcomes && (
              <ul className="mt-3 space-y-1 text-sm">
                {a.validation.outcomes.map((o) => (
                  <li key={o.index} className="text-muted">
                    Statement {o.index + 1}: <span className={o.status === "failed" ? "font-semibold text-high" : "text-fg"}>{o.status}</span>
                    {o.message ? ` — ${o.message}` : ""}
                    {o.rows_affected != null ? ` (${fmt(o.rows_affected)} rows)` : ""}
                  </li>
                ))}
              </ul>
            )}
            {a.validation.engine && <p className="mt-2 text-xs text-muted">Executed in: {a.validation.engine}. The source database was only read.</p>}
          </div>
          <div className="card p-4">
            <h3 className="mb-2 font-semibold">Limitations of this analysis</h3>
            {a.limitations.length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm">{a.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            ) : (
              <p className="text-sm text-muted">No specific limitations were recorded. Workloads, data outside the copy and unregistered consumers are never visible to Missync.</p>
            )}
          </div>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
