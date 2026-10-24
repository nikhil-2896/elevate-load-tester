"""T11: the rate-limiting module, tested against apps with known limiters."""
import time
from email.utils import formatdate

import pytest
from flask import Flask, jsonify, request

from demo_target.app import create_app, serve
from testkit import executor, registry, store
from testkit.models import Status, Target
from testkit.modules.rate_limiting.module import RateLimiting, retry_after_seconds
from testkit.selector import build_plan


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")


def run_module(base, verified=True, token="", **options):
    options.setdefault("max_wait_s", 0)    # skip the recovery wait unless a test asks for it
    target = Target(base_url=base, auth_token=token, ownership_verified=verified)
    result = RateLimiting().run(target, options)
    return {f.check_id: f for f in result.findings}, result


def limiter_app(limit=3, window=1.0, status=429, headers=None, body=None,
                per_client=False, forever=False, crash=False, ok_headers=None):
    state = {}
    app = Flask("limiter")

    @app.route("/api", methods=["GET", "POST"])
    def api():
        key = request.headers.get("Authorization", "anon") if per_client else "all"
        now = time.monotonic()
        s = state.setdefault(key, {"start": now, "n": 0})
        if not forever and now - s["start"] >= window:
            s["start"], s["n"] = now, 0
        s["n"] += 1
        if s["n"] > limit:
            if crash:
                return "boom", 500
            resp = jsonify({"error": "rate_limited"}) if body is None else app.response_class(
                body, mimetype="text/plain")
            resp.status_code = status
            resp.headers.update(headers if headers is not None else {"Retry-After": "1"})
            return resp
        resp = jsonify({"ok": True})
        resp.headers.update(ok_headers or {})
        return resp

    return app


API = {"endpoint": {"method": "GET", "path": "/api"}}


# ---- safety -----------------------------------------------------------

def test_t11_1_refuses_to_run_without_verified_ownership():
    with serve(limiter_app()) as base:
        f, result = run_module(base, verified=False, **API)
    assert result.status == Status.SKIPPED and "ownership" in f["T11.0"].detail


def test_t11_2_private_targets_are_refused_unless_allowed(monkeypatch):
    monkeypatch.delenv("TESTKIT_ALLOW_PRIVATE")
    f, result = run_module("http://127.0.0.1:8100")
    assert result.status == Status.SKIPPED and "public" in f["T11.0"].detail


def test_t11_3_unreachable_target_is_a_failure():
    f, result = run_module("http://127.0.0.1:9")
    assert result.status == Status.FAIL and list(f) == ["T11.0"]


def test_t11_4_request_ceiling_is_respected():
    with serve(limiter_app(limit=10_000)) as base:
        f, result = run_module(base, max_requests=12, **API)
    assert result.metrics["requests"] <= 12 + 5
    assert f["T11.1"].status == Status.WARN


# ---- T11.1 - T11.4, T11.6, T11.7 against the demo target ---------------

def test_t11_5_the_demo_limited_endpoint_behaves_like_a_good_limiter():
    with serve(create_app()) as base:
        f, result = run_module(base, endpoint={"method": "GET", "path": "/limited"}, max_wait_s=30)
    assert f["T11.1"].status == Status.PASS and "after 5 requests" in f["T11.1"].detail
    assert f["T11.2"].status == Status.PASS
    assert f["T11.3"].status == Status.PASS
    assert f["T11.4"].status == Status.WARN          # no RateLimit headers
    assert f["T11.6"].status == Status.PASS
    assert f["T11.7"].status == Status.PASS
    assert result.metrics["allowed_before_limit"] == 5


def test_t11_6_an_unlimited_endpoint_warns_and_skips_the_dependent_checks():
    with serve(create_app()) as base:
        f, _ = run_module(base, endpoint={"method": "GET", "path": "/unlimited"}, max_requests=30)
    assert f["T11.1"].status == Status.WARN
    for check in ("T11.2", "T11.3", "T11.6", "T11.7"):
        assert f[check].status == Status.SKIPPED


