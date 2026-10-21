"""The twelve error-handling checks. Each takes a Context and returns one
Finding. Finding ids are T9.1 to T9.12 (the feature number is 9)."""
import json
import re
import secrets
from dataclasses import dataclass, field

from testkit.models import Finding, Status

BODY_METHODS = ("POST", "PUT", "PATCH")

SQLI = "' OR '1'='1"
XSS = "<script>alert(1)</script>"
TRAVERSAL = "../../etc/passwd"
PAYLOADS = (SQLI, XSS, TRAVERSAL)

LEAK_PATTERNS = {
    "Python traceback": r"Traceback \(most recent call last\)",
    "stack frame": r'File "[^"]+", line \d+',
    "Java stack frame": r"\bat [\w.$]+\([\w]+\.java:\d+\)",
    "JavaScript stack frame": r"\bat .+\.js:\d+:\d+",
    "database error": r"sqlalchemy|psycopg2|sqlite3\.\w*Error|pymysql|SQLSTATE|ORA-\d{4,5}|SequelizeDatabaseError",
    "SQL text": r"\bSELECT\b.+\bFROM\b",
    "file path": r"(?:/usr/|/var/|/srv/|/home/|/app/|/opt/)[\w./-]+|[A-Za-z]:\\\\[\w\\.-]+",
    "exception class": r"\b\w+(?:Exception|Error)\b: ",
}


@dataclass
class Context:
    prober: object
    endpoints: list                 # [{"method","path","body"}]
    has_token: bool
    slow_error_s: float = 2.0
    notes: list = field(default_factory=list)

    @property
    def body_endpoints(self):
        return [e for e in self.endpoints if e["method"] in BODY_METHODS]

    @property
    def sample_endpoints(self):
        return [e for e in self.body_endpoints if isinstance(e.get("body"), dict) and e["body"]]


# ---- helpers ---------------------------------------------------------

_RANK = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


def _judge(check_id, title, probes, classify, fix_hint, all_good):
    """Classifies each probe PASS/WARN/FAIL; the finding takes the worst."""
    if not probes:
        return Finding(check_id, title, Status.SKIPPED, "nothing to probe", fix_hint=fix_hint)
    rated = [(p, classify(p)) for p in probes]
    worst = max((s for _, s in rated), key=lambda s: _RANK[s])
    bad = [(p, s) for p, s in rated if s != Status.PASS]
    if not bad:
        detail = all_good
    else:
        shown = "; ".join(f"{p.label} -> {p.status or p.error}" for p, _ in bad[:3])
        detail = f"{len(bad)} of {len(probes)} probes: {shown}"
    evidence = {"probes": [{"label": p.label, "status": p.status, "error": p.error,
                            "rating": s.value} for p, s in bad[:8]]}
    return Finding(check_id, title, worst, detail, evidence, fix_hint if bad else "")


def _must_reject(p):
    """Bad input should draw a 4xx answer."""
    if p.status is None or p.status >= 500:
        return Status.FAIL
    return Status.PASS if 400 <= p.status < 500 else Status.WARN


def _must_not_crash(p):
    return Status.FAIL if (p.status is None or p.status >= 500) else Status.PASS


def _json_post(ctx, label, endpoint, body):
    return ctx.prober.send(label, endpoint["method"], endpoint["path"], json=body)


def _wrong_type(value):
    if isinstance(value, bool):
        return "yes"
    if isinstance(value, (int, float)):
        return "abc"
    if isinstance(value, str) or value is None:
        return 12345
    return "abc"


def _boundary_values(value):
    values = [None]
    if isinstance(value, str):
        values += ["", "A" * 10000, "\u65e5\u672c\u8a9e\U0001f642", "\u0000"]
    elif isinstance(value, bool):
        pass
    elif isinstance(value, (int, float)):
        values += [-1, 0, 2 ** 63, -(2 ** 63) - 1]
    elif isinstance(value, list):
        values += [[], [None]]
    elif isinstance(value, dict):
        values += [{}]
    return values


# ---- checks ----------------------------------------------------------

def t9_1_malformed_json(ctx):
    probes = [ctx.prober.send(f"{e['method']} {e['path']} malformed JSON", e["method"],
                              e["path"], data="{oops", headers={"Content-Type": "application/json"})
              for e in ctx.body_endpoints]
    return _judge("T9.1", "Malformed JSON is rejected, not crashed on", probes, _must_reject,
                  "Wrap request parsing so invalid JSON returns 400, never an unhandled error.",
                  "every endpoint answered malformed JSON with a 4xx")


