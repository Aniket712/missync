import { Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../App";
import { api, type AnalysisListItem } from "../api";
import { Empty, ErrorBox, PageHeader, SeverityBadge, when } from "../components/ui";

const PAGE = 25;
const SEVERITIES = ["critical", "high", "medium", "low", "info"];

export default function HistoryPage() {
  const { config } = useApp();
  const [items, setItems] = useState<AnalysisListItem[] | null>(null);
  const [q, setQ] = useState("");
  const [severity, setSeverity] = useState("");
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  // Debounced search; any filter change restarts from the first page.
  useEffect(() => {
    const t = setTimeout(() => {
      api.analyses({ q: q.trim(), severity, limit: PAGE }).then((r) => { setItems(r); setMore(r.length === PAGE); setError(null); }).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [q, severity]);

  const loadMore = () =>
    api.analyses({ q: q.trim(), severity, limit: PAGE, offset: items?.length ?? 0 })
      .then((r) => { setItems([...(items ?? []), ...r]); setMore(r.length === PAGE); })
      .catch((e) => setError(e.message));

  const remove = async (id: string) => {
    setConfirm(null);
    try { await api.deleteAnalysis(id); setItems((items ?? []).filter((a) => a.id !== id)); } catch (e) { setError((e as Error).message); }
  };

  return (
    <div>
      <PageHeader title="Analysis history" subtitle="Every analysis is kept so you can revisit evidence and export reports." />
      <ErrorBox error={error} />
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="relative min-w-[14rem] flex-1">
          <Search size={14} className="absolute left-2.5 top-3 text-muted" />
          <input className="input !pl-8" placeholder="Search by title" aria-label="Search analyses" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <select className="input !w-auto" aria-label="Filter by severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
        </select>
      </div>
      {items === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <Empty>{q || severity ? "No analyses match these filters." : "No analyses yet. Run one from Analyze change."}</Empty>
      ) : (
        <>
          <ul className="card divide-y divide-line">
            {items.map((a) => (
              <li key={a.id} className="flex items-center gap-2 pr-3 hover:bg-bg">
                <Link to={`/analyses/${a.id}`} className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2 p-4">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{a.title}</div>
                    <div className="text-xs text-muted">{when(a.created_at)} · {a.finding_count} finding{a.finding_count === 1 ? "" : "s"}</div>
                  </div>
                  <SeverityBadge s={a.severity} />
                </Link>
                {!config?.demo && (confirm === a.id ? (
                  <button className="btn text-critical" onClick={() => remove(a.id)}>Confirm</button>
                ) : (
                  <button className="btn" aria-label={`Delete ${a.title}`} onClick={() => setConfirm(a.id)}><Trash2 size={15} /></button>
                ))}
              </li>
            ))}
          </ul>
          {more && <button className="btn mx-auto mt-4" onClick={loadMore}>Load more</button>}
        </>
      )}
    </div>
  );
}
