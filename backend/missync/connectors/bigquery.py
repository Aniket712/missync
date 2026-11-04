"""BigQuery adapter using the official google-cloud-bigquery client.

Authentication: Application Default Credentials (recommended; `gcloud auth application-default login`
or workload identity) or a service-account JSON given via `credentials_json` (stored encrypted).
Grant only roles/bigquery.dataViewer + roles/bigquery.jobUser.
Analysis is static only (no sandbox copy); no data is copied or modified. `dry_run()` is available for ad-hoc cost/validity checks but is not part of the analysis pipeline yet.
"""
from __future__ import annotations

import json
from typing import Any

from ..models import Capabilities, Column, SchemaSnapshot, Table
from .base import Connector, ConnectorError


class BigQueryConnector(Connector):
    type = "bigquery"
    dialect = "bigquery"
    capabilities = Capabilities(
        sandbox_validation=False,
        read_only_enforced="Only SELECT is ever submitted. Use a viewer-only service account.",
        notes="Sandbox copy is not supported (cost/size); analysis is static only. Not tested against live BigQuery.",
    )

    def __init__(self, project: str, dataset: str, credentials_json: str | None = None, client=None):
        self.project, self.dataset = project, dataset
        if client is not None:
            self.client = client
            return
        try:
            from google.cloud import bigquery
        except ImportError as e:  # pragma: no cover
            raise ConnectorError("Install google-cloud-bigquery to use BigQuery") from e
        if credentials_json:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(json.loads(credentials_json))
            self.client = bigquery.Client(project=project, credentials=creds)
        else:
            self.client = bigquery.Client(project=project)

    def test(self) -> dict[str, Any]:
        self.client.get_dataset(f"{self.project}.{self.dataset}")
        return {"server": f"BigQuery {self.project}.{self.dataset}", "read_only": True}

    def discover(self) -> SchemaSnapshot:
        tables: list[Table] = []
        for item in self.client.list_tables(f"{self.project}.{self.dataset}"):
            t = self.client.get_table(item.reference)
            cols = [Column(name=f.name, type=f.field_type.upper(), nullable=f.mode != "REQUIRED") for f in t.schema]
            is_view = t.table_type == "VIEW"
            tables.append(
                Table(
                    name=t.table_id,
                    schema_name=self.dataset,
                    kind="view" if is_view else "table",
                    columns=cols,
                    definition=t.view_query if is_view else None,
                    row_count=None if is_view else t.num_rows,
                )
            )
        return SchemaSnapshot(dialect=self.dialect, tables=tables)

    def fetch_rows(self, table: str, limit: int):
        raise ConnectorError("BigQuery connector does not copy data; analysis is static only")

    def dry_run(self, sql: str) -> dict[str, Any]:
        from google.cloud import bigquery

        job = self.client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        return {"bytes_processed": job.total_bytes_processed}

    def query(self, sql: str, limit: int = 1000):
        from ..analysis.sql_parser import assert_single_select

        assert_single_select(sql, self.dialect)
        rows = self.client.query(sql).result(max_results=limit)
        return [f.name for f in rows.schema], [tuple(r.values()) for r in rows]