def t9_2_wrong_content_type(ctx):
    probes = [ctx.prober.send(f"{e['method']} {e['path']} text/plain", e["method"], e["path"],
                              data=json.dumps(e.get("body") or {}),
                              headers={"Content-Type": "text/plain"})
              for e in ctx.body_endpoints]
    return _judge("T9.2", "Wrong Content-Type is rejected", probes, _must_reject,
                  "Answer 415 (or 400) when the Content-Type is not the one you accept.",
                  "wrong content types drew a 4xx")


def t9_3_missing_fields(ctx):
    probes = []
    for e in ctx.sample_endpoints:
        for key in e["body"]:
            body = {k: v for k, v in e["body"].items() if k != key}
            probes.append(_json_post(ctx, f"{e['path']} without '{key}'", e, body))
    return _judge("T9.3", "Missing fields are rejected with a clear 4xx", probes, _must_reject,
                  "Validate required fields and answer 400 or 422 naming the field. "
                  "A 2xx here may only mean the field is optional.",
                  "every missing field drew a 4xx")


def t9_4_wrong_types(ctx):
    probes = []
    for e in ctx.sample_endpoints:
        for key, value in e["body"].items():
            body = dict(e["body"], **{key: _wrong_type(value)})
            probes.append(_json_post(ctx, f"{e['path']} '{key}' wrong type", e, body))
    return _judge("T9.4", "Wrong data types are rejected", probes, _must_reject,
                  "Check field types before using them; answer 400 or 422.",
                  "every wrong type drew a 4xx")


def t9_5_boundary_values(ctx):
    probes = []
    for e in ctx.sample_endpoints:
        for key, value in e["body"].items():
            for i, candidate in enumerate(_boundary_values(value)):
                body = dict(e["body"], **{key: candidate})
                probes.append(_json_post(ctx, f"{e['path']} '{key}' boundary #{i + 1}", e, body))
    return _judge("T9.5", "Boundary values never crash the service", probes, _must_not_crash,
                  "Handle empty, huge, null, unicode and extreme numeric values; "
                  "a 4xx is fine, a 5xx is not.",
                  "no boundary value caused a server error")


def t9_6_oversized_body(ctx):
    targets = ctx.body_endpoints[:1]
    big = '{"data":"' + "A" * (2 * 1024 * 1024) + '"}'
    probes = [ctx.prober.send(f"{e['method']} {e['path']} 2 MiB body", e["method"], e["path"],
                              data=big, headers={"Content-Type": "application/json"})
              for e in targets]

    def classify(p):
        if p.status is None or p.status >= 500:
            return Status.FAIL
        return Status.PASS if p.status == 413 else Status.WARN

    return _judge("T9.6", "Oversized body is refused with 413", probes, classify,
                  "Set a maximum request size (answer 413) so one request cannot exhaust memory.",
                  "a 2 MiB body drew a 413")


def t9_7_unknown_route_and_method(ctx):
    first = ctx.endpoints[0]
    ghost = "/testkit-no-such-route-" + secrets.token_hex(4)
    unknown = ctx.prober.send("unknown route", "GET", ghost)
    odd_method = ctx.prober.send(f"unknown method on {first['path']}", "TESTKIT", first["path"])

    def classify(p):
        if p.status is None or p.status >= 500:
            return Status.FAIL
        if p.label == "unknown route":
            return Status.PASS if p.status in (404, 401, 403) else Status.WARN
        return Status.PASS if p.status in (405, 501) else Status.WARN

    return _judge("T9.7", "Unknown routes answer 404 and unknown methods 405",
                  [unknown, odd_method], classify,
                  "Return 404 for unknown paths and 405 for unsupported methods; "
                  "a catch-all that answers 200 hides mistakes.",
                  "unknown route gave a 404 and unknown method a 405")


def t9_8_injection_strings(ctx):
    probes = []
    for e in ctx.sample_endpoints:
        for key, value in e["body"].items():
            if isinstance(value, str):
                for payload in PAYLOADS:
                    body = dict(e["body"], **{key: payload})
                    probes.append(_json_post(ctx, f"{e['path']} '{key}' injection", e, body))
    for e in ctx.endpoints:
        if e["method"] == "GET":
            for payload in PAYLOADS:
                probes.append(ctx.prober.send(f"GET {e['path']} ?q= injection", "GET",
                                              e["path"], params={"q": payload}))

    def classify(p):
        if p.status is None or p.status >= 500:
            return Status.FAIL
        if "html" in p.content_type.lower() and XSS in p.body:
            return Status.FAIL     # script reflected unescaped in an HTML page
        return Status.PASS

    return _judge("T9.8", "Injection-style input is handled safely", probes, classify,
                  "Treat input as data: use parameterised queries and escape output.",
                  "no server error and no unescaped reflection")


