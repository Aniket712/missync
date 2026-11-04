from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MISSYNC_", env_file=".env", extra="ignore")

    mode: str = "demo"  # "demo" (bundled data only) or "self-hosted"
    data_dir: Path = Path("./data")
    secret_key: str | None = None  # Fernet key; generated into data_dir if absent
    allow_local_paths: bool = False  # self-hosted: allow sqlite/duckdb files outside data_dir
    allowed_hosts: str = ""  # comma separated host allowlist for network connectors
    allow_private_hosts: bool = True  # self-hosted default; set False for hardened deployments
    statement_timeout_s: int = 30
    sample_limit: int = 200_000  # max rows copied per table into the sandbox
    max_sql_chars: int = 200_000
    result_limit: int = 1000
    cors_origins: str = "http://localhost:5173"
    api_token: str | None = None  # when set, every /api route (except /api/health) needs "Authorization: Bearer <token>"
    allow_insecure_bind: bool = False  # allow a non-local bind without a token (e.g. behind an authenticating proxy / loopback-published Docker port)
    max_concurrent_analyses: int = 2
    analysis_deadline_s: int = 600  # overall wall-clock limit for one analysis
    max_body_bytes: int = 2_000_000
    history_limit: int = 500  # analyses kept in history (oldest are pruned)
    frontend_dist: Path | None = None  # override the built UI location

    @property
    def demo(self) -> bool:
        return self.mode.lower() == "demo"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
