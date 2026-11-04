# Connector capability matrix

| Capability | SQLite | DuckDB | CSV / Parquet | PostgreSQL | BigQuery | Snowflake |
|---|---|---|---|---|---|---|
| Schema discovery | yes | yes | yes (inferred) | yes | yes | yes |
| View definitions → lineage | yes | yes | no | yes (`pg_views`) | yes | yes |
| Row counts | exact | exact | exact | planner estimate (`~`), exact when no statistics | metadata | metadata |
| Sandbox validation (copy + apply + compare) | yes | yes | yes | yes (sampled copy into DuckDB) | **no** (static only) | **no** (static only) |
| Read-only enforcement | `mode=ro` + `query_only` | `read_only=True` | read-only views | `default_transaction_read_only`, `statement_timeout`, use SELECT-only role | SELECT only; viewer role | SELECT only; SELECT-only role |
| Auth | file path (confined to data dir) | file path | file path | user/password, `sslmode` | ADC (preferred) or service-account JSON | key-pair (preferred) or password |
| SSRF checks | n/a | n/a | n/a | yes (connects to the validated IP) | n/a (Google API) | yes |
| Accepted parameters | `path` | `path`, `files` | `files` | `host`, `port`, `database`, `user`, `password`, `schema`, `sslmode` | `project`, `dataset`, `credentials_json` | `account`, `user`, `database`, `schema`, `warehouse`, `role`, `password`, `private_key`, `private_key_passphrase` |
| Row preview in the UI | yes | yes | yes | yes | yes | yes |
| **Tested against the real system** | yes | yes | yes | yes (live PostgreSQL 16.2, embedded via `pgserver`; the compose file itself is unrun) | **no** (fake client only) | **no** (fake connection only) |

Anything not in the "accepted parameters" row is rejected with an error before a connector is built.
`sslmode` must be one of `disable, allow, prefer, require, verify-ca, verify-full`; `schema` must be a plain identifier; `port` an integer 1–65535.

## PostgreSQL notes
- One schema per connection (default `public`).
- The embedded **sample database** (Connections → PostgreSQL → *Launch sample database*, needs the `sample` extra) is a real PostgreSQL 16 started by `pgserver`, seeded from `backend/missync/demo/postgres-init.sql` (identical to `docker/postgres-init.sql`; a test keeps them in sync). It uses trust authentication on 127.0.0.1, so any password is accepted; use it for demos only.
- Connection errors are mapped to short, secret-free messages (wrong password, unknown database, unreachable host, SSL mode).

## Adding a connector
Subclass `Connector` in `backend/missync/connectors/`, implement `test`, `discover`, `fetch_rows`
(bounded), declare `Capabilities`, register it in `connectors/__init__.py` (`REGISTRY`) **and** list the parameters it accepts in `ALLOWED_PARAMS`. Call `validate_host` for any network host and connect to the address it returns. Add tests next to `tests/test_connectors.py`.
