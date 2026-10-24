"""A self-contained, printable HTML report for one run."""
from html import escape
import json

ORDER = {"error": 0, "fail": 1, "warn": 2, "pass": 3, "skipped": 4}
COLOURS = {"pass": "#1a7f37", "warn": "#9a6700", "fail": "#cf222e", "error": "#8250df",
           "skipped": "#6e7781"}
LABELS = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "error": "ERROR", "skipped": "SKIPPED"}


def _badge(status):
    return (f'<span class="badge" style="background:{COLOURS.get(status, "#6e7781")}">'
            f'{LABELS.get(status, escape(str(status)))}</span>')


def counts(run):
    tally = {k: 0 for k in ORDER}
    for result in run.get("results", []):
        for f in result["findings"]:
            tally[f["status"]] = tally.get(f["status"], 0) + 1
    return tally


def render_html(run):
    tally = counts(run)
    verdict = run.get("verdict") or ("running" if run["status"] != "failed" else "error")
    summary = " ".join(f'{_badge(k)} {v}' for k, v in tally.items() if v)
    sections = []
    for result in run.get("results", []):
        findings = sorted(result["findings"], key=lambda f: ORDER.get(f["status"], 9))
        rows = []
        for f in findings:
            extra = ""
            if f.get("fix_hint"):
                extra += f'<div class="fix"><b>How to fix:</b> {escape(f["fix_hint"])}</div>'
            if f.get("evidence"):
                extra += f'<pre>{escape(json.dumps(f["evidence"], indent=2)[:1500])}</pre>'
            rows.append(f'<tr><td>{_badge(f["status"])}</td><td><code>{escape(f["check_id"])}</code></td>'
                        f'<td><b>{escape(f["title"])}</b><div>{escape(f["detail"])}</div>{extra}</td></tr>')
        metrics = ", ".join(f"{escape(str(k))}: {escape(str(v))}" for k, v in result["metrics"].items())
        sections.append(
            f'<section><h2>{escape(result["module"])} {_badge(result["status"])}</h2>'
            f'<p class="meta">{result["duration_s"]:.1f}s{" · " + metrics if metrics else ""}</p>'
            f'<table>{"".join(rows)}</table></section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test report {escape(run["run_id"][:8])}</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1f2328}}
.badge{{color:#fff;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:600}}
.banner{{padding:1rem 1.25rem;border-radius:8px;color:#fff;margin:1rem 0}}
table{{width:100%;border-collapse:collapse}}td{{vertical-align:top;padding:8px;border-top:1px solid #d0d7de}}
.meta{{color:#656d76;margin-top:-8px}}.fix{{color:#1a7f37;margin-top:4px}}
pre{{background:#f6f8fa;padding:8px;overflow:auto;font-size:12px}}code{{font-size:12px}}
@media print{{body{{margin:0}}}}</style></head><body>
<h1>Software test report</h1>
<p>Target: <b>{escape(run["target_url"])}</b><br>Criteria: {escape(", ".join(run["criteria"]))}<br>
Started: {escape(str(run["created_at"]))} UTC · Status: {escape(run["status"])}</p>
<div class="banner" style="background:{COLOURS.get(verdict, "#6e7781")}">
Overall verdict: <b>{escape(verdict.upper())}</b> &nbsp; {summary}</div>
{"".join(sections)}</body></html>"""