# ---- T11.2 status codes ------------------------------------------------

def test_t11_7_a_503_limiter_warns_and_crashing_under_load_fails():
    with serve(limiter_app(status=503)) as base:
        f, _ = run_module(base, **API)
    assert f["T11.2"].status == Status.WARN and "503" in f["T11.2"].detail
    with serve(limiter_app(crash=True)) as base:
        f, _ = run_module(base, **API)
    assert f["T11.2"].status == Status.FAIL


# ---- T11.3 Retry-After -------------------------------------------------

def test_t11_8_retry_after_missing_invalid_or_http_date():
    with serve(limiter_app(headers={})) as base:
        f, _ = run_module(base, **API)
    assert f["T11.3"].status == Status.WARN and "no Retry-After" in f["T11.3"].detail
    with serve(limiter_app(headers={"Retry-After": "soon"})) as base:
        f, _ = run_module(base, **API)
    assert f["T11.3"].status == Status.WARN and "neither" in f["T11.3"].detail
    date = formatdate(time.time() + 1, usegmt=True)
    with serve(limiter_app(headers={"Retry-After": date})) as base:
        f, _ = run_module(base, **API)
    assert f["T11.3"].status == Status.PASS


def test_t11_9_retry_after_parser():
    assert retry_after_seconds("30") == 30
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("garbage") is None
    assert 0 <= retry_after_seconds(formatdate(time.time() + 60, usegmt=True)) <= 60
    assert retry_after_seconds(formatdate(time.time() - 60, usegmt=True)) == 0


# ---- T11.4 headers -----------------------------------------------------

def test_t11_10_ratelimit_headers_are_recognised():
    for header in ("X-RateLimit-Limit", "RateLimit-Remaining"):
        with serve(limiter_app(ok_headers={header: "3"})) as base:
            f, _ = run_module(base, **API)
        assert f["T11.4"].status == Status.PASS, header


# ---- T11.5 documented limit --------------------------------------------

def test_t11_11_documented_limit_is_compared_with_the_observed_one():
    with serve(limiter_app(limit=5, window=5)) as base:
        f, _ = run_module(base, documented_limit=5, max_wait_s=0, **API)
    assert f["T11.5"].status == Status.PASS
    with serve(limiter_app(limit=5, window=5)) as base:
        f, _ = run_module(base, documented_limit=50, max_wait_s=0, **API)
    assert f["T11.5"].status == Status.WARN
    with serve(limiter_app(limit=5, window=5)) as base:
        f, _ = run_module(base, documented_limit=2, max_wait_s=0, **API)
    assert f["T11.5"].status == Status.FAIL
    with serve(limiter_app(limit=5, window=5)) as base:
        f, _ = run_module(base, max_wait_s=0, **API)
    assert f["T11.5"].status == Status.SKIPPED


# ---- T11.6 recovery ----------------------------------------------------

def test_t11_12_a_service_that_never_recovers_fails():
    with serve(limiter_app(forever=True)) as base:
        f, _ = run_module(base, max_wait_s=30, **API)
    assert f["T11.6"].status == Status.FAIL and "still throttled" in f["T11.6"].detail


def test_t11_13_a_very_long_retry_after_skips_the_waiting():
    started = time.monotonic()
    with serve(limiter_app(headers={"Retry-After": "3600"})) as base:
        f, _ = run_module(base, max_wait_s=5, **API)
    assert f["T11.6"].status == Status.WARN and "not checked" in f["T11.6"].detail
    assert time.monotonic() - started < 5


# ---- T11.7 throttled response quality ----------------------------------

def test_t11_14_empty_throttled_body_warns():
    with serve(limiter_app(body="", window=5)) as base:
        f, _ = run_module(base, max_wait_s=0, **API)
    assert f["T11.7"].status == Status.WARN and "empty" in f["T11.7"].detail


