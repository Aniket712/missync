import clsx from "clsx";
import { AlertOctagon, AlertTriangle, CheckCircle2, Info, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { Severity } from "../api";

export const SEV: Record<Severity, { label: string; cls: string; Icon: typeof Info }> = {
  critical: { label: "Critical", cls: "text-critical border-critical/40 bg-critical/10", Icon: AlertOctagon },
  high: { label: "High", cls: "text-high border-high/40 bg-high/10", Icon: ShieldAlert },
  medium: { label: "Medium", cls: "text-medium border-medium/40 bg-medium/10", Icon: AlertTriangle },
  low: { label: "Low", cls: "text-low border-low/40 bg-low/10", Icon: Info },
  info: { label: "Info", cls: "text-muted border-line bg-bg", Icon: CheckCircle2 },
};

export function SeverityBadge({ s, count }: { s: Severity; count?: number }) {
  const { label, cls, Icon } = SEV[s];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold", cls)}>
      <Icon size={13} aria-hidden /> {count !== undefined ? `${count} ` : ""}
      {label}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "brand" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        tone === "ok" ? "text-ok border-ok/40 bg-ok/10" : tone === "brand" ? "text-brand border-brand/40 bg-brand/10" : "text-muted border-line",
      )}
    >
      {children}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card p-8 text-center text-sm text-muted">{children}</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-4 rounded-lg border border-critical/40 bg-critical/10 p-3 text-sm text-critical">
      {error}
    </div>
  );
}

export const fmt = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: digits });
export const pct = (n: number | null | undefined, digits = 1) => (n === null || n === undefined ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`);
export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
