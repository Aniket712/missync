import type { Table } from "../api";

/** Parses postgresql://user:pass@host:port/db?sslmode=... into form values; null when it is not a Postgres URL. */
export function parsePgUrl(raw: string): Record<string, string> | null {
  try {
    const u = new URL(raw.trim());
    if (!/^postgres(ql)?:$/.test(u.protocol)) return null;
    const out: Record<string, string> = {};
    if (u.hostname) out.host = u.hostname;
    if (u.port) out.port = u.port;
    if (u.username) out.user = decodeURIComponent(u.username);
    if (u.password) out.password = decodeURIComponent(u.password);
    if (u.pathname.length > 1) out.database = decodeURIComponent(u.pathname.slice(1));
    const ssl = u.searchParams.get("sslmode");
    if (ssl) out.sslmode = ssl;
    return out;
  } catch {
    return null;
  }
}

export interface Suggestion { label: string; sql: string }

/** Starter changes built from a discovered schema, so a fresh connection can be analyzed without writing SQL. */
export function suggestChanges(tables: Table[]): Suggestion[] {
  const base = tables.filter((t) => t.kind === "table" && t.columns.length > 1);
  const out: Suggestion[] = [];
  const t = base[0];
  if (t) {
    const col = t.columns.find((c) => !c.primary_key) ?? t.columns[0];
    out.push({ label: `Drop ${t.name}.${col.name}`, sql: `ALTER TABLE ${t.name} DROP COLUMN ${col.name};` });
    const pk = t.columns.find((c) => c.primary_key) ?? t.columns[0];
    out.push({ label: `Delete some ${t.name} rows`, sql: `DELETE FROM ${t.name} WHERE ${pk.name} % 4 = 0;` });
  }
  const text = base.flatMap((x) => x.columns.filter((c) => /char|text/i.test(c.type)).map((c) => ({ t: x.name, c: c.name })))[0];
  if (text) out.push({ label: `Null out ${text.t}.${text.c}`, sql: `UPDATE ${text.t} SET ${text.c} = NULL;` });
  return out;
}
