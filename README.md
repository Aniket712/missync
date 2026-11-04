# Missync

**Catch data changes before they break what depends on them.**

[![CI](https://github.com/Aniket712/missync/actions/workflows/ci.yml/badge.svg)](https://github.com/Aniket712/missync/actions/workflows/ci.yml) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Missync analyzes a proposed SQL change, maps what depends on the objects it touches, applies the change to a throw-away copy of your data (never to the source), compares before/after, and produces an evidence-based report (JSON + HTML).

- Static analysis (SQLGlot): added/removed/retyped columns, drops, unfiltered `UPDATE`/`DELETE`.
- Impact: column-level lineage from accessible view definitions plus registered downstream assets; incomplete lineage is labelled.
- Validation: row counts, NULL rates, duplicate keys, record-level reconciliation (only on keys unique in the baseline), user-selected metrics with tolerances.
- Findings are marked **verified** (measured) or **predicted** (static), with confidence, limitations and "may be intended" where a difference is not necessarily a defect. No numeric risk scores and no safety guarantees.
- Baselines: capture schema signature + profile, compare to current state or another baseline.
- **Visual results**: a blast-radius flow, severity bar, metric-drift gauges, record-flow bars and an impact graph, so a reviewer sees the damage in seconds (see [Reading the results](#reading-the-results)).

**Demo video (about 44 s):** [docs/media/missync-demo.mp4](docs/media/missync-demo.mp4): launch the sample database, run a column type change, and watch it ripple through 3 views and 4 downstream assets (blast radius, record check, impact graph).

## Quick start

```bash
git clone https://github.com/Aniket712/missync.git && cd missync
```

**Windows:** `.\start.ps1`  ·  **macOS/Linux:** `./install.sh`  ·  then open http://localhost:8000. Both do the one-time setup (virtualenv, PostgreSQL driver, built UI) and start Missync in self-hosted mode, so you can add connections from the UI.

**Command line / CI:** `missync analyze --sql change.sql --postgres-url ... --fail-on high` (see [CI guide](docs/CI.md)).

Below are the manual steps and the public-demo variant (no credentials).

## Manual setup (demo, no credentials)

Requires Python 3.11+ and Node 18+. Run these from the repository root. Pick the block for your shell.

**Easiest on Windows:** run `.\start.ps1` from the repo root. It does the one-time setup on the first run and just starts the app afterwards (if blocked: `powershell -ExecutionPolicy Bypass -File .\start.ps1`). Setup is only needed once; afterwards you only need `python -m missync` inside the activated environment.

**Windows PowerShell**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -e "backend[dev]"
cd frontend; npm install; npm run build; cd ..
python -m missync
```

**Windows cmd**
```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -e "backend[dev]"
cd frontend && npm install && npm run build && cd ..
python -m missync
```

**macOS / Linux / Git Bash**
```bash
python -m venv .venv && source .venv/bin/activate      # Git Bash on Windows: source .venv/Scripts/activate
pip install -e "backend[dev]"
(cd frontend && npm install && npm run build)
python -m missync
```

Then open http://localhost:8000 and run one of the four sample scenarios (type change, missing records, metric drift, data-quality regression).

Options: `python -m missync serve --port 8080 --data-dir ./mydata --mode self-hosted` (`missync` is also installed as a command). You can also use `uvicorn missync.api.app:app` from the `backend/` folder; set `MISSYNC_DATA_DIR` as an environment variable in your shell's own syntax (`$env:MISSYNC_DATA_DIR="../data"` in PowerShell, `set MISSYNC_DATA_DIR=../data` in cmd).

The UI is served only after `npm run build`; without it the API still works at `/api/*` and `/docs`. For UI development use `npm run dev` in `frontend/` (port 5173, proxies `/api` to port 8000).

**Troubleshooting**
- `. .venv/bin/activate` fails on Windows: the folder is `Scripts`, not `bin` (see above).
- `VAR=value command` is Bash-only; use `python -m missync --data-dir ...` or your shell's syntax.
- `&&` does not work in Windows PowerShell 5.1; use `;` or run the lines separately.
- `uvicorn` not found: activate the virtual environment first, or use `python -m missync`.
- Blank page at `/`: run `npm run build` in `frontend/`.
- Port in use: `python -m missync --port 8001`.

## Demo script: connect PostgreSQL entirely from the UI (Windows, no Docker)

`.\start.ps1` starts Missync in self-hosted mode (connections enabled) and installs the PostgreSQL driver and the embedded sample database. Existing `.venv`? Run `.venv\Scripts\pip install -e "backend[postgres,sample]"` once, and `npm run build` in `frontend/` if you changed the UI.

1. Open http://localhost:8000 → **Connections**.
2. Pick **PostgreSQL**, then **Launch sample database** (or fill the form / paste a `postgresql://…` URL for your own server). The form is filled and tested for you.
3. **Test connection** shows server version, latency and object count; **Save connection** unlocks after a pass.
4. Browse the schema, search, and **Preview rows** on any table. Use the refresh icon on a connection to re-test it. If the sample database was stopped (for example after restarting Missync), a failed re-test shows **Relaunch it**.
5. **Analyze a change**: pick a suggested change (or a sample scenario) and run it. It is applied only to a sandbox copy.

The sample database uses trust authentication on 127.0.0.1 only, so any password works there; it is for demos, not for real data.

**Platform note:** the one-click sample database works on Windows. On Linux and macOS the embedded PostgreSQL only offers a Unix socket, so the button reports that and you should use the Docker route below (`docker compose up`) for the same sample data.

## Reading the results

Take the bundled **type-change** scenario on the sample PostgreSQL database: `ALTER TABLE orders ALTER COLUMN amount TYPE INTEGER;`, a one-line change that looks harmless. It runs only on a throw-away copy, then Missync compares before and after and follows the dependencies.

| What you see | Meaning in this example |
|---|---|
| **Tiles + severity bar** | 2 findings (1 critical, 1 high), both *verified*: measured on the copy, not guessed. |
| **Blast radius**: *Your change* | One `ALTER` statement. |
| *Directly changed* | `orders`, the one table the SQL touches. |
| *Dependent objects* | The 3 views built on it: `v_daily_revenue`, `v_order_details`, `v_customer_ltv`. They are not edited, but their results now depend on a changed column. |
| *Downstream assets* | The 4 registered consumers that read those objects: Revenue Dashboard, Finance Monthly Export, Churn Model Features, Customer Support Console. Consumers you did not register are invisible to Missync. |
| **Metric drift** | Total completed revenue moves by about -0.01% against an allowed +/-1% (the green zone). The headline number looks fine. |
| **Where did the records go?** | ...yet the bar for `orders` is fully amber: all 5,000 rows have a changed `amount`. This is the point of record-level checks: a total can hide widespread damage. |
| **Impact graph** | The same story as a map: arrows run from `orders` to the views and from the views to the dashboards, exports, models and services that depend on them; dashed arrows mark links Missync could not resolve. |

In one line: a "small" type change quietly alters every order amount and reaches 3 views and 4 downstream assets, even though the revenue total looks normal.

The **missing-records** scenario (a cleanup `DELETE` that removes 25% of customers) is a second example: there the damage shows as missing rows, a red segment in the record-flow bar, and a large metric drift.

Verdicts are labelled *verified* or *predicted* and never as a guarantee of safety. Limits are listed under [Status](#status-what-is-and-isnt-verified).

## Security and deployment

- Missync listens on `127.0.0.1` by default. In self-hosted mode it **refuses to listen on any other address** unless `MISSYNC_API_TOKEN` is set; every `/api` call then needs `Authorization: Bearer <token>` (the UI asks for it once).
- There are no user accounts or roles: whoever holds the token can use every saved connection. Put TLS (a reverse proxy) in front before exposing it beyond your machine or network. Details and the threat model are in [SECURITY.md](SECURITY.md).
- Analyses run on a bounded worker pool (`MISSYNC_MAX_CONCURRENT_ANALYSES`, default 2) with an overall deadline (`MISSYNC_ANALYSIS_DEADLINE_S`, default 600) and can be cancelled from the UI. History keeps the newest `MISSYNC_HISTORY_LIMIT` analyses (default 500).
- Back up the `data/` directory, **including `data/.secret_key`**: without it stored connection secrets cannot be decrypted. The metadata database migrates itself on startup.
- `GET /api/health` (liveness) and `GET /api/ready` (store and data directory checks) are unauthenticated for probes.

## Self-hosted with PostgreSQL sample data (Docker)

```bash
cp .env.example .env
docker compose up --build        # Missync on :8000, sample Postgres on 127.0.0.1:5433
```

In **Connections** add PostgreSQL: host `postgres`, database `shop`, user `missync_ro`, password `missync_ro_dev_only`. Set `MISSYNC_MODE=demo` to deploy a public instance that exposes only the bundled synthetic data.

Optional connector deps: `pip install -e "backend[postgres,bigquery,snowflake,files]"`.

## Tests

```bash
cd backend && pytest        # ~95 tests; 3 more run against a live PostgreSQL when MISSYNC_TEST_PG_PORT is set
cd frontend && npm run typecheck && npm test && npm run build
cd frontend && npx playwright install chromium && npm run e2e                  # browser walkthrough (server on :8000)
# add E2E_CONNECT=1 on Windows to include the sample-database flow (needs a self-hosted server with the `sample` extra)
```

## Status: what is and isn't verified

| Area | Status |
|---|---|
| Analysis engine, SQLite/DuckDB/CSV/Parquet connectors, API, reports, security helpers, CLI, jobs, auth, store migration | Tested (automated, real databases/files) |
| Four demo scenarios | Tested against ground truth computed independently from the source data, on SQLite **and** a live PostgreSQL 16 |
| PostgreSQL connector + `docker/postgres-init.sql` | Tested against a real PostgreSQL 16.2 (embedded via `pgserver`, not Docker): discovery, view definitions, numeric precision, writes rejected, scenarios, source untouched |
| Visual results (blast radius, drift, record-flow, row-count and NULL-rate charts, impact graph legend) and the sample-database progress/relaunch UI | Type-checked, built, the frontend unit tests pass, and every result tab was viewed in headless Chromium (Playwright screenshots, including the demo video recording) on the four scenarios. The Playwright walkthrough `frontend/e2e.mjs` has **not** been re-run since these UI changes; the Relaunch button has not been exercised against a stopped sample server |
| UI, including the sample-database connection flow | Walked through in headless Chromium (Playwright) at desktop-light and phone-dark on Windows: every page, result tabs, downloads, baselines, history search, sample database start/test/save/browse/preview and an analysis started with Ctrl+Enter; no console or network errors |
| Installed (non-editable) package serves the UI and CLI | Checked in a fresh virtualenv on Windows |
| `Dockerfile`, `docker-compose.yml` | **Not run** - Docker is not available where this was built (the CI workflow builds and smoke-tests the image) |
| GitHub workflows (`.github/`) and `action.yml` | **Never executed** - written but not yet run on GitHub; expect to fix small issues on the first run |
| macOS/Linux launcher (`install.sh`) | **Not run**. The first CI run showed the one-click sample database cannot work there (Unix socket only, see the platform note); use Docker Compose for the sample data |
| BigQuery, Snowflake | Fake client/connection tests only; never run against live services (no accounts); static analysis only |

Known limits: the sandbox is DuckDB (constraints, triggers, indexes and engine-specific semantics are not reproduced); big tables are sampled; unregistered consumers (BI tools, ad-hoc queries) are invisible; baseline-to-baseline row-count changes may be normal growth.

Docs: [architecture](docs/ARCHITECTURE.md) · [connector matrix](docs/CONNECTORS.md) · [CLI and CI](docs/CI.md) · [security](SECURITY.md) · [contributing](CONTRIBUTING.md) · [changelog](CHANGELOG.md). License: Apache-2.0.
