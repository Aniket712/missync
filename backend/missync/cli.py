"""Command line: `missync serve` (default) and `missync analyze` (for CI gates and quick checks)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .models import SEVERITY_ORDER

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _serve(args: argparse.Namespace) -> int:
    if args.data_dir:
        os.environ["MISSYNC_DATA_DIR"] = args.data_dir
    if args.mode:
        os.environ["MISSYNC_MODE"] = args.mode

    from .config import get_settings

    settings = get_settings()
    if args.host not in LOOPBACK and not settings.api_token and not settings.demo and not settings.allow_insecure_bind:
        print(
            "Refusing to listen on a non-local address without authentication.\n"
            "Set MISSYNC_API_TOKEN to a long random value, for example:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
            "(or run behind an authenticating reverse proxy and set MISSYNC_ALLOW_INSECURE_BIND=true).",
            file=sys.stderr,
        )
        return EXIT_ERROR

    import uvicorn

    uvicorn.run("missync.api.app:app", host=args.host, port=args.port)
    return EXIT_OK


def _read_sql(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if args.sql:
        for f in args.sql:
            parts.append(sys.stdin.read() if f == "-" else Path(f).read_text(encoding="utf-8"))
    if args.dir:
        files = sorted(p for p in Path(args.dir).rglob("*.sql") if p.is_file())
        if not files:
            raise ValueError(f"No .sql files found in {args.dir}")
        parts.extend(f"-- file: {p.name}\n" + p.read_text(encoding="utf-8") for p in files)
    sql = "\n;\n".join(p.strip().rstrip(";") for p in parts if p.strip())
    if not sql:
        raise ValueError("No SQL provided: use --sql FILE (or '-' for stdin) and/or --dir DIRECTORY")
    return sql


def _connector(args: argparse.Namespace):
    """Returns (connector, assets, connection_id)."""
    from .connectors import build_connector

    if args.demo:
        from .config import get_settings
        from .demo.seed import DEMO_ASSETS, build_demo_db
        from .models import Asset

        path = build_demo_db(get_settings().data_dir / "demo" / "demo.sqlite")
        return build_connector("sqlite", {"path": str(path)}, enforce_path=False), [Asset(name=n, kind=k, depends_on=d) for n, k, d in DEMO_ASSETS], "demo"
    if args.sqlite:
        return build_connector("sqlite", {"path": args.sqlite}, enforce_path=False), [], "cli"
    if args.duckdb:
        return build_connector("duckdb", {"path": args.duckdb}, enforce_path=False), [], "cli"
    url = args.postgres_url or os.environ.get("MISSYNC_POSTGRES_URL")
    if url:
        from sqlalchemy.engine import make_url

        u = make_url(url)
        params = {"host": u.host or "localhost", "port": u.port or 5432, "database": u.database, "user": u.username, "password": u.password or ""}
        if u.query.get("sslmode"):
            params["sslmode"] = u.query["sslmode"]
        return build_connector("postgres", params), [], "cli"
    if args.connection:
        from .store.db import Store

        st = Store()
        row = next((c for c in st.list_connections() if args.connection in (c["id"], c["name"])), None)
        if not row:
            raise ValueError(f"No saved connection named '{args.connection}'. Save one in the UI first, or use --sqlite/--postgres-url.")
        full = st.get_connection(row["id"])
        return build_connector(full["type"], full["params"], enforce_path=not full["builtin"]), st.list_assets(row["id"]), row["id"]
    raise ValueError("Choose a source: --demo, --sqlite PATH, --duckdb PATH, --postgres-url URL (or MISSYNC_POSTGRES_URL), or --connection NAME")


def _text_report(r: dict) -> str:
    s = r["summary"]
    lines = [f"Missync: {r['title']}", f"Verdict: {s['verdict']}", ""]
    counts = ", ".join(f"{n} {k}" for k, n in s["by_severity"].items() if n) or "no findings"
    lines.append(f"Findings: {counts}  ({s['verified']} verified, {s['predicted']} predicted; sandbox validated: {'yes' if s['validated_in_sandbox'] else 'no'})")
    for f in r["findings"]:
        lines.append(f"  [{f['severity'].upper():8}] {f['kind']:9} {f['title']}")
    if s["impacted_objects"]:
        lines.append("Impacted: " + ", ".join(s["impacted_objects"]))
    if r["limitations"]:
        lines += ["", "Limitations:"] + [f"  - {x}" for x in r["limitations"]]
    return "\n".join(lines)


def _analyze(args: argparse.Namespace) -> int:
    if args.data_dir:
        os.environ["MISSYNC_DATA_DIR"] = args.data_dir
    try:
        sql = _read_sql(args)
        connector, assets, cid = _connector(args)
    except Exception as e:
        print(f"error: {getattr(e, 'detail', None) or e}", file=sys.stderr)
        return EXIT_ERROR

    from .analysis.engine import run_analysis
    from .models import AnalysisRequest
    from .reports.export import to_html, to_json

    try:
        with connector as c:
            req = AnalysisRequest(connection_id=cid, sql=sql, sql_dialect=args.dialect, title=args.title or "CLI analysis")
            result = run_analysis(c, req, assets).model_dump()
    except Exception as e:
        print(f"error: analysis failed: {e}", file=sys.stderr)
        return EXIT_ERROR

    text = _text_report(result)
    if args.format == "json":
        body = to_json(result)
    elif args.format == "html":
        body = to_html(result)
    else:
        body = text
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
        print(text)
        print(f"\nReport written to {args.output}")
    elif args.format == "html":
        print("error: --format html needs --output FILE", file=sys.stderr)
        return EXIT_ERROR
    else:
        print(body)

    if args.fail_on != "never":
        threshold = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f["severity"]] <= threshold for f in result["findings"]):
            return EXIT_FINDINGS
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="missync", description="Catch data changes before they break what depends on them.")
    sub = ap.add_subparsers(dest="cmd")

    sv = sub.add_parser("serve", help="Run the web app (default when no command is given)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--data-dir", default=None, help="Metadata/demo data directory (default: ./data)")
    sv.add_argument("--mode", choices=["demo", "self-hosted"], default=None)
    sv.set_defaults(fn=_serve)

    an = sub.add_parser("analyze", help="Analyze SQL against a database and print/write a report (CI friendly)")
    an.add_argument("--sql", action="append", metavar="FILE", help="SQL file ('-' for stdin); repeatable")
    an.add_argument("--dir", metavar="DIR", help="Folder of .sql migration files, applied in filename order")
    src = an.add_argument_group("source (choose one)")
    src.add_argument("--demo", action="store_true", help="Use the bundled demo database")
    src.add_argument("--sqlite", metavar="PATH")
    src.add_argument("--duckdb", metavar="PATH")
    src.add_argument("--postgres-url", metavar="URL", help="postgresql://user:pass@host:5432/db (prefer MISSYNC_POSTGRES_URL to keep it out of process lists)")
    src.add_argument("--connection", metavar="NAME", help="A connection saved in the web app (name or id)")
    an.add_argument("--dialect", default=None, help="SQL dialect of the change (default: the source's dialect)")
    an.add_argument("--title", default=None)
    an.add_argument("--format", choices=["text", "json", "html"], default="text")
    an.add_argument("--output", metavar="FILE", help="Write the report here (a text summary still prints)")
    an.add_argument("--fail-on", choices=["critical", "high", "medium", "low", "never"], default="high",
                    help="Exit with code 1 when a finding is at least this severe (default: high)")
    an.add_argument("--data-dir", default=None)
    an.set_defaults(fn=_analyze)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]  # `python -m missync --port 8001` keeps working
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return EXIT_ERROR
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
