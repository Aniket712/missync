import { Camera, GitCompare, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useApp } from "../App";
import { api, type BaselineCompare, type BaselineItem } from "../api";
import { FindingCard, TableComparisonView } from "../components/Result";
import { Empty, ErrorBox, PageHeader, Pill, when } from "../components/ui";

export default function Baselines() {
  const { connectionId } = useApp();
  const [items, setItems] = useState<BaselineItem[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cmp, setCmp] = useState<BaselineCompare | null>(null);
  const [against, setAgainst] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api.baselines(connectionId).then(setItems).catch((e) => setError(e.message));
  }, [connectionId]);
  useEffect(load, [load]);

  const guard = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <div>
      <PageHeader title="Baselines" subtitle="Capture schema signatures and profiling statistics, then compare any later state against them. Differences are evidence to review, not automatically defects." />
      <ErrorBox error={error} />
      <div className="card mb-5 flex flex-wrap items-end gap-3 p-4">
        <label className="min-w-0 flex-1 text-sm font-medium">Baseline name
          <input className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Before Q3 migration" />
        </label>
        <button className="btn btn-primary" disabled={busy !== null} onClick={() => guard("capture", async () => { await api.captureBaseline(connectionId, name || `Baseline ${new Date().toLocaleString()}`); setName(""); load(); })}>
          <Camera size={15} /> {busy === "capture" ? "Capturing…" : "Capture baseline"}
        </button>
      </div>

      {items.length === 0 ? <Empty>No baselines for this connection yet.</Empty> : (
        <ul className="card mb-6 divide-y divide-line">
          {items.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <div className="font-medium">{b.name}</div>
                <div className="flex flex-wrap gap-2 text-xs text-muted">{when(b.created_at)} · {b.tables} objects <Pill>{b.has_profile ? "schema + profile" : "schema only"}</Pill> <span className="font-mono">{b.signature.slice(0, 8)}</span></div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select className="input w-auto py-1.5" aria-label="Compare against" value={against[b.id] ?? "current"} onChange={(e) => setAgainst({ ...against, [b.id]: e.target.value })}>
                  <option value="current">current state</option>
                  {items.filter((o) => o.id !== b.id).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                <button className="btn" disabled={busy !== null} onClick={() => guard(b.id, async () => setCmp(await api.compareBaseline(b.id, against[b.id] ?? "current")))}>
                  <GitCompare size={15} /> {busy === b.id ? "Comparing…" : "Compare"}
                </button>
                <button className="btn" aria-label={`Delete ${b.name}`} onClick={() => guard("del", async () => { await api.deleteBaseline(b.id); setCmp(null); load(); })}><Trash2 size={15} /></button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {cmp && (
        <section aria-live="polite">
          <h2 className="mb-1 text-lg font-semibold">{cmp.from.name} → {cmp.to.name}</h2>
          <p className="mb-3 text-sm text-muted">{cmp.schema_changed ? "The schema signature changed." : "The schema signature is identical."} {cmp.schema_diff.length} structural difference{cmp.schema_diff.length === 1 ? "" : "s"}.</p>
          <div className="space-y-3">
            {cmp.findings.length === 0 && <Empty>No notable differences between these states.</Empty>}
            {cmp.findings.map((f) => <FindingCard key={f.id} f={f} />)}
          </div>
          {cmp.table_comparison.length > 0 && <div className="card mt-4 p-4"><h3 className="mb-2 font-semibold">Row counts &amp; NULL rates</h3><TableComparisonView rows={cmp.table_comparison} /></div>}
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">{cmp.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
