# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private vulnerability reporting (the repository's *Security* tab → *Report a vulnerability*) and include what you found, how to reproduce it, and the impact you expect. You will get an acknowledgement within a few days; fixes ship in the next patch release with credit unless you prefer otherwise.

## What Missync is designed to protect

- **Your databases are never written to.** Connectors open sessions read-only, and the analysis runs the proposed change only against a throw-away DuckDB copy of a bounded sample. Use a database role that only has `SELECT` anyway (defence in depth).
- **Stored credentials are encrypted** at rest (Fernet) and are never returned by the API. The key comes from `MISSYNC_SECRET_KEY` or is generated into `data/.secret_key`. Back that file up with the database and keep it out of version control.
- **Network connectors are SSRF-guarded.** Link-local/metadata/reserved ranges are always blocked and the connection goes to the validated IP. Set `MISSYNC_ALLOW_PRIVATE_HOSTS=false` and/or `MISSYNC_ALLOWED_HOSTS` for shared deployments.
- **Public demo mode** (`MISSYNC_MODE=demo`, the default) exposes only the bundled synthetic database.

## Deployment guidance

- Missync is built to run **on your own machine or inside your network**. By default it listens on `127.0.0.1`.
- It refuses to listen on a non-local address in self-hosted mode unless `MISSYNC_API_TOKEN` is set (a bearer token required on every `/api` call). Use a long random value (`python -c "import secrets; print(secrets.token_urlsafe(32))"`). If you terminate authentication in a reverse proxy instead, set `MISSYNC_ALLOW_INSECURE_BIND=true` deliberately.
- There are no user accounts, roles or per-user history: anyone with the token can use every connection. Do not expose a self-hosted instance to the internet without TLS (a reverse proxy) and the token.
- Report HTML files are escaped and carry a restrictive CSP, but treat reports as sensitive: they contain your SQL and table/column names.

## Supported versions

Only the latest release receives security fixes while the project is pre-1.0.
