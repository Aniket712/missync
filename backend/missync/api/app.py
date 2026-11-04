from __future__ import annotations

import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..analysis import baselines as bl
from ..analysis.engine import run_analysis
from ..analysis.sql_parser import SqlRejected
from ..config import get_settings
from ..connectors import REGISTRY, ConnectorError, build_connector
from ..demo import sample_pg
from ..demo.scenarios import SCENARIOS, scenario_request
from ..demo.seed import DEMO_ASSETS, build_demo_db
from ..models import AnalysisRequest, Asset
from ..reports.export import to_html, to_json
from ..security import SecurityError, install_log_redaction
from ..store.db import Store
from .jobs import JobManager

log = logging.getLogger("missync")
VERSION = "0.1.0"
DEMO_ID = "demo"
PUBLIC_API = {"/api/health", "/api/ready"}


def find_frontend_dist(settings) -> Path:
    """Built UI location: explicit override, then the copy bundled in the package, then the repo checkout."""
    candidates = [settings.frontend_dist, Path(__file__).resolve().parents[1] / "_static",
                  Path(__file__).resolve().parents[3] / "frontend" / "dist"]
    for c in candidates:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return Path(candidates[-1])


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


def _cell(v: Any) -> Any:
    return v if v is None or isinstance(v, (int, float, str, bool)) else str(v)


def friendly_error(e: Exception) -> str:
    """Actionable, secret-free message for a connection failure (the raw driver text may echo host/user details)."""
    name = type(e).__name__
    msg = str(e).lower()
    if isinstance(e, ModuleNotFoundError):
        return f"A database driver is missing ({e.name}). Install it with: pip install -e \"backend[postgres]\""
    if "password authentication failed" in msg or "authentication failed" in msg:
        return "Authentication failed: check the user name and password."
    if "does not exist" in msg and "database" in msg:
        return "That database does not exist on the server: check the database name."
    if "role" in msg and "does not exist" in msg:
        return "That user does not exist on the server."
    if "timeout expired" in msg or "timed out" in msg:
        return "The server did not answer in time: check the host, port and firewall."
    if "connection refused" in msg or "could not connect" in msg or "could not translate host" in msg or "name or service not known" in msg:
        return "Could not reach the server: check the host and port, and that PostgreSQL is running."
    if "ssl" in msg or "no pg_hba.conf entry" in msg:
        return "The server rejected the connection (SSL or access rule): try a different SSL mode."
    return f"Connection test failed ({name})."


