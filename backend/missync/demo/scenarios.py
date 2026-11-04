"""Deterministic demo scenarios. They run through the same engine as any user analysis."""
from __future__ import annotations

from typing import Any

REVENUE = {"name": "Total completed revenue", "sql": "SELECT SUM(revenue) FROM v_daily_revenue", "tolerance_pct": 1.0}
ORDERS = {"name": "Completed order count", "sql": "SELECT SUM(orders) FROM v_daily_revenue", "tolerance_pct": 1.0}

SCENARIOS: dict[str, dict[str, Any]] = {
    "type-change": {
        "title": "Type change: orders.amount DECIMAL → INTEGER",
        "description": "A cleanup migration narrows a money column. Cents are silently rounded and dependent views and assets are flagged.",
        "sql": "ALTER TABLE orders ALTER COLUMN amount TYPE INTEGER;",
        "metrics": [REVENUE],
        "keys": {"orders": ["order_id"]},
    },
    "missing-records": {
        "title": "Missing records: cleanup deletes more than intended",
        "description": "A 'remove test accounts' delete matches real customers by country. Records disappear and joined views shrink.",
        "sql": "DELETE FROM customers WHERE email LIKE '%shop-demo.test' AND country IN ('BR', 'IN');",
        "metrics": [{"name": "Rows visible in support console", "sql": "SELECT COUNT(*) FROM v_order_details", "tolerance_pct": 1.0}],
        "keys": {"customers": ["customer_id"]},
    },
    "metric-drift": {
        "title": "Metric drift: revenue view now includes refunds",
        "description": "A view is redefined with a broader status filter. Nothing breaks structurally, but the headline revenue number moves.",
        "sql": ("CREATE OR REPLACE VIEW v_daily_revenue AS\n"
                "SELECT order_date, COUNT(*) AS orders, SUM(amount) AS revenue\n"
                "FROM orders WHERE status IN ('completed', 'refunded')\n"
                "GROUP BY order_date;"),
        "metrics": [REVENUE, ORDERS],
        "keys": {"orders": ["order_id"]},
    },
    "data-quality": {
        "title": "Data-quality regression: segment backfill via lookup",
        "description": "A backfill joins to a lookup that only covers some countries, turning populated values into NULLs.",
        "sql": ("UPDATE customers\n"
                "SET segment = (SELECT m.segment FROM segment_map m WHERE m.country = customers.country);"),
        "metrics": [{"name": "Customers with a segment", "sql": "SELECT COUNT(segment) FROM customers", "tolerance_pct": 1.0}],
        "keys": {"customers": ["customer_id"]},
    },
}


def scenario_request(scenario_id: str, connection_id: str) -> dict[str, Any]:
    s = SCENARIOS[scenario_id]
    return {
        "connection_id": connection_id, "sql": s["sql"], "title": s["title"], "sql_dialect": "postgres",
        "metrics": s["metrics"], "keys": s["keys"],
    }