# ---- T11.8 sensitive endpoints -----------------------------------------

def two_endpoint_app(general, sensitive):
    app = Flask("two")
    counters = {"/api": 0, "/login": 0}
    limits = {"/api": general, "/login": sensitive}

    def make(path):
        def view():
            counters[path] += 1
            if limits[path] is not None and counters[path] > limits[path]:
                resp = jsonify({"error": "rate_limited"})
                resp.status_code = 429
                resp.headers["Retry-After"] = "1"
                return resp
            return jsonify({"ok": True})
        view.__name__ = "v" + path.strip("/")
        app.add_url_rule(path, view_func=view, methods=["GET", "POST"])

    make("/api")
    make("/login")
    return app


def test_t11_15_sensitive_endpoint_must_be_limited_more_strictly():
    sens = {"method": "POST", "path": "/login", "body": {"u": "x"}}
    for general, sensitive, expected in ((6, 2, Status.PASS), (3, 8, Status.WARN),
                                          (3, None, Status.WARN)):
        with serve(two_endpoint_app(general, sensitive)) as base:
            f, _ = run_module(base, sensitive_endpoint=sens, max_wait_s=0, **API)
        assert f["T11.8"].status == expected, (general, sensitive)


def test_t11_16_sensitive_check_is_skipped_without_the_option():
    with serve(limiter_app(window=5)) as base:
        f, _ = run_module(base, max_wait_s=0, **API)
    assert f["T11.8"].status == Status.SKIPPED


# ---- T11.9 isolation ---------------------------------------------------

def test_t11_17_per_client_limits_pass_and_a_global_limit_warns():
    with serve(limiter_app(per_client=True, window=5)) as base:
        f, _ = run_module(base, token="alice", second_token="bob", max_wait_s=0, **API)
    assert f["T11.9"].status == Status.PASS
    with serve(limiter_app(per_client=False, window=5)) as base:
        f, _ = run_module(base, token="alice", second_token="bob", max_wait_s=0, **API)
    assert f["T11.9"].status == Status.WARN and "global" in f["T11.9"].detail
    with serve(limiter_app(window=5)) as base:
        f, _ = run_module(base, max_wait_s=0, **API)
    assert f["T11.9"].status == Status.SKIPPED


# ---- whole module ------------------------------------------------------

def test_t11_18_findings_come_back_in_check_order():
    with serve(limiter_app(window=5)) as base:
        _, result = run_module(base, max_wait_s=0, **API)
    numbers = [int(x.check_id.split(".")[1]) for x in result.findings]
    assert numbers == sorted(numbers)


def test_t11_19_selected_only_for_verified_owners():
    assert "rate_limiting" in [m.id for m in registry.discover()]
    verified = build_plan({"abuse-protection"}, Target(base_url="http://x", ownership_verified=True))
    assert "rate_limiting" in [i.module_id for i in verified.selected]
    unverified = build_plan({"abuse-protection"}, Target(base_url="http://x"))
    assert "rate_limiting" not in [i.module_id for i in unverified.selected]
    reasons = {s.module_id: s.reason for s in unverified.skipped}
    assert "ownership" in reasons["rate_limiting"]


def test_t11_20_runs_end_to_end_through_the_executor_and_store():
    with serve(create_app()) as base:
        target = Target(base_url=base, ownership_verified=True)
        plan = build_plan({"abuse-protection"}, target)
        run_id = executor.start_run(
            {"abuse-protection"}, target, plan,
            options={"rate_limiting": {"endpoint": {"method": "GET", "path": "/limited"}}},
            background=False)
    run = store.get_run(run_id)
    result = next(r for r in run["results"] if r["module"] == "rate_limiting")
    findings = {f["check_id"]: f for f in result["findings"]}
    assert run["status"] == "done" and findings["T11.1"]["status"] == "pass"