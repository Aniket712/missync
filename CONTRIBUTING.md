# Contributing to Missync

Thanks for helping! Bug reports, connector improvements, new checks, docs and UI polish are all welcome.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e "backend[dev,postgres,sample]"
cd frontend && npm install && cd ..
```

`./install.sh` (macOS/Linux) or `.\start.ps1` (Windows) does the same and starts the app at http://localhost:8000.

For UI work run the API (`missync serve --mode self-hosted`) and `npm run dev` in `frontend/` (port 5173, proxies `/api`).

## Before you open a pull request

```bash
cd backend && ruff check missync tests && pytest        # backend
cd frontend && npm run typecheck && npm test && npm run build   # frontend
```

- Live PostgreSQL tests run when `MISSYNC_TEST_PG_PORT` is set (the CI job does this; locally you can start the embedded sample database from the UI and point the variable at its port).
- Add a test for behaviour you change. Analysis checks need a test in `backend/tests` that shows both the finding and a case that must *not* produce it.
- Keep the honesty model: a finding is **verified** only when it was observed in the sandbox, otherwise it is **predicted**. State limitations rather than hiding them.
- `docker/postgres-init.sql` and `backend/missync/demo/postgres-init.sql` must stay identical (a test checks it).

## Project map

- `backend/missync/analysis/` — parsing, sandbox, profiling, reconciliation, lineage, severity rules
- `backend/missync/connectors/` — one class per source; new connectors implement `Connector` and register in `connectors/__init__.py` (include an allowed-parameter list)
- `backend/missync/api/` — FastAPI app and the background job manager
- `backend/missync/cli.py` — `missync serve` / `missync analyze`
- `frontend/src/` — React UI

## Reporting security issues

See [SECURITY.md](SECURITY.md); please don't use public issues for those.
