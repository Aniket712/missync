import { ArrowRight, Database, FileCode2, LayoutDashboard, Minus, Plus, Table2, Pencil } from "lucide-react";
import type { ReactNode } from "react";
import type { Analysis, MetricRow, Reconciliation, SchemaChange, Severity, TableComparison } from "../api";
import { fmt, pct, SEV } from "./ui";

/** Lightweight, dependency-free visuals. Every graphic carries a text equivalent (aria-label / title) and never relies on colour alone. */

const SEV_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];
const SEV_BG: Record<Severity, string> = { critical: "bg-critical", high: "bg-high", medium: "bg-medium", low: "bg-low", info: "bg-muted/40" };

/* ---------- Severity distribution: one stacked bar instead of a row of badges ---------- */
export function SeverityBar({ counts }: { counts: Record<Severity, number> }) {
  const total = SEV_ORDER.reduce((n, k) => n + (counts[k] ?? 0), 0);
  if (!total) return null;
  const label = SEV_ORDER.filter((k) => counts[k]).map((k) => `${counts[k]} ${SEV[k].label}`).join(", ");
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-bg" role="img" aria-label={`Findings by severity: ${label}`}>
        {SEV_ORDER.filter((k) => counts[k]).map((k) => (
          <div key={k} className={`${SEV_BG[k]} first:rounded-l-full last:rounded-r-full`} style={{ width: `${(counts[k] / total) * 100}%` }} title={`${counts[k]} ${SEV[k].label}`} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SEV_ORDER.filter((k) => counts[k]).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-sm ${SEV_BG[k]}`} aria-hidden /> <b className="tabular-nums">{counts[k]}</b> <span className="text-muted">{SEV[k].label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------- Blast radius: Change → changed objects → affected views → affected assets ---------- */
function Stage({ title, tone, icon, items, empty }: { title: string; tone: string; icon: ReactNode; items: string[]; empty: string }) {
  const MAX = 4;
  return (
    <div className="min-w-0 flex-1 rounded-xl border border-line bg-surface p-3" style={{ borderTopWidth: 3, borderTopColor: `rgb(var(--${tone}))` }}>
      <div className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
        <span className="flex items-center gap-1.5">{icon} {title}</span>
        <span className="rounded-full bg-bg px-2 py-0.5 tabular-nums text-fg">{items.length}</span>
      </div>
      {items.length === 0 ? <p className="text-xs text-muted">{empty}</p> : (
        <ul className="space-y-1">
          {items.slice(0, MAX).map((i) => <li key={i} className="truncate rounded-md bg-bg px-2 py-1 text-sm" title={i}>{i}</li>)}
          {items.length > MAX && <li className="px-2 text-xs text-muted">+{items.length - MAX} more</li>}
        </ul>
      )}
    </div>
  );
}

export function BlastRadius({ a }: { a: Analysis }) {
  const nodes = a.graph.nodes;
  const changed = nodes.filter((n) => n.changed).map((n) => n.label);
  const views = nodes.filter((n) => n.impacted && n.type !== "asset").map((n) => n.label);
  const assets = nodes.filter((n) => n.type === "asset").map((n) => n.label);
  const kinds = [...new Set(a.statements.map((s) => s.kind.toUpperCase()))];
  const Arrow = () => <ArrowRight className="mx-auto my-1 shrink-0 self-center text-muted max-lg:rotate-90" size={20} aria-hidden />;
  return (
    <div role="group" aria-label={`Blast radius: ${changed.length} changed, ${views.length} dependent views or tables, ${assets.length} downstream assets`}>
      <div className="flex flex-col gap-1 lg:flex-row lg:items-stretch">
        <Stage title="Your change" tone="brand" icon={<FileCode2 size={14} />} items={kinds.length ? [`${a.statements.length} statement${a.statements.length === 1 ? "" : "s"}: ${kinds.join(", ")}`] : []} empty="No statements" />
        <Arrow />
        <Stage title="Directly changed" tone="high" icon={<Table2 size={14} />} items={changed} empty="No objects changed" />
        <Arrow />
        <Stage title="Dependent objects" tone="medium" icon={<Database size={14} />} items={views} empty="No dependent views" />
        <Arrow />
        <Stage title="Downstream assets" tone="critical" icon={<LayoutDashboard size={14} />} items={assets} empty="None registered" />
      </div>
      {!a.graph.complete && <p className="mt-2 text-xs text-medium">Lineage is incomplete: more dependents may exist than are shown here.</p>}
    </div>
  );
}

/* ---------- Schema changes as add / remove / modify chips ---------- */
const CHANGE_META: Record<string, { Icon: typeof Plus; cls: string; label: string }> = {
  column_added: { Icon: Plus, cls: "text-ok border-ok/40 bg-ok/10", label: "added" },
  table_added: { Icon: Plus, cls: "text-ok border-ok/40 bg-ok/10", label: "added" },
  column_removed: { Icon: Minus, cls: "text-critical border-critical/40 bg-critical/10", label: "removed" },
  table_removed: { Icon: Minus, cls: "text-critical border-critical/40 bg-critical/10", label: "removed" },
};
const MODIFIED = { Icon: Pencil, cls: "text-medium border-medium/40 bg-medium/10", label: "modified" };

export function SchemaChips({ diff }: { diff: SchemaChange[] }) {
  if (!diff.length) return <p className="text-sm text-muted">No schema differences observed.</p>;
  return (
    <ul className="space-y-2">
      {diff.map((d, i) => {
        const m = CHANGE_META[d.change] ?? MODIFIED;
        const isView = d.change === "view_definition_changed";
        return (
          <li key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-bg p-2.5 text-sm">
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${m.cls}`}><m.Icon size={12} aria-hidden /> {m.label}</span>
            <span className="font-mono font-medium">{d.table}{d.column ? `.${d.column}` : ""}</span>
            {d.change === "type_changed" && (
              <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                <span className="rounded bg-surface px-1.5 py-0.5">{d.old}</span><ArrowRight size={12} aria-hidden /><span className="rounded bg-surface px-1.5 py-0.5">{d.new}</span>
                {d.compatibility && <span className={`rounded-full border px-2 py-0.5 font-sans ${d.compatibility === "widening" ? "border-ok/40 text-ok" : "border-high/40 text-high"}`}>{d.compatibility}</span>}
              </span>
            )}
            {d.change === "nullability_changed" && <span className="font-mono text-xs">{d.old} → {d.new}</span>}
            {(d.change === "column_added" || d.change === "column_removed") && d.type && <span className="font-mono text-xs text-muted">{d.type}</span>}
            {isView && <span className="text-xs text-muted">definition rewritten (see SQL tab)</span>}
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- Row counts: before/after paired bars ---------- */
export function RowCountBars({ rows }: { rows: TableComparison[] }) {
  const compared = rows.filter((r) => r.status === "compared" && r.rows_before != null);
  if (!compared.length) return <p className="text-sm text-muted">No comparison data available.</p>;
  const max = Math.max(1, ...compared.flatMap((r) => [r.rows_before ?? 0, r.rows_after ?? 0]));
  return (
    <ul className="space-y-3">
      {compared.map((r) => {
        const d = r.row_delta ?? 0;
        return (
          <li key={r.table} aria-label={`${r.table}: ${fmt(r.rows_before)} rows before, ${fmt(r.rows_after)} after`}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">{r.table}{r.kind === "view" && <span className="ml-1.5 text-xs text-muted">view</span>}</span>
              <span className={`tabular-nums text-xs ${d < 0 ? "font-semibold text-critical" : d > 0 ? "font-semibold text-medium" : "text-muted"}`}>
                {d ? `${d > 0 ? "▲ +" : "▼ "}${fmt(d)} (${pct(r.row_delta_pct)})` : "no change"}
              </span>
            </div>
            <div className="space-y-0.5">
              <div className="flex items-center gap-2"><span className="w-12 text-[11px] text-muted">before</span><div className="h-2 rounded-full bg-muted/50" style={{ width: `${Math.max(1, ((r.rows_before ?? 0) / max) * 100)}%` }} /><span className="text-[11px] tabular-nums text-muted">{fmt(r.rows_before)}</span></div>
              <div className="flex items-center gap-2"><span className="w-12 text-[11px] text-muted">after</span><div className={`h-2 rounded-full ${d < 0 ? "bg-critical" : d > 0 ? "bg-medium" : "bg-brand"}`} style={{ width: `${Math.max(1, ((r.rows_after ?? 0) / max) * 100)}%` }} /><span className="text-[11px] tabular-nums text-muted">{fmt(r.rows_after)}</span></div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- NULL-rate: before → after bar ---------- */
export function NullRateBars({ rows }: { rows: TableComparison[] }) {
  const items = rows.filter((r) => r.status === "compared").flatMap((r) => (r.columns ?? []).filter((c) => Math.abs(c.null_rate_delta) > 0.0005).map((c) => ({ ...c, table: r.table })));
  if (!items.length) return null;
  return (
    <div className="mt-5">
      <h4 className="mb-2 text-sm font-semibold">NULL rate changes</h4>
      <ul className="space-y-2.5">
        {items.map((c) => (
          <li key={c.table + c.column} aria-label={`${c.table}.${c.column} NULL rate ${(c.null_rate_before * 100).toFixed(1)}% to ${(c.null_rate_after * 100).toFixed(1)}%`}>
            <div className="mb-1 flex justify-between text-xs"><span className="font-mono">{c.table}.{c.column}</span><span className="tabular-nums text-muted">{(c.null_rate_before * 100).toFixed(1)}% → <b className={c.null_rate_delta > 0 ? "text-high" : "text-ok"}>{(c.null_rate_after * 100).toFixed(1)}%</b></span></div>
            <div className="relative h-2.5 overflow-hidden rounded-full bg-bg">
              <div className={`absolute inset-y-0 left-0 rounded-full ${c.null_rate_delta > 0 ? "bg-high/80" : "bg-ok/70"}`} style={{ width: `${Math.max(1, c.null_rate_after * 100)}%` }} />
              <div className="absolute inset-y-0 w-0.5 bg-fg" style={{ left: `${c.null_rate_before * 100}%` }} title="Before" />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-muted">Bar = after · black tick = before</p>
    </div>
  );
}

/* ---------- Metric drift: how far from "no change", against the tolerance band ---------- */
export function MetricDrift({ metrics }: { metrics: MetricRow[] }) {
  if (!metrics.length) return <p className="text-sm text-muted">No business metrics were selected for this analysis.</p>;
  return (
    <ul className="space-y-5">
      {metrics.map((m) => {
        const d = m.delta_pct ?? 0;
        const out = m.delta_pct != null && Math.abs(d) > m.tolerance_pct;
        const range = Math.max(m.tolerance_pct * 2, Math.abs(d) * 1.15, 1); // axis spans ±range, centred on "no change"
        const pos = (v: number) => 50 + (Math.max(-range, Math.min(range, v)) / range) * 50;
        return (
          <li key={m.name} aria-label={`${m.name}: ${m.error ?? pct(m.delta_pct, 2)}, tolerance ±${m.tolerance_pct}%, ${out ? "outside" : "within"} tolerance`}>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">{m.name}</span>
              <span className={`tabular-nums text-xs ${out ? "font-semibold text-high" : "text-muted"}`}>
                {m.error ?? `${out ? "⚠ " : "✓ "}${pct(m.delta_pct, 2)}`}
              </span>
            </div>
            <div className="relative h-4 rounded-full bg-bg">
              <div className="absolute inset-y-0 rounded-full bg-ok/20" style={{ left: `${pos(-m.tolerance_pct)}%`, width: `${pos(m.tolerance_pct) - pos(-m.tolerance_pct)}%` }} title={`Tolerance ±${m.tolerance_pct}%`} />
              <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
              {m.delta_pct != null && !m.error && (
                <>
                  <div className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full ${out ? "bg-high" : "bg-ok"}`} style={{ left: `${Math.min(50, pos(d))}%`, width: `${Math.abs(pos(d) - 50)}%` }} />
                  <div className={`absolute top-1/2 h-4 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-sm ${out ? "bg-high" : "bg-ok"}`} style={{ left: `${pos(d)}%` }} />
                </>
              )}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-muted">
              <span>{fmt(m.before, 2)} before</span><span>green band = allowed ±{m.tolerance_pct}%</span><span>{fmt(m.after, 2)} after</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------- Reconciliation: where did every record go? ---------- */
export function ReconBars({ items }: { items: Reconciliation[] }) {
  if (!items.length) return <p className="text-sm text-muted">No tables with a reliable comparison key.</p>;
  const seg = (r: Reconciliation) => {
    const matched = r.matched ?? 0, changed = r.changed_rows ?? 0;
    return [
      { k: "Unchanged", v: Math.max(0, matched - changed), cls: "bg-ok/70" },
      { k: "Values changed", v: Math.min(changed, matched), cls: "bg-medium" },
      { k: "Missing after change", v: r.missing_in_candidate ?? 0, cls: "bg-critical" },
      { k: "New", v: r.new_in_candidate ?? 0, cls: "bg-low" },
    ];
  };
  return (
    <div>
      <ul className="space-y-3.5">
        {items.map((r) => {
          const s = seg(r), total = s.reduce((n, x) => n + x.v, 0) || 1;
          return (
            <li key={r.table}>
              <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">{r.table} <span className="font-mono text-xs text-muted">key: {r.key.join(", ")}</span></span>
                {r.status === "compared" && s[2].v > 0 && <span className="text-xs font-semibold text-critical">{fmt(s[2].v)} missing</span>}
              </div>
              {r.status !== "compared" ? <p className="text-xs text-muted">Not compared: {r.reason}</p> : (
                <>
                  <div className="flex h-3 overflow-hidden rounded-full bg-bg" role="img" aria-label={s.map((x) => `${x.k}: ${fmt(x.v)}`).join(", ")}>
                    {s.filter((x) => x.v > 0).map((x) => <div key={x.k} className={x.cls} style={{ width: `${(x.v / total) * 100}%` }} title={`${x.k}: ${fmt(x.v)}`} />)}
                  </div>
                  {r.missing_examples && r.missing_examples.length > 0 && <p className="mt-1 text-xs text-muted">Example missing keys: {r.missing_examples.map((k) => k.join("/")).join(", ")}</p>}
                </>
              )}
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {[["bg-ok/70", "Unchanged"], ["bg-medium", "Values changed"], ["bg-critical", "Missing after change"], ["bg-low", "New"]].map(([c, l]) => (
          <span key={l} className="inline-flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-sm ${c}`} aria-hidden /> {l}</span>
        ))}
      </div>
    </div>
  );
}

/* ---------- Headline tiles: the 4 numbers a reviewer wants first ---------- */
export function StatTile({ value, label, tone = "fg" }: { value: ReactNode; label: string; tone?: "fg" | "critical" | "high" | "medium" | "ok" }) {
  const cls = { fg: "text-fg", critical: "text-critical", high: "text-high", medium: "text-medium", ok: "text-ok" }[tone];
  return (
    <div className="rounded-xl border border-line bg-bg px-3 py-2.5">
      <div className={`text-2xl font-semibold tabular-nums leading-none ${cls}`}>{value}</div>
      <div className="mt-1 text-xs text-muted">{label}</div>
    </div>
  );
}
