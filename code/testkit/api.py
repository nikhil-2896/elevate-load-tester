"""HTTP endpoints of the testing platform, under /api/v2."""
import json
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request

from testkit import executor, ownership, registry, store
from testkit.criteria import CRITERIA, is_known
from testkit.models import Target
from testkit.report import render_html
from testkit.safety import UnsafeTarget, check_url
from testkit.selector import build_plan

bp = Blueprint("testkit", __name__, url_prefix="/api/v2")
registry.discover()
store.init_store()

MAX_ACTIVE_RUNS = 3
MAX_OPTIONS_BYTES = 20_000


def _bad(message, code=400):
    return jsonify({"error": message}), code


def _read_target(data):
    """Validates the request body. Returns (target, criteria, options) or an
    (error_response, None, None) tuple."""
    url = data.get("url")
    if not url or not isinstance(url, str):
        return _bad("url (string) is required"), None, None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _bad("url must be a valid http(s) URL"), None, None
    try:
        check_url(url, strict_dns=False)
    except UnsafeTarget as e:
        return _bad(str(e)), None, None
    openapi_url = data.get("openapi_url") or ""
    if openapi_url:
        if not isinstance(openapi_url, str):
            return _bad("openapi_url must be a string"), None, None
        try:
            check_url(openapi_url, strict_dns=False)
        except UnsafeTarget as e:
            return _bad("openapi_url: " + str(e)), None, None
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return _bad("criteria (non-empty list) is required"), None, None
    unknown = [c for c in criteria if not isinstance(c, str) or not is_known(c)]
    if unknown:
        return _bad(f"unknown criteria: {unknown}"), None, None
    options = data.get("options") or {}
    if not isinstance(options, dict) or not all(isinstance(v, dict) for v in options.values()):
        return _bad("options must be an object of per-module objects"), None, None
    if len(json.dumps(options)) > MAX_OPTIONS_BYTES:
        return _bad("options are too large"), None, None
    base = f"{parsed.scheme}://{parsed.netloc}"
    target = Target(base_url=base, openapi_url=openapi_url,
                    auth_token=str(data.get("auth_token") or ""),
                    ownership_verified=ownership.is_verified(base))
    return target, criteria, options


@bp.get("/criteria")
def criteria_endpoint():
    return jsonify([{"id": k, "label": v} for k, v in CRITERIA.items()])


@bp.get("/modules")
def modules_endpoint():
    return jsonify([{"id": m.id, "title": m.title, "criteria": sorted(m.criteria),
                     "requires": sorted(m.requires), "intrusive": m.intrusive, "cost": m.cost}
                    for m in registry.all_modules()])


@bp.post("/plan")
def plan_endpoint():
    target, criteria, _ = _read_target(request.get_json(silent=True) or {})
    if criteria is None:
        return target
    plan = build_plan(criteria, target)
    return jsonify({"ownership_verified": target.ownership_verified, **plan.to_dict()})


@bp.post("/runs")
def start_run_endpoint():
    target, criteria, options = _read_target(request.get_json(silent=True) or {})
    if criteria is None:
        return target
    active = [r for r in store.list_runs(50) if r["status"] in ("queued", "running")]
    if len(active) >= MAX_ACTIVE_RUNS:
        return _bad("too many tests are running; try again in a minute", 429)
    plan = build_plan(criteria, target)
    if not plan.selected:
        return jsonify({"error": "no test module applies to these criteria and inputs",
                        **plan.to_dict()}), 400
    run_id = executor.start_run(criteria, target, plan, options)
    return jsonify({"run_id": run_id, "status": "started", **plan.to_dict()}), 202


@bp.get("/runs")
def list_runs_endpoint():
    return jsonify({"runs": store.list_runs()})


@bp.get("/runs/<run_id>")
def get_run_endpoint(run_id):
    run = store.get_run(run_id)
    return jsonify(run) if run else _bad("run not found", 404)


@bp.get("/runs/<run_id>/report.html")
def report_endpoint(run_id):
    run = store.get_run(run_id)
    if not run:
        return _bad("run not found", 404)
    return Response(render_html(run), mimetype="text/html")


@bp.post("/ownership/token")
def ownership_token_endpoint():
    url = (request.get_json(silent=True) or {}).get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _bad("url must be a valid http(s) URL")
    token = ownership.issue_token(url)
    return jsonify({"host": ownership.host_of(url), "token": token,
                    "path": "/.well-known/testkit-verify",
                    "instructions": "Serve exactly this token as plain text at the path above, "
                                    "then call /api/v2/ownership/verify."})


@bp.post("/ownership/verify")
def ownership_verify_endpoint():
    url = (request.get_json(silent=True) or {}).get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _bad("url must be a valid http(s) URL")
    try:
        check_url(url, strict_dns=True)
    except UnsafeTarget as e:
        return _bad(str(e))
    return jsonify({"verified": ownership.verify(url)})