def create_app(store: Store | None = None) -> FastAPI:
    settings = get_settings()
    install_log_redaction()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = store or Store()
        app.state.store = st
        demo_path = Path(build_demo_db(settings.data_dir / "demo" / "demo.sqlite")).resolve()
        existing = st.get_connection(DEMO_ID)
        # Always (re)write the absolute path: a relative one saved earlier breaks when the working directory changes.
        if not existing or existing["params"].get("path") != str(demo_path):
            st.add_connection("Demo shop (synthetic SQLite)", "sqlite", {"path": str(demo_path)}, builtin=True, id_=DEMO_ID)
        if not existing:
            st.set_assets(DEMO_ID, [Asset(name=n, kind=k, depends_on=d) for n, k, d in DEMO_ASSETS])
        app.state.jobs = JobManager(settings.max_concurrent_analyses, settings.analysis_deadline_s)
        yield
        app.state.jobs.shutdown()
        sample_pg.stop()

    app = FastAPI(title="Missync", version=VERSION, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins.split(",") if o],
                       allow_methods=["*"], allow_headers=["*"])
    api_token = settings.api_token

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Request id, body-size cap, optional bearer-token auth and basic security headers."""
        rid = uuid.uuid4().hex[:10]
        request.state.request_id = rid
        path = request.url.path
        if path.startswith("/api/") and request.method != "OPTIONS":
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > settings.max_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
            if api_token and path not in PUBLIC_API:
                supplied = request.headers.get("authorization", "")
                if not hmac.compare_digest(supplied.encode(), f"Bearer {api_token}".encode()):
                    return JSONResponse(status_code=401, content={"detail": "Missing or invalid API token"}, headers={"WWW-Authenticate": "Bearer"})
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "-")
        log.exception("unhandled error [%s]", rid)
        return JSONResponse(status_code=500, content={"detail": f"Unexpected server error (ref {rid}). Check the server log."})

    def get_store(request: Request) -> Store:
        return request.app.state.store

    def connector_for(st: Store, cid: str):
        row = st.get_connection(cid)
        if not row:
            raise HTTPException(404, "Connection not found")
        try:
            return build_connector(row["type"], row["params"], enforce_path=not row["builtin"])
        except (ConnectorError, SecurityError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            log.warning("connector error: %s", type(e).__name__)
            raise HTTPException(502, f"Could not connect: {type(e).__name__}") from e

    def require_selfhosted() -> None:
        if settings.demo:
            raise HTTPException(403, "Custom connections are disabled in the public demo. Run Missync locally to connect your own database.")

    @app.exception_handler(SqlRejected)
    async def _sql_rejected(_: Request, exc: SqlRejected):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/api/config")
    def config():
        return {"mode": settings.mode, "demo": settings.demo, "connector_types": sorted(REGISTRY) if not settings.demo else ["sqlite"],
                "limits": {"sample_limit": settings.sample_limit, "timeout_s": settings.statement_timeout_s, "max_sql_chars": settings.max_sql_chars}}

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION, "auth_required": bool(api_token)}

    @app.get("/api/ready")
    def ready(request: Request):
        problems = []
        try:
            if not request.app.state.store.health():
                problems.append("metadata store")
        except Exception:
            problems.append("metadata store")
        if not settings.data_dir.is_dir():
            problems.append("data directory")
        if problems:
            raise HTTPException(503, f"Not ready: {', '.join(problems)}")
        return {"ready": True}

    # ---- connections ----------------------------------------------------------------
    @app.get("/api/connections")
    def list_connections(st: Store = Depends(get_store)):
        return st.list_connections()

    def _probe(body: ConnectionIn) -> dict[str, Any]:
        """Validate, build and test a connector without saving it. Returns server info, latency, capabilities and object count."""
        if body.type not in REGISTRY:
            raise HTTPException(422, f"Unknown connector type '{body.type}'")
        started = time.monotonic()
        try:
            conn = build_connector(body.type, body.params)
            try:
                info = conn.test()
                caps = conn.capabilities.model_dump()
                objects = len(conn.discover().tables)
            finally:
                conn.close()
        except (ConnectorError, SecurityError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            log.warning("connection test failed: %s", type(e).__name__)
            raise HTTPException(400, friendly_error(e)) from e
        return {**info, "latency_ms": round((time.monotonic() - started) * 1000), "capabilities": caps, "objects": objects}

    @app.post("/api/connections/test")
    def test_new_connection(body: ConnectionIn):
        require_selfhosted()
        return _probe(body)

    @app.post("/api/connections", status_code=201)
    def add_connection(body: ConnectionIn, st: Store = Depends(get_store)):
        require_selfhosted()
        info = _probe(body)
        cid = st.add_connection(body.name, body.type, body.params)
        return {"id": cid, "test": info}

    # ---- sample database (embedded PostgreSQL, self-hosted only) ---------------------
    @app.get("/api/sample-postgres")
    def sample_postgres_status():
        require_selfhosted()
        return sample_pg.status()

    @app.post("/api/sample-postgres/start")
    def sample_postgres_start():
        require_selfhosted()
        try:
            return sample_pg.start(settings.data_dir)
        except sample_pg.SampleUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.delete("/api/connections/{cid}", status_code=204)
    def delete_connection(cid: str, st: Store = Depends(get_store)):
        require_selfhosted()
        if not st.delete_connection(cid):
            raise HTTPException(404, "Connection not found or built-in")
        return Response(status_code=204)

    @app.post("/api/connections/{cid}/test")
    def test_connection(cid: str, st: Store = Depends(get_store)):
        with connector_for(st, cid) as c:
            return {**c.test(), "capabilities": c.capabilities.model_dump()}

    @app.get("/api/connections/{cid}/schema")
    def schema(cid: str, st: Store = Depends(get_store)):
        with connector_for(st, cid) as c:
            snap = c.discover()
            return {"schema": snap.model_dump(), "capabilities": c.capabilities.model_dump(), "type": c.type}

    @app.get("/api/connections/{cid}/preview")
    def preview(cid: str, table: str, limit: int = 20, st: Store = Depends(get_store)):
        limit = max(1, min(limit, 100))
        with connector_for(st, cid) as c:
            if table not in {t.name for t in c.discover().tables}:  # only discovered objects are ever queried
                raise HTTPException(404, "Table not found")
            try:
                cols, rows, truncated = c.fetch_rows(table, limit)
            except Exception as e:
                log.warning("preview failed: %s", type(e).__name__)
                raise HTTPException(502, friendly_error(e)) from e
        return {"columns": cols, "rows": [[_cell(v) for v in r] for r in rows], "truncated": truncated}

    @app.get("/api/connections/{cid}/lineage")
    def lineage(cid: str, st: Store = Depends(get_store)):
        from ..analysis.lineage import build_lineage

        with connector_for(st, cid) as c:
            g = build_lineage(c.discover(), st.list_assets(cid))
        nodes = [{"id": k, "type": v} for k, v in g.kinds.items()] + [{"id": f"asset:{a.name}", "type": "asset", "label": a.name} for a in g.assets]
        edges = [{"source": s, "target": d, "complete": d not in g.incomplete_views} for s, ds in g.table_edges.items() for d in ds]
        for a in g.assets:
            for dep in a.depends_on:
                edges.append({"source": dep.split(".")[0], "target": f"asset:{a.name}", "complete": True})
        return {"nodes": nodes, "edges": edges, "incomplete": g.incomplete_views}

    @app.get("/api/connections/{cid}/assets")
    def get_assets(cid: str, st: Store = Depends(get_store)):
        return [a.model_dump() for a in st.list_assets(cid)]

    @app.put("/api/connections/{cid}/assets")
    def put_assets(cid: str, assets: list[Asset] = Body(...), st: Store = Depends(get_store)):
        if not st.get_connection(cid):
            raise HTTPException(404, "Connection not found")
        if settings.demo:
            raise HTTPException(403, "Assets are read-only in the public demo")
        st.set_assets(cid, assets)
        return {"ok": True}

    # ---- analyses -------------------------------------------------------------------
    def _precheck(req: AnalysisRequest) -> None:
        if len(req.sql) > settings.max_sql_chars:
            raise HTTPException(413, "SQL is too large")
        if settings.demo and req.connection_id != DEMO_ID:
            raise HTTPException(403, "Only the bundled demo connection is available in the public demo")

    def _run(st: Store, req: AnalysisRequest, progress=None) -> dict[str, Any]:
        with connector_for(st, req.connection_id) as c:
            result = run_analysis(c, req, st.list_assets(req.connection_id), progress)
        data = result.model_dump()
        st.save_analysis(data)
        return data

    def _job_error(e: Exception) -> tuple[int, str]:
        if isinstance(e, HTTPException):
            return e.status_code, str(e.detail)
        if isinstance(e, SqlRejected):
            return 422, str(e)
        log.exception("analysis failed")
        return 500, f"The analysis failed unexpectedly ({type(e).__name__}). Check the server log."

    def _submit(app_: FastAPI, st: Store, req: AnalysisRequest):
        _precheck(req)
        return app_.state.jobs.submit(lambda progress: _run(st, req, progress)["id"], _job_error)

    def _execute(app_: FastAPI, st: Store, req: AnalysisRequest) -> dict[str, Any]:
        """Synchronous path (API clients, scenarios): same worker pool, so concurrency stays bounded."""
        job = _submit(app_, st, req)
        job.done.wait()
        if job.status != "done":
            raise HTTPException(job.http_status, job.error or "The analysis was cancelled")
        return st.get_analysis(job.result_id)

    @app.post("/api/analyses")
    def analyze(req: AnalysisRequest, request: Request, st: Store = Depends(get_store)):
        return _execute(request.app, st, req)

    @app.post("/api/jobs", status_code=202)
    def start_job(req: AnalysisRequest, request: Request, st: Store = Depends(get_store)):
        return _submit(request.app, st, req).public()

    @app.get("/api/jobs/{jid}")
    def job_status(jid: str, request: Request):
        job = request.app.state.jobs.get(jid)
        if not job:
            raise HTTPException(404, "Job not found")
        return job.public()

    @app.delete("/api/jobs/{jid}", status_code=202)
    def cancel_job(jid: str, request: Request):
        if not request.app.state.jobs.cancel(jid):
            raise HTTPException(404, "Job not found")
        return {"ok": True}

    @app.get("/api/analyses")
    def analyses(limit: int = 50, offset: int = 0, q: str | None = None, severity: str | None = None, st: Store = Depends(get_store)):
        return st.list_analyses(max(1, min(limit, 200)), q=q, severity=severity, offset=max(0, offset))

    @app.delete("/api/analyses/{aid}", status_code=204)
    def delete_analysis(aid: str, st: Store = Depends(get_store)):
        require_selfhosted()
        if not st.delete_analysis(aid):
            raise HTTPException(404, "Analysis not found")
        return Response(status_code=204)

    @app.get("/api/analyses/{aid}")
    def get_analysis(aid: str, st: Store = Depends(get_store)):
        r = st.get_analysis(aid)
        if not r:
            raise HTTPException(404, "Analysis not found")
        return r

    @app.get("/api/analyses/{aid}/report.json")
    def report_json(aid: str, st: Store = Depends(get_store)):
        r = st.get_analysis(aid)
        if not r:
            raise HTTPException(404, "Analysis not found")
        return Response(to_json(r), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="missync-{aid}.json"'})

    @app.get("/api/analyses/{aid}/report.html")
    def report_html(aid: str, st: Store = Depends(get_store)):
        r = st.get_analysis(aid)
        if not r:
            raise HTTPException(404, "Analysis not found")
        return HTMLResponse(to_html(r), headers={"Content-Disposition": f'attachment; filename="missync-{aid}.html"',
                                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    # ---- scenarios ------------------------------------------------------------------
    @app.get("/api/scenarios")
    def scenarios():
        return [{"id": k, "title": v["title"], "description": v["description"], "sql": v["sql"], "metrics": v["metrics"], "keys": v["keys"]}
                for k, v in SCENARIOS.items()]

    @app.post("/api/scenarios/{sid}/run")
    def run_scenario(sid: str, request: Request, st: Store = Depends(get_store)):
        if sid not in SCENARIOS:
            raise HTTPException(404, "Unknown scenario")
        return _execute(request.app, st, AnalysisRequest(**scenario_request(sid, DEMO_ID)))

    # ---- baselines ------------------------------------------------------------------
    @app.post("/api/connections/{cid}/baselines", status_code=201)
    def capture_baseline(cid: str, body: dict[str, Any] = Body(default_factory=dict), st: Store = Depends(get_store)):
        if settings.demo and cid != DEMO_ID:
            raise HTTPException(403, "Demo mode")
        with connector_for(st, cid) as c:
            data = bl.capture(c)
        name = str(body.get("name") or f"Baseline {data['captured_at']}")[:80]
        return st.add_baseline(cid, name, data)

    @app.get("/api/connections/{cid}/baselines")
    def list_baselines(cid: str, st: Store = Depends(get_store)):
        return st.list_baselines(cid)

    @app.get("/api/baselines/{bid}")
    def get_baseline(bid: str, st: Store = Depends(get_store)):
        b = st.get_baseline(bid)
        if not b:
            raise HTTPException(404, "Baseline not found")
        return b

    @app.delete("/api/baselines/{bid}", status_code=204)
    def del_baseline(bid: str, st: Store = Depends(get_store)):
        require_selfhosted()
        if not st.delete_baseline(bid):
            raise HTTPException(404, "Baseline not found")
        return Response(status_code=204)

    @app.get("/api/baselines/{bid}/compare")
    def compare_baseline(bid: str, to: str = "current", st: Store = Depends(get_store)):
        old = st.get_baseline(bid)
        if not old:
            raise HTTPException(404, "Baseline not found")
        if to == "current":
            with connector_for(st, old["connection_id"]) as c:
                new = bl.capture(c)
            label = "current state"
        else:
            new = st.get_baseline(to)
            if not new or new["connection_id"] != old["connection_id"]:
                raise HTTPException(404, "Comparison baseline not found")
            label = new["name"]
        res = bl.compare(old, new, st.list_assets(old["connection_id"]))
        return {"from": {"id": old["id"], "name": old["name"], "captured_at": old["captured_at"]},
                "to": {"name": label, "captured_at": new["captured_at"]}, **res}

    # ---- static frontend ------------------------------------------------------------
    FRONTEND_DIST = find_frontend_dist(settings)
    if (FRONTEND_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (FRONTEND_DIST / path).resolve()
            if path and FRONTEND_DIST.resolve() in f.parents and f.is_file():
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
