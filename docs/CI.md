# CLI and CI

`missync analyze` runs the same engine as the web app without a browser, so a pull request that changes SQL can be checked before it merges.

```bash
pip install "missync[postgres]"          # from a checkout: pip install -e "backend[postgres]"

# one file, or a folder of migrations applied in filename order
missync analyze --sql migrations/0042_drop_discount.sql --postgres-url "$STAGING_URL" --fail-on high
missync analyze --dir migrations/pending --sqlite ./data/app.db --format html --output report.html
missync analyze --connection "Staging" --sql change.sql      # a connection saved in the web app (uses ./data)
missync analyze --demo --sql change.sql                      # try it against the bundled demo database
```

Keep passwords out of process lists: set `MISSYNC_POSTGRES_URL` instead of passing `--postgres-url`. Use a **read-only database user**; Missync never writes to the source, but least privilege is still the right default.

| Option | Meaning |
|---|---|
| `--sql FILE` (repeatable, `-` = stdin), `--dir DIR` | The change. Folders are read recursively, `*.sql` in filename order. |
| `--demo`, `--sqlite`, `--duckdb`, `--postgres-url`, `--connection` | The data to analyze against (choose one). |
| `--dialect` | SQL dialect of the change (default: the database's). |
| `--format text\|json\|html`, `--output FILE` | Report format. A text summary is always printed. HTML needs `--output`. |
| `--fail-on critical\|high\|medium\|low\|never` | Exit code 1 when a finding is at least this severe (default `high`). |

Exit codes: `0` no finding at or above the threshold, `1` findings at or above it, `2` usage or runtime error.

## GitHub Action

This repository ships a composite action. It installs Missync from the action's own checkout, runs the analysis, writes the summary to the job summary, uploads the HTML report as an artifact and fails the step according to `fail-on`.

```yaml
name: Check migrations
on: pull_request
jobs:
  missync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Aniket712/missync@main         # or pin to a release tag once you publish one
        with:
          sql: migrations/pending           # file or folder
          postgres-url: ${{ secrets.STAGING_READONLY_URL }}
          dialect: postgres
          fail-on: high
```

The database must be reachable from the runner (a self-hosted runner, or a staging database that allows it). For a self-contained check, commit a small SQLite or DuckDB fixture and pass `sqlite: tests/fixtures/app.db`.

Note: the action and workflows in this repository have not been run on GitHub yet; try them on a branch first.

## What the result means

Findings are **verified** when they were observed on an isolated copy of a bounded sample of your data, and **predicted** when only static analysis was possible (for example BigQuery/Snowflake, or a statement the sandbox could not run). Read the `Limitations` section of the report: sampled tables, incomplete lineage and dialect differences are listed there. A passing check is evidence, not a guarantee.
