# Architecture

```
React/Vite UI ──► FastAPI (api/app.py)             missync CLI (cli.py) ──┐
                   ├─ guard middleware   request id, body cap, bearer token, security headers
                   ├─ api/jobs.py        worker pool: progress, cancel, deadline
                   ├─ connectors/   read-only discovery + bounded row fetch
                   ├─ analysis/                                           │
                   │   sql_parser   SQLGlot: classify statements, structural changes (static only)
                   │   lineage      view definitions → table/column graph + registered assets
                   │   sandbox      in-memory DuckDB: schema `base` (copy) and `cand` (proposal applied)
                   │   schema_diff / profiling / reconcile / severity
                   │   engine       orchestrates and produces Findings  ◄───┘ (the CLI calls it directly)
                   │   baselines    capture + compare stored states
                   ├─ store/        SQLite metadata: WAL, versioned migrations
                   │                (connections encrypted, assets, baselines, analyses)
                   ├─ demo/         bundled synthetic DB, scenarios, embedded sample PostgreSQL
                   └─ reports/      JSON + HTML (Jinja2 autoescape)
```

## Frontend result visuals
`frontend/src/components/viz.tsx` holds dependency-free chart components (SVG-less, plain divs sized from data): `SeverityBar`, `BlastRadius`, `SchemaChips`, `RowCountBars`, `NullRateBars`, `MetricDrift`, `ReconBars`, `StatTile`. `components/Result.tsx` composes them from the existing `Analysis` payload: no API change, all values come from `summary`, `graph`, `schema_diff`, `table_comparison`, `metric_comparison` and `reconciliation`. `ImpactGraph.tsx` (React Flow, lazy-loaded) draws the lineage. Conventions: each chart exposes a text equivalent via `aria-label`, severity is never colour-only (icon + label), and the original tables stay available behind "Show as table".

Blast-radius stages are derived from graph nodes: `changed` nodes → *Directly changed* (this includes views whose data changed because a table under them changed); `impacted` non-asset nodes → *Dependent objects*; `type == "asset"` → *Downstream assets*.

## Analysis flow
1. Parse the proposal (never executed on the source). Classify statements and structural changes.
2. Discover the source schema (read-only) and build lineage from accessible view SQL; registered assets are added as nodes.
3. If the connector supports it, copy a bounded sample of each table into a DuckDB sandbox, profile it (`base`), clone to `cand`, apply the transpiled statements to `cand`, then profile and diff.
4. Reconcile row-by-row on a key only if the key is unique in the baseline. Evaluate selected metrics on both sides.
5. Emit findings: `verified` (measured in the sandbox) or `predicted` (static only), each with confidence + reason, limitations, a "may be intended" flag, and a rule-based severity (see `severity.py`; no numeric scores).

`run_analysis(connector, request, assets, progress)` reports `(stage, percent)` between these steps. The `progress` callback may raise to cancel the run; this is how the job manager implements cancel and the overall deadline.

## Jobs
`POST /api/jobs` queues an analysis on a `ThreadPoolExecutor` sized by `MISSYNC_MAX_CONCURRENT_ANALYSES` (default 2). `GET /api/jobs/{id}` returns `{status, stage, percent, result_id, error}`; `DELETE /api/jobs/{id}` requests cancellation, honoured at the next step boundary. A run longer than `MISSYNC_ANALYSIS_DEADLINE_S` (default 600) is stopped. Jobs are in memory (lost on restart; finished analyses are in the metadata store). `POST /api/analyses` and scenario runs wait on the same pool, so the concurrency limit applies to every entry point.

## Metadata store
SQLite through SQLAlchemy with WAL and a busy timeout. `schema_version` records applied migrations; `store/db.py` holds an append-only `MIGRATIONS` list that runs at startup (never edit a shipped migration; add a new one). History is pruned to `MISSYNC_HISTORY_LIMIT` analyses, and list queries read a small `summary` column instead of parsing full results.

## Design decisions and trade-offs
- **DuckDB as the universal sandbox** instead of a staging clone of each database: works without cloud/DB write privileges and is isolated by construction (in-memory, `enable_external_access=false`, `lock_configuration=true`). Trade-off: proposals are transpiled by SQLGlot to DuckDB, so dialect-specific behaviour (and constraints/indexes/triggers, which are not copied) can differ from the real engine; this is stated in findings. Large tables are sampled (`MISSYNC_SAMPLE_LIMIT`) and results are labelled lower-confidence.
- **Cloud warehouses are static-analysis only** (no sandbox copy): copying warehouse data is slow and costly. BigQuery's `dry_run()` helper exists but is not wired into the pipeline.
- **Lineage is only what is visible**: view definitions and registered assets. Missing/unparsable definitions mark lineage incomplete; the UI and reports say so.
- **Demo vs self-hosted**: `MISSYNC_MODE=demo` exposes only the bundled synthetic database through the same engine; creating connections is refused server-side. The launchers (`start.ps1`, `install.sh`) choose self-hosted for local use.
- **Estimated row counts on PostgreSQL**: discovery reads planner statistics (`pg_class.reltuples`) instead of running `count(*)` on every table on every call; the UI marks them `~`. The sandbox copy is counted exactly.
- **UI served from the package**: the build is bundled as `missync/_static` in the wheel; lookup order is `MISSYNC_FRONTEND_DIST`, the bundled copy, then `frontend/dist` in a checkout.

## Security notes
Secrets encrypted with Fernet at rest and masked in responses/logs; the key file is created atomically. Host validation blocks link-local/metadata/reserved ranges (optional private block and allowlist) and the connection is made to the validated IP (DNS-rebinding guard). Connector parameters are whitelisted per type and `sslmode`/schema/port are validated. File paths are confined to the data dir; metric queries must be a single SELECT; identifiers quoted and values bound; SQL size, request-body size, statement timeout, sample limit, worker pool and analysis deadline bound resource use. Optional bearer-token auth (`MISSYNC_API_TOKEN`) is required to listen on a non-local address in self-hosted mode. HTML reports escape all content and are served with a restrictive CSP. See `SECURITY.md` for the threat model and what is not covered (no user accounts or per-user isolation).
