"""Metadata store (SQLite via SQLAlchemy): connections, assets, baselines, analyses."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Integer, String, Text, create_engine, event, func, inspect, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import get_settings
from ..models import Asset
from ..security import decrypt, encrypt, redact


class Base(DeclarativeBase):
    pass


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ConnectionRow(Base):
    __tablename__ = "connections"
    id = Column(String, primary_key=True, default=_id)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    params_enc = Column(Text, nullable=False)  # encrypted JSON (contains secrets)
    builtin = Column(Integer, default=0)
    created_at = Column(String, default=_now)


class AssetRow(Base):
    __tablename__ = "assets"
    id = Column(String, primary_key=True, default=_id)
    connection_id = Column(String, ForeignKey("connections.id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    kind = Column(String, default="dashboard")
    depends_on = Column(Text, default="[]")
    owner = Column(String)


class BaselineRow(Base):
    __tablename__ = "baselines"
    id = Column(String, primary_key=True, default=_id)
    connection_id = Column(String, ForeignKey("connections.id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    created_at = Column(String, default=_now)
    signature = Column(String)
    data = Column(Text, nullable=False)


class AnalysisRow(Base):
    __tablename__ = "analyses"
    id = Column(String, primary_key=True)
    connection_id = Column(String)
    title = Column(String)
    created_at = Column(String)
    severity = Column(String)
    data = Column(Text, nullable=False)
    summary = Column(Text)  # small JSON: summary + finding_count, so history lists never parse the full result


def _m1_analysis_summary(conn) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns("analyses")}
    if "summary" not in cols:
        conn.exec_driver_sql("alter table analyses add column summary text")


# (version, function). Append only; never edit a shipped migration.
MIGRATIONS = [(1, _m1_analysis_summary)]
SCHEMA_VERSION = MIGRATIONS[-1][0]


class Store:
    def __init__(self, url: str | None = None):
        s = get_settings()
        self.history_limit = s.history_limit
        self.engine = create_engine(url or f"sqlite:///{(s.data_dir / 'missync.db').as_posix()}", future=True)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):  # WAL lets the UI read while an analysis writes; busy_timeout avoids "database is locked"
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        Base.metadata.create_all(self.engine)
        self._migrate()
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self) -> None:
        with self.engine.begin() as c:
            c.exec_driver_sql("create table if not exists schema_version (version integer not null)")
            current = c.exec_driver_sql("select max(version) from schema_version").scalar() or 0
            for version, fn in MIGRATIONS:
                if version > current:
                    fn(c)
                    c.exec_driver_sql(f"insert into schema_version (version) values ({int(version)})")

    def health(self) -> bool:
        with self.engine.connect() as c:
            return c.exec_driver_sql("select 1").scalar() == 1

    def session(self) -> Session:
        return self._Session()

    # connections --------------------------------------------------------------------
    def add_connection(self, name: str, type_: str, params: dict[str, Any], builtin: bool = False, id_: str | None = None) -> str:
        with self.session() as s:
            row = ConnectionRow(id=id_ or _id(), name=name, type=type_, params_enc=encrypt(json.dumps(params)), builtin=int(builtin))
            s.merge(row)
            s.commit()
            return row.id

    def get_connection(self, id_: str) -> dict[str, Any] | None:
        with self.session() as s:
            r = s.get(ConnectionRow, id_)
            if not r:
                return None
            return {"id": r.id, "name": r.name, "type": r.type, "params": json.loads(decrypt(r.params_enc)),
                    "builtin": bool(r.builtin), "created_at": r.created_at}

    def list_connections(self) -> list[dict[str, Any]]:
        with self.session() as s:
            out = []
            for r in s.scalars(select(ConnectionRow).order_by(ConnectionRow.created_at)):
                try:
                    params = redact(json.loads(decrypt(r.params_enc)))
                except Exception:  # e.g. the secret key changed: keep the list usable
                    params = {}
                out.append({"id": r.id, "name": r.name, "type": r.type, "builtin": bool(r.builtin),
                            "created_at": r.created_at, "params": params})
            return out

    def delete_connection(self, id_: str) -> bool:
        with self.session() as s:
            r = s.get(ConnectionRow, id_)
            if not r or r.builtin:
                return False
            for model in (AssetRow, BaselineRow, AnalysisRow):
                for x in s.scalars(select(model).where(model.connection_id == id_)):
                    s.delete(x)
            s.delete(r)
            s.commit()
            return True

    # assets -------------------------------------------------------------------------
    def set_assets(self, connection_id: str, assets: list[Asset]) -> None:
        with self.session() as s:
            for x in s.scalars(select(AssetRow).where(AssetRow.connection_id == connection_id)):
                s.delete(x)
            for a in assets:
                s.add(AssetRow(connection_id=connection_id, name=a.name, kind=a.kind,
                               depends_on=json.dumps(a.depends_on), owner=a.owner))
            s.commit()

    def list_assets(self, connection_id: str) -> list[Asset]:
        with self.session() as s:
            return [Asset(id=r.id, name=r.name, kind=r.kind, depends_on=json.loads(r.depends_on), owner=r.owner)
                    for r in s.scalars(select(AssetRow).where(AssetRow.connection_id == connection_id))]

    # baselines ----------------------------------------------------------------------
    def add_baseline(self, connection_id: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
        with self.session() as s:
            r = BaselineRow(connection_id=connection_id, name=name, signature=data["signature"], data=json.dumps(data, default=str))
            s.add(r)
            s.commit()
            return {"id": r.id, "name": r.name, "created_at": r.created_at, "signature": r.signature}

    def list_baselines(self, connection_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            q = select(BaselineRow).where(BaselineRow.connection_id == connection_id).order_by(BaselineRow.created_at.desc())
            return [{"id": r.id, "name": r.name, "created_at": r.created_at, "signature": r.signature,
                     "tables": len(json.loads(r.data)["schema"]["tables"]), "has_profile": json.loads(r.data)["profile"] is not None}
                    for r in s.scalars(q)]

    def get_baseline(self, id_: str) -> dict[str, Any] | None:
        with self.session() as s:
            r = s.get(BaselineRow, id_)
            return {"id": r.id, "connection_id": r.connection_id, "name": r.name, "created_at": r.created_at, **json.loads(r.data)} if r else None

    def delete_baseline(self, id_: str) -> bool:
        with self.session() as s:
            r = s.get(BaselineRow, id_)
            if not r:
                return False
            s.delete(r)
            s.commit()
            return True

    # analyses -----------------------------------------------------------------------
    def save_analysis(self, result: dict[str, Any]) -> None:
        with self.session() as s:
            s.merge(AnalysisRow(id=result["id"], connection_id=result["connection_id"], title=result["title"],
                                created_at=result["created_at"], severity=result["summary"]["highest_severity"],
                                data=json.dumps(result, default=str),
                                summary=json.dumps({"summary": result["summary"], "finding_count": len(result["findings"])})))
            s.commit()
            extra = s.scalars(select(AnalysisRow.id).order_by(AnalysisRow.created_at.desc()).offset(self.history_limit)).all()
            for id_ in extra:  # retention: keep only the newest `history_limit` analyses
                s.delete(s.get(AnalysisRow, id_))
            if extra:
                s.commit()

    def delete_analysis(self, id_: str) -> bool:
        with self.session() as s:
            r = s.get(AnalysisRow, id_)
            if not r:
                return False
            s.delete(r)
            s.commit()
            return True

    def get_analysis(self, id_: str) -> dict[str, Any] | None:
        with self.session() as s:
            r = s.get(AnalysisRow, id_)
            return json.loads(r.data) if r else None

    def list_analyses(self, limit: int = 50, connection_id: str | None = None, q: str | None = None,
                      severity: str | None = None, offset: int = 0) -> list[dict[str, Any]]:
        with self.session() as s:
            stmt = select(AnalysisRow).order_by(AnalysisRow.created_at.desc())
            if connection_id:
                stmt = stmt.where(AnalysisRow.connection_id == connection_id)
            if severity:
                stmt = stmt.where(AnalysisRow.severity == severity)
            if q:
                stmt = stmt.where(func.lower(AnalysisRow.title).contains(q.lower(), autoescape=True))
            out = []
            for r in s.scalars(stmt.offset(offset).limit(limit)):
                meta = json.loads(r.summary) if r.summary else None
                if meta is None:  # row saved before the summary column existed
                    d = json.loads(r.data)
                    meta = {"summary": d["summary"], "finding_count": len(d["findings"])}
                out.append({"id": r.id, "title": r.title, "created_at": r.created_at, "connection_id": r.connection_id,
                            "severity": r.severity, "summary": meta["summary"], "finding_count": meta["finding_count"]})
            return out