def t9_9_no_leakage(ctx):
    leaks = []
    for p in ctx.prober.log:
        if not p.is_error_response:
            continue
        for name, pattern in LEAK_PATTERNS.items():
            m = re.search(pattern, p.body, re.IGNORECASE | re.DOTALL)
            if m:
                leaks.append((p, name, p.body[max(0, m.start() - 20):m.end() + 40]))
    errors = [p for p in ctx.prober.log if p.is_error_response]
    if not errors:
        return Finding("T9.9", "Error responses do not leak internals", Status.SKIPPED,
                       "no error responses were seen")
    if not leaks:
        return Finding("T9.9", "Error responses do not leak internals", Status.PASS,
                       f"{len(errors)} error responses checked, nothing sensitive in them")
    return Finding(
        "T9.9", "Error responses do not leak internals", Status.FAIL,
        f"{len(leaks)} error responses exposed internals: "
        + "; ".join(f"{p.label} ({name})" for p, name, _ in leaks[:3]),
        {"leaks": [{"probe": p.label, "kind": name, "snippet": s[:120]}
                   for p, name, s in leaks[:5]]},
        "Log the details on the server; send clients a short, generic message.")


def t9_10_consistent_envelope(ctx):
    errors = [p for p in ctx.prober.log if p.is_error_response]
    if len(errors) < 2:
        return Finding("T9.10", "Errors share one shape", Status.SKIPPED,
                       "fewer than two error responses were seen")
    shapes, non_json = [], []
    for p in errors:
        try:
            parsed = json.loads(p.body)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            shapes.append(set(parsed))
        else:
            non_json.append(p)
    hint = "Send every error as JSON with the same top-level keys, for example {\"error\": ...}."
    if non_json and shapes:
        return Finding("T9.10", "Errors share one shape", Status.WARN,
                       f"{len(non_json)} of {len(errors)} error responses are not JSON "
                       f"(first: {non_json[0].label})", {}, hint)
    if shapes and not set.intersection(*shapes):
        return Finding("T9.10", "Errors share one shape", Status.WARN,
                       "JSON error bodies have no key in common", {}, hint)
    return Finding("T9.10", "Errors share one shape", Status.PASS,
                   f"{len(errors)} error responses share one format")


def t9_11_auth_errors(ctx):
    title = "Missing or invalid credentials are refused"
    if not ctx.has_token:
        return Finding("T9.11", title, Status.SKIPPED, "no auth token was supplied")
    hint = "Answer 401 for a missing or invalid token and 403 when the token lacks rights."
    probes = []
    for e in ctx.endpoints:
        probes.append(ctx.prober.send(f"{e['method']} {e['path']} no token", e["method"],
                                      e["path"], auth="none", json=e.get("body")))
        probes.append(ctx.prober.send(f"{e['method']} {e['path']} invalid token", e["method"],
                                      e["path"], auth="invalid-token-" + secrets.token_hex(4),
                                      json=e.get("body")))

    def classify(p):
        if p.status is None or p.status >= 500:
            return Status.FAIL
        if p.status in (401, 403):
            return Status.PASS
        # A 2xx with no token may be a public endpoint (warn); with a fake
        # token it means the service accepts credentials it should not.
        return Status.FAIL if "invalid token" in p.label else Status.WARN

    return _judge("T9.11", title, probes, classify, hint, "credentials are checked")


def t9_12_errors_are_fast(ctx):
    errors = [p for p in ctx.prober.log if p.is_error_response]
    if not errors:
        return Finding("T9.12", "Error responses are fast", Status.SKIPPED,
                       "no error responses were seen")
    slow = [p for p in errors if p.elapsed > ctx.slow_error_s]
    if not slow:
        return Finding("T9.12", "Error responses are fast", Status.PASS,
                       f"all {len(errors)} error responses took under {ctx.slow_error_s:g}s")
    return Finding("T9.12", "Error responses are fast", Status.WARN,
                   f"{len(slow)} of {len(errors)} error responses took over "
                   f"{ctx.slow_error_s:g}s (slowest: {max(p.elapsed for p in slow):.1f}s)",
                   {"slow": [{"probe": p.label, "seconds": round(p.elapsed, 2)} for p in slow[:5]]},
                   "Reject bad input before doing expensive work.")


# Order matters: the analysis checks (9 to 12) read the probes sent earlier.
ALL_CHECKS = [
    t9_1_malformed_json, t9_2_wrong_content_type, t9_3_missing_fields, t9_4_wrong_types,
    t9_5_boundary_values, t9_6_oversized_body, t9_7_unknown_route_and_method,
    t9_8_injection_strings, t9_11_auth_errors,
    t9_9_no_leakage, t9_10_consistent_envelope, t9_12_errors_are_fast,
]