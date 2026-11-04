# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/); while it is below 1.0, minor releases may include breaking changes.

## [Unreleased]

### Added
- **Visual results** (`frontend/src/components/viz.tsx`): headline tiles, a stacked severity bar and a **blast-radius flow** (your change → changed objects → dependent objects → downstream assets); schema changes as add/remove/modify chips; metric drift drawn against its tolerance band; a "where did the records go?" bar per table (unchanged / values changed / missing / new); before/after row-count bars; NULL-rate bars. Every chart has a text equivalent (`aria-label`) and never relies on colour alone; the original tables remain under "Show as table".
- Impact graph legend (changed / impacted / related / unresolved link) and vertically centred columns.
- Launch-sample-database progress steps, and a **Relaunch** button on a saved sample connection whose embedded server has stopped.
- A 44-second demo video, `docs/media/missync-demo.mp4`, linked from the README. It follows a column type change through 3 dependent views to 4 downstream assets.
- UI-driven PostgreSQL setup: guided connector picker, connection-URL paste, **Launch sample database** (embedded PostgreSQL, no Docker), stateless **Test connection**, friendly errors, row preview, schema search, re-test and confirmed delete.
- Background analysis jobs (`/api/jobs`) with stage/percent progress and cancel; bounded concurrency and an overall deadline.
- `missync analyze` CLI for CI gates (`--fail-on`, `--dir` migration folders, JSON/HTML reports) and a composite GitHub Action (`action.yml`).
- Optional bearer-token auth (`MISSYNC_API_TOKEN`); the server refuses an unauthenticated non-local bind in self-hosted mode.
- Downstream-asset registration UI, history search/filter/delete/pagination with retention, first-run checklist, Ctrl/Cmd+Enter to analyze, OS-aware theme, skip link.
- `/api/ready`, request ids, a global error handler, security headers, request-size limit.
- SQLite metadata store: WAL, busy timeout, schema versioning with migrations.
- Packaging: `missync` console script, UI bundled into the wheel, `install.sh`, `scripts/build_release.py`, Docker image serves the UI and has a health check.
- Community files, CI workflows, Dependabot.

### Changed
- Finding cards are compact: severity stripe, affected objects as chips, highlighted "Next step", evidence collapsed; findings are sorted by severity.
- Connector parameters are whitelisted per type; Postgres connects to the validated IP (DNS-rebinding guard); row counts use planner estimates (shown with `~`).
- `start.ps1` runs in self-hosted mode and installs the PostgreSQL driver and sample-database extra.
- Python dependencies have upper bounds (sqlglot 30.x, duckdb 2.x).

### Fixed
- The bundled demo connection stored a relative path and showed "SQLite file not found" when started from another folder.
- The Add-connection form defaulted to SQLite on a fresh page load instead of PostgreSQL.
- Deleting a connection now also removes its analyses; an unreadable secret no longer breaks the connection list.
