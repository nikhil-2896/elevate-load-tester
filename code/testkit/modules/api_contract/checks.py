"""The eight API-contract checks (T10.1 to T10.8)."""
import json
from dataclasses import dataclass, field

import requests
from openapi_spec_validator import validate as validate_spec

from testkit.models import Finding, Status
from testkit.modules.api_contract import spec as sp

_RANK = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


@dataclass
class Record:
    """What one documented operation answered."""
    label: str
    method: str
    path_template: str
    status: int = None
    content_type: str = ""
    headers: dict = field(default_factory=dict)
    body: str = ""
    error: str = ""
    response_key: str = None
    response_def: dict = None
    operation: dict = None


def summarise(check_id, title, items, fix, all_good):
    """items: [(label, Status, why)]. The finding takes the worst status."""
    if not items:
        return Finding(check_id, title, Status.SKIPPED, "nothing to check", fix_hint=fix)
    worst = max((s for _, s, _ in items), key=lambda s: _RANK[s])
    bad = [(label, s, why) for label, s, why in items if s != Status.PASS]
    if not bad:
        return Finding(check_id, title, Status.PASS, all_good)
    shown = "; ".join(f"{label}: {why}" for label, _, why in bad[:3])
    return Finding(check_id, title, worst, f"{len(bad)} of {len(items)} operations - {shown}",
                   {"operations": [{"operation": label, "rating": s.value, "problem": why}
                                   for label, s, why in bad[:8]]}, fix)


# ---- T10.1 -----------------------------------------------------------

def check_valid_spec(spec):
    title = "The API description is valid OpenAPI"
    fix = "Fix the document so it validates against the OpenAPI specification."
    try:
        validate_spec(spec)
    except Exception as e:  # noqa: BLE001 - the validator raises many types
        return Finding("T10.1", title, Status.FAIL, str(e).splitlines()[0][:200], fix_hint=fix)
    return Finding("T10.1", title, Status.PASS, "document validates")


# ---- T10.2 - T10.6 (read the records) --------------------------------

def check_reachable(records):
    items = []
    for r in records:
        has_params = "{" in r.path_template
        if r.status is None:
            items.append((r.label, Status.FAIL, f"no response ({r.error})"))
        elif r.status == 405:
            items.append((r.label, Status.FAIL, "method not allowed - documented but not implemented"))
        elif r.status == 404:
            items.append((r.label, Status.WARN if has_params else Status.FAIL,
                          "not found" + (" (sample id may not exist)" if has_params else "")))
        else:
            items.append((r.label, Status.PASS, ""))
    return summarise("T10.2", "Every documented operation exists", items,
                     "Implement the route, or remove it from the description.",
                     "all documented operations answered")


def check_status_declared(records):
    items = []
    for r in records:
        if r.status is None:
            continue
        ok = r.response_key is not None
        items.append((r.label, Status.PASS if ok else Status.FAIL,
                      f"answered {r.status}, which the description does not list"))
    return summarise("T10.3", "Response statuses are documented", items,
                     "Add the status to the operation's responses, or fix the code.",
                     "every status returned is documented")


def check_schema(spec, records):
    items = []
    for r in records:
        if r.response_def is None:
            continue
        schema = sp.response_json_schema(r.response_def)
        if schema is None:
            continue
        try:
            body = json.loads(r.body)
        except ValueError:
            items.append((r.label, Status.FAIL, "body is not valid JSON"))
            continue
        problem = sp.first_error(spec, schema, body)
        items.append((r.label, Status.FAIL if problem else Status.PASS, problem or ""))
    return summarise("T10.4", "Response bodies match their schemas", items,
                     "Make the response match the schema, or correct the schema.",
                     "every checked body matches its schema")


def check_content_type(records):
    items = []
    for r in records:
        if r.response_def is None or not r.response_def.get("content") or not r.body:
            continue
        declared = list(r.response_def["content"])
        ok = bool(r.content_type) and sp.media_allowed(declared, r.content_type)
        items.append((r.label, Status.PASS if ok else Status.FAIL,
                      f"returned '{r.content_type or 'no type'}', description says {declared}"))
    return summarise("T10.5", "Content types match the description", items,
                     "Return the media type the description promises.",
                     "content types match")


def check_headers(records):
    items = []
    for r in records:
        if r.response_def is None:
            continue
        required = [name for name, h in (r.response_def.get("headers") or {}).items()
                    if isinstance(h, dict) and h.get("required") and name.lower() != "content-type"]
        if not required:
            continue
        have = {k.lower() for k in r.headers}
        missing = [n for n in required if n.lower() not in have]
        items.append((r.label, Status.FAIL if missing else Status.PASS,
                      f"missing header(s): {', '.join(missing)}"))
    return summarise("T10.6", "Required response headers are present", items,
                     "Send every header the description marks as required.",
                     "required headers present")


# ---- T10.8 -----------------------------------------------------------

def check_breaking_changes(spec, baseline):
    title = "No breaking changes against the baseline"
    if not baseline:
        return Finding("T10.8", title, Status.SKIPPED, "no baseline description was supplied")
    problems = sp.diff_specs(baseline, spec)
    if not problems:
        return Finding("T10.8", title, Status.PASS, "nothing that would break existing clients")
    return Finding("T10.8", title, Status.FAIL,
                   f"{len(problems)} breaking change(s): " + "; ".join(problems[:3]),
                   {"changes": problems[:20]},
                   "Add new things beside the old ones instead of changing or removing them.")


def fetch_json(client, url, headers):
    """Returns (parsed_json, problem). One of the two is None."""
    try:
        resp = client.get(url, headers=headers)
    except requests.exceptions.RequestException as e:
        return None, f"could not fetch the description ({type(e).__name__})"
    if resp.status_code != 200:
        return None, f"the description URL answered {resp.status_code}"
    if len(resp.text) > 2_000_000:
        return None, "the description is larger than 2 MB"
    try:
        parsed = resp.json()
    except ValueError:
        return None, "the description is not JSON (YAML is not supported yet)"
    if not isinstance(parsed, dict):
        return None, "the description is not a JSON object"
    return parsed, None