"""JSON and HTML report export. HTML is generated with Jinja2 autoescape (no raw interpolation)."""
from __future__ import annotations

import json
from typing import Any

from jinja2 import Environment, select_autoescape

SCHEMA_VERSION = "1"

_ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_ENV.filters["pct"] = lambda v: "—" if v is None else f"{v * 100:.1f}%"
_ENV.filters["num"] = lambda v: "—" if v is None else (f"{v:,.2f}" if isinstance(v, float) else f"{v:,}")

_TEMPLATE = _ENV.from_string("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Missync report — {{ r.title }}</title>
<style>
:root{--bg:#fff;--fg:#1c2330;--muted:#5b6575;--line:#e3e7ee;--card:#f7f9fc;--critical:#9b1c1c;--high:#c2410c;--medium:#a16207;--low:#1d6fa5;--info:#5b6575}
@media (prefers-color-scheme:dark){:root{--bg:#10151d;--fg:#e6eaf1;--muted:#97a1b2;--line:#273041;--card:#171e29;--critical:#f87171;--high:#fb923c;--medium:#facc15;--low:#60a5fa;--info:#97a1b2}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:960px;margin:0 auto;padding:24px 16px}
h1{margin:0 0 4px}h2{margin-top:32px;border-bottom:1px solid var(--line);padding-bottom:6px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor;text-transform:uppercase}
.critical{color:var(--critical)}.high{color:var(--high)}.medium{color:var(--medium)}.low{color:var(--low)}.info{color:var(--info)}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left}
pre{background:var(--card);border:1px solid var(--line);padding:10px;border-radius:8px;overflow:auto;font-size:12px}
.tbl{overflow-x:auto}
</style></head><body>
<h1>{{ r.title }}</h1>
<div class="muted">Missync analysis {{ r.id }} · {{ r.created_at }} · dialect {{ r.dialect }}</div>
<div class="card"><strong>{{ r.summary.verdict }}</strong><br>
{% for k,v in r.summary.by_severity.items() %}{% if v %}<span class="badge {{k}}">{{ v }} {{ k }}</span> {% endif %}{% endfor %}
<span class="muted">{{ r.summary.verified }} verified · {{ r.summary.predicted }} predicted ·
lineage {{ 'complete' if r.summary.lineage_complete else 'INCOMPLETE' }}</span></div>

<h2>Proposed change</h2><pre>{{ r.sql }}</pre>

<h2>Findings</h2>
{% for f in r.findings %}
<div class="card"><span class="badge {{ f.severity }}">{{ f.severity }}</span>
<span class="badge info">{{ f.kind }}</span> <span class="muted">confidence: {{ f.confidence }}</span>
<h3 style="margin:6px 0">{{ f.id }} · {{ f.title }}</h3>
<div>{{ f.summary }}</div>
{% if f.possibly_intended %}<div class="muted">May be intended — a difference is not necessarily a defect.</div>{% endif %}
<div class="muted">Evidence basis: {{ f.confidence_reason }}</div>
{% if f.affected %}<div><strong>Affected:</strong> {{ f.affected|join(', ') }}</div>{% endif %}
{% if f.recommendation %}<div><strong>Recommended:</strong> {{ f.recommendation }}</div>{% endif %}
{% for l in f.limitations %}<div class="muted">Limitation: {{ l }}</div>{% endfor %}
<details><summary class="muted">Raw evidence</summary><pre>{{ f.evidence | tojson(indent=2) }}</pre></details></div>
{% else %}<p class="muted">No findings.</p>{% endfor %}

<h2>Schema differences</h2>
{% if r.schema_diff %}<div class="tbl"><table><tr><th>Change</th><th>Object</th><th>Detail</th></tr>
{% for d in r.schema_diff %}<tr><td>{{ d.change }}</td><td>{{ d.table }}{% if d.column %}.{{ d.column }}{% endif %}</td>
<td>{% if d.old and d.new and d.change=='type_changed' %}{{ d.old }} → {{ d.new }} ({{ d.compatibility }}){% elif d.type %}{{ d.type }}{% endif %}</td></tr>{% endfor %}
</table></div>{% else %}<p class="muted">No schema differences observed.</p>{% endif %}

<h2>Table comparison</h2>
{% if r.table_comparison %}<div class="tbl"><table><tr><th>Table</th><th>Rows before</th><th>Rows after</th><th>Δ</th></tr>
{% for c in r.table_comparison %}{% if c.status == 'compared' %}<tr><td>{{ c.table }}</td><td>{{ c.rows_before|num }}</td><td>{{ c.rows_after|num }}</td><td>{{ c.row_delta|num }}</td></tr>{% endif %}{% endfor %}
</table></div>{% else %}<p class="muted">Not available.</p>{% endif %}

<h2>Metrics</h2>
{% if r.metric_comparison %}<div class="tbl"><table><tr><th>Metric</th><th>Before</th><th>After</th><th>Δ %</th><th>Tolerance</th></tr>
{% for m in r.metric_comparison %}<tr><td>{{ m.name }}</td><td>{{ m.before|num }}</td><td>{{ m.after|num }}</td>
<td>{% if m.delta_pct is not none %}{{ '%+.2f'|format(m.delta_pct) }}%{% else %}{{ m.error or '—' }}{% endif %}</td><td>±{{ m.tolerance_pct }}%</td></tr>{% endfor %}
</table></div>{% else %}<p class="muted">No metrics were selected.</p>{% endif %}

<h2>Impact</h2>
<p>{% for n in r.graph.nodes %}{% if n.impacted or n.changed %}<span class="badge {{ 'high' if n.changed else 'medium' }}">{{ n.type }}: {{ n.label }}</span> {% endif %}{% endfor %}</p>
{% for n in r.graph.notes %}<div class="muted">{{ n }}</div>{% endfor %}

<h2>Limitations</h2>
<ul>{% for l in r.limitations %}<li>{{ l }}</li>{% else %}<li class="muted">None recorded.</li>{% endfor %}</ul>
<p class="muted">Predicted findings come from static analysis; verified findings were measured in an isolated copy of the data.
This report is evidence, not a guarantee that a change is safe.</p>
</body></html>""")


def to_json(result: dict[str, Any]) -> str:
    return json.dumps({"report_schema_version": SCHEMA_VERSION, "generator": "missync", **result}, indent=2, default=str)


def to_html(result: dict[str, Any]) -> str:

    def wrap(o):
        if isinstance(o, dict):
            return _D({k: wrap(v) for k, v in o.items()})
        if isinstance(o, list):
            return [wrap(v) for v in o]
        return o

    return _TEMPLATE.render(r=wrap(result))


class _D(dict):
    """dict with attribute access that returns None for missing keys (Jinja-friendly)."""

    def __getattr__(self, k):
        return self.get(k)
