import { ArrowRight, CheckCircle2, Circle, Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApp } from "../App";
import { api, type AnalysisListItem, type Scenario } from "../api";
import { Empty, ErrorBox, PageHeader, SeverityBadge, when } from "../components/ui";

function GettingStarted({ connected, analyzed }: { connected: boolean; analyzed: boolean }) {
  const steps = [
    { done: connected, label: "Connect a database", hint: "Use the built-in sample PostgreSQL or your own, all from the UI.", to: "/connections", cta: "Add connection" },
    { done: connected && analyzed, label: "Analyze a change", hint: "Pick a suggested change or paste a migration; it runs on a throw-away copy.", to: "/analyze", cta: "Analyze" },
    { done: false, label: "Review the evidence", hint: "Open the report, see what it would break, export HTML or JSON.", to: "/history", cta: "History" },
  ];
  return (
    <section className="card mb-8 p-5" aria-labelledby="start">
      <h2 id="start" className="mb-3 text-lg font-semibold">Getting started</h2>
      <ol className="grid gap-3 sm:grid-cols-3">
        {steps.map((st, i) => (
          <li key={st.label} className="flex flex-col rounded-lg border border-line p-3">
            <div className="flex items-center gap-2 font-medium">
              {st.done ? <CheckCircle2 size={16} className="text-ok" aria-label="done" /> : <Circle size={16} className="text-muted" aria-hidden />} {i + 1}. {st.label}
            </div>
            <p className="mt-1 flex-1 text-sm text-muted">{st.hint}</p>
            <Link to={st.to} className="btn mt-3 self-start">{st.cta} <ArrowRight size={14} /></Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Overview() {
  const { config, connections } = useApp();
  const [items, setItems] = useState<AnalysisListItem[] | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();
  const connected = connections.some((c) => !c.builtin);

  useEffect(() => {
    api.analyses({ limit: 6 }).then(setItems).catch((e) => setError(e.message));
    api.scenarios().then(setScenarios).catch(() => setScenarios([]));
  }, []);

  const run = async (id: string) => {
    setRunning(id);
    setError(null);
    try {
      const a = await api.runScenario(id);
      nav(`/analyses/${a.id}`);
    } catch (e) {
      setError((e as Error).message);
      setRunning(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Propose a SQL change, see what it would break, and get evidence — before it reaches production."
        actions={<Link to="/analyze" className="btn btn-primary">Analyze a change <ArrowRight size={15} /></Link>}
      />
      <ErrorBox error={error} />

      {!config?.demo && !connected && <GettingStarted connected={connected} analyzed={(items?.length ?? 0) > 0} />}

      <section className="mb-8" aria-labelledby="scn">
          <h2 id="scn" className="mb-1 text-lg font-semibold">Try a sample scenario</h2>
          <p className="mb-3 text-sm text-muted">Each runs the real analysis engine against a synthetic shop database, in a throw-away copy.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {scenarios.map((s) => (
              <div key={s.id} className="card flex flex-col p-4">
                <h3 className="font-semibold">{s.title}</h3>
                <p className="mt-1 flex-1 text-sm text-muted">{s.description}</p>
                <button className="btn mt-3 self-start" disabled={running !== null} onClick={() => run(s.id)}>
                  {running === s.id ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />} {running === s.id ? "Analyzing…" : "Run analysis"}
                </button>
              </div>
            ))}
          </div>
        </section>

      <section aria-labelledby="recent">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="recent" className="text-lg font-semibold">Recent analyses</h2>
          <Link to="/history" className="text-sm text-brand">View all</Link>
        </div>
        {items === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : items.length === 0 ? (
          <Empty>No analyses yet. Run a sample scenario above to see what a report looks like.</Empty>
        ) : (
          <ul className="card divide-y divide-line">
            {items.map((a) => (
              <li key={a.id}>
                <Link to={`/analyses/${a.id}`} className="flex flex-wrap items-center justify-between gap-2 p-4 hover:bg-bg">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{a.title}</div>
                    <div className="text-xs text-muted">{when(a.created_at)} · {a.finding_count} finding{a.finding_count === 1 ? "" : "s"}</div>
                  </div>
                  <SeverityBadge s={a.severity} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
