"""Connector interface. Connectors are read-only: they discover metadata and fetch bounded rows."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from ..models import Capabilities, SchemaSnapshot


class ConnectorError(RuntimeError):
    pass


class Connector(ABC):
    type: str = ""
    dialect: str = ""  # SQLGlot dialect name
    capabilities: Capabilities = Capabilities()

    @abstractmethod
    def test(self) -> dict[str, Any]:
        """Verify connectivity; return harmless server info."""

    @abstractmethod
    def discover(self) -> SchemaSnapshot:
        """Return tables, columns, views and (if accessible) view definitions."""

    @abstractmethod
    def fetch_rows(self, table: str, limit: int) -> tuple[list[str], list[tuple], bool]:
        """Return (column names, rows, truncated) for a bounded read of one table. Never writes."""

    def row_count(self, table: str) -> int | None:
        return None

    def query(self, sql: str, limit: int = 1000) -> tuple[list[str], list[tuple]]:
        """Run a read-only SELECT with a result limit. Optional; used for previews."""
        raise ConnectorError(f"{self.type} connector does not support ad-hoc queries")

    def close(self) -> None:  # noqa: B027
        pass

    def __enter__(self) -> Connector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def batched(rows: Iterator[tuple], n: int) -> Iterator[list[tuple]]:
    batch: list[tuple] = []
    for r in rows:
        batch.append(r)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


_CREATE_VIEW = re.compile(
    r'^\s*create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?view\s+(?:if\s+not\s+exists\s+)?'
    r'(?:"[^"]+"|[\w.]+)(?:\s*\([^)]*\))?\s+as\s+', re.IGNORECASE)


def view_body(create_sql: str) -> str:
    """Strip a leading CREATE VIEW ... AS from a stored view statement."""
    return _CREATE_VIEW.sub("", create_sql, count=1).strip().rstrip(";")
