"""Credential protection, SSRF checks, path checks and log redaction."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from .config import Settings, get_settings

SECRET_KEYS = {"password", "private_key", "private_key_passphrase", "token", "credentials_json", "secret", "api_key"}
_URL_CRED = re.compile(r"(\w+://[^:/\s]+:)([^@/\s]+)(@)")


class SecurityError(ValueError):
    pass


def redact(value: Any) -> Any:
    """Return a copy of value with secrets masked (for API responses and logs)."""
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in SECRET_KEYS and v else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _URL_CRED.sub(r"\1***\3", value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, (str, dict)) else a for a in record.args)
        return True


def install_log_redaction() -> None:
    f = RedactingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "missync"):
        logging.getLogger(name).addFilter(f)


def _fernet(settings: Settings) -> Fernet:
    key = settings.secret_key
    if not key:
        path = settings.data_dir / ".secret_key"
        if path.exists():
            key = path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(key)
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            try:
                os.link(tmp, path)  # atomic create-if-absent: if two processes race, the first key wins
            except FileExistsError:
                pass
            except OSError:  # filesystem without hard links
                if not path.exists():
                    tmp.replace(path)
            tmp.unlink(missing_ok=True)
            key = path.read_text().strip()
    return Fernet(key.encode())


def encrypt(text: str, settings: Settings | None = None) -> str:
    return _fernet(settings or get_settings()).encrypt(text.encode()).decode()


def decrypt(token: str, settings: Settings | None = None) -> str:
    return _fernet(settings or get_settings()).decrypt(token.encode()).decode()


def validate_host(host: str, settings: Settings | None = None) -> str:
    """SSRF guard for network connectors. Returns the validated IP address to connect to (prefers IPv4).

    Always blocks link-local / metadata / unspecified ranges. Optionally blocks all private
    ranges and enforces an allowlist. Connecting to the returned IP (not the name) stops DNS rebinding
    between this check and the connection.
    """
    settings = settings or get_settings()
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9_.\-:\[\]]+", host):
        raise SecurityError("Invalid host")
    allow = {h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()}
    if allow and host.lower() not in allow:
        raise SecurityError("Host is not in MISSYNC_ALLOWED_HOSTS")
    try:
        infos = socket.getaddrinfo(host.strip("[]"), None)
    except socket.gaierror as e:
        raise SecurityError(f"Cannot resolve host: {host}") from e
    ips = [ipaddress.ip_address(i[4][0]) for i in infos]
    for ip in ips:
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            raise SecurityError("Host resolves to a blocked address range (link-local/metadata/reserved)")
        if not settings.allow_private_hosts and (ip.is_private or ip.is_loopback) and host.lower() not in allow:
            raise SecurityError("Private/loopback hosts are disabled (MISSYNC_ALLOW_PRIVATE_HOSTS=false)")
    return str(next((ip for ip in ips if ip.version == 4), ips[0]))


def validate_local_path(path: str, settings: Settings | None = None) -> Path:
    """Restrict file-based sources to data_dir unless explicitly allowed."""
    settings = settings or get_settings()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = settings.data_dir / p
    p = p.resolve()
    root = settings.data_dir.resolve()
    if not settings.allow_local_paths and root != p and root not in p.parents:
        raise SecurityError("File paths must be inside the Missync data directory")
    return p


def quote_ident(name: str) -> str:
    """Quote an identifier for generic ANSI-style SQL (sqlite/duckdb/postgres)."""
    return '"' + name.replace('"', '""') + '"'
