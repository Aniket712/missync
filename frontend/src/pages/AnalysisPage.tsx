import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Analysis } from "../api";
import Result from "../components/Result";
import { ErrorBox } from "../components/ui";

export default function AnalysisPage() {
  const { id = "" } = useParams();
  const [a, setA] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.analysis(id).then(setA).catch((e) => setError(e.message));
  }, [id]);
  return (
    <div>
      <Link to="/history" className="mb-4 inline-block text-sm text-muted hover:text-fg">← All analyses</Link>
      <ErrorBox error={error} />
      {!a && !error && <p className="text-sm text-muted">Loading…</p>}
      {a && <Result a={a} />}
    </div>
  );
}
