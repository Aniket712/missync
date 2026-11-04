import { Database, FileSearch, GitCompare, History, LayoutDashboard, Moon, Sun } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { api, getToken, setToken, type AppConfig, type Connection } from "./api";
import Analyze from "./pages/Analyze";
import AnalysisPage from "./pages/AnalysisPage";
import Baselines from "./pages/Baselines";
import Connections from "./pages/Connections";
import HistoryPage from "./pages/History";
import Overview from "./pages/Overview";

interface Ctx {
  config: AppConfig | null;
  connections: Connection[];
  connectionId: string;
  setConnectionId: (id: string) => void;
  reload: () => void;
}
const AppCtx = createContext<Ctx>({ config: null, connections: [], connectionId: "demo", setConnectionId: () => {}, reload: () => {} });
export const useApp = () => useContext(AppCtx);

const NAV = [
  { to: "/", label: "Overview", Icon: LayoutDashboard, end: true },
  { to: "/connections", label: "Connections", Icon: Database },
  { to: "/analyze", label: "Analyze change", Icon: FileSearch },
  { to: "/baselines", label: "Baselines", Icon: GitCompare },
  { to: "/history", label: "History", Icon: History },
];

function Logo() {
  return (
    <div className="flex items-center gap-2 font-semibold">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="rgb(var(--brand))" />
        <path d="M8 22V10l8 8 8-8v12" stroke="rgb(var(--on-brand))" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Missync
    </div>
  );
}

function TokenGate({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setToken(value.trim());
    try {
      await api.config();
      onDone();
    } catch {
      setToken("");
      setError("That token was not accepted.");
    }
  };
  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <form onSubmit={submit} className="card space-y-3 p-6">
        <Logo />
        <h1 className="text-lg font-semibold">Access token required</h1>
        <p className="text-sm text-muted">This Missync server is protected. Enter the value of <code>MISSYNC_API_TOKEN</code> that was set when it was started.</p>
        {error && <div role="alert" className="text-sm text-critical">{error}</div>}
        <input className="input" type="password" autoComplete="off" autoFocus aria-label="Access token" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn btn-primary w-full" disabled={!value.trim()}>Continue</button>
      </form>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState(() => {
    try { return localStorage.getItem("missync.connection") || "demo"; } catch { return "demo"; }
  });
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem("missync.theme");
      if (saved) return saved === "dark";
    } catch { /* storage unavailable */ }
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
  });
  const [apiError, setApiError] = useState<string | null>(null);
  const [needsToken, setNeedsToken] = useState(false);

  const reload = () => {
    setApiError(null);
    api.config().then(setConfig).catch((e) => setApiError(e.message));
    api.connections().then(setConnections).catch((e) => setApiError(e.message));
  };
  useEffect(() => {
    const onUnauthorized = () => setNeedsToken(true);
    window.addEventListener("missync:unauthorized", onUnauthorized);
    api.health().then((h) => { if (h.auth_required && !getToken()) setNeedsToken(true); else reload(); }).catch(() => reload());
    return () => window.removeEventListener("missync:unauthorized", onUnauthorized);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    try { localStorage.setItem("missync.theme", next ? "dark" : "light"); } catch { /* storage unavailable */ }
  };
  useEffect(() => {
    try { localStorage.setItem("missync.connection", connectionId); } catch { /* storage unavailable */ }
  }, [connectionId]);

  if (needsToken) return <TokenGate onDone={() => { setNeedsToken(false); reload(); }} />;

  const selected = connections.find((c) => c.id === connectionId) ? connectionId : connections[0]?.id ?? "demo";

  return (
    <AppCtx.Provider value={{ config, connections, connectionId: selected, setConnectionId, reload }}>
      <BrowserRouter>
        <a href="#main" className="btn btn-primary sr-only z-50 focus:not-sr-only focus:fixed focus:left-2 focus:top-2">Skip to content</a>
        <div className="min-h-screen md:flex">
          <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r">
            <div className="flex items-center justify-between px-4 py-3 md:block md:py-5">
              <Logo />
              <button className="btn px-2 py-1.5 md:hidden" onClick={toggleTheme} aria-label="Toggle theme">
                {dark ? <Sun size={15} /> : <Moon size={15} />}
              </button>
              <p className="mt-1 hidden text-xs text-muted md:block">Catch data changes before they break what depends on them.</p>
            </div>
            <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0" aria-label="Main">
              {NAV.map(({ to, label, Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-brand/10 text-brand" : "text-muted hover:bg-bg hover:text-fg"}`
                  }
                >
                  <Icon size={16} aria-hidden /> {label}
                </NavLink>
              ))}
            </nav>
            <div className="hidden space-y-3 p-4 md:absolute md:bottom-0 md:block md:w-60">
              {config?.demo && <p className="rounded-lg bg-brand/10 p-2 text-xs text-brand">Public demo: synthetic data only. Self-host to connect your own databases.</p>}
              <button className="btn w-full" onClick={toggleTheme} aria-label="Toggle theme">
                {dark ? <Sun size={15} /> : <Moon size={15} />} {dark ? "Light" : "Dark"} mode
              </button>
            </div>
          </aside>
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 outline-none md:px-8">
            {apiError && <div role="alert" className="mb-4 rounded-lg border border-critical/40 bg-critical/10 p-3 text-sm text-critical">Cannot reach the Missync API: {apiError}</div>}
            <div className="mx-auto max-w-5xl">
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/connections" element={<Connections />} />
                <Route path="/analyze" element={<Analyze />} />
                <Route path="/baselines" element={<Baselines />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/analyses/:id" element={<AnalysisPage />} />
              </Routes>
            </div>
          </main>
        </div>
      </BrowserRouter>
    </AppCtx.Provider>
  );
}
