"""T9: the error-handling module, tested against apps whose right answer is
known in advance."""
import time

import pytest
from flask import Flask, jsonify, request

from demo_target.app import create_app, serve
from testkit import executor, registry, store
from testkit.models import Status, Target
from testkit.modules.error_handling.module import ErrorHandling
from testkit.selector import build_plan


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")


def run_module(base, endpoints=None, token="", **options):
    opts = dict(options)
    if endpoints is not None:
        opts["endpoints"] = endpoints
    result = ErrorHandling().run(Target(base_url=base, auth_token=token), opts)
    return {f.check_id: f for f in result.findings}, result


ITEMS = {"method": "POST", "path": "/items", "body": {"name": "widget"}}


def well_behaved_app():
    """Everything an API should do: JSON errors with one shape, 413 limit."""
    app = Flask("good")
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.errorhandler(Exception)
    def any_error(e):
        code = getattr(e, "code", 500) or 500
        return jsonify({"error": "request_failed"}), code

    @app.post("/items")
    def items():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            return jsonify({"error": "invalid"}), 422
        return jsonify({"ok": True}), 201

    @app.get("/ping")
    def ping():
        return jsonify({"ok": True})

    return app


# ---- T9.1 - T9.5 input handling ---------------------------------------

def test_t9_1_malformed_json_passes_when_rejected_and_fails_when_it_crashes():
    with serve(create_app()) as base:
        good, _ = run_module(base, [ITEMS])
        assert good["T9.1"].status == Status.PASS
        bad, _ = run_module(base, [{"method": "POST", "path": "/crash", "body": {"a": 1}}])
        assert bad["T9.1"].status == Status.FAIL
        assert "500" in bad["T9.1"].detail


def test_t9_2_wrong_content_type_is_a_warning_when_accepted():
    with serve(create_app()) as base:
        ok, _ = run_module(base, [ITEMS])
        assert ok["T9.2"].status == Status.PASS
        lax, _ = run_module(base, [{"method": "POST", "path": "/crash", "body": {"a": 1}}])
        assert lax["T9.2"].status == Status.WARN


def test_t9_3_missing_fields_are_rejected():
    with serve(create_app()) as base:
        f, _ = run_module(base, [ITEMS])
        assert f["T9.3"].status == Status.PASS


def test_t9_4_wrong_types_are_rejected():
    with serve(create_app()) as base:
        f, _ = run_module(base, [ITEMS])
        assert f["T9.4"].status == Status.PASS


def test_t9_5_boundary_value_that_causes_a_500_is_a_failure():
    app = Flask("fragile")

    @app.post("/items")
    def items():
        name = request.get_json()["name"]
        return jsonify({"first": name[0]})   # IndexError on the empty string

    with serve(app) as base:
        f, _ = run_module(base, [ITEMS])
    assert f["T9.5"].status == Status.FAIL
    assert "boundary" in f["T9.5"].evidence["probes"][0]["label"]


def test_t9_5b_body_checks_are_skipped_without_a_sample_body():
    with serve(create_app()) as base:
        f, _ = run_module(base, [{"method": "POST", "path": "/items"}])
    for check in ("T9.3", "T9.4", "T9.5", "T9.8"):
        assert f[check].status in (Status.SKIPPED, Status.PASS)
    assert f["T9.3"].status == Status.SKIPPED


# ---- T9.6 size limit --------------------------------------------------

def test_t9_6_oversized_body_needs_a_413():
    with serve(well_behaved_app()) as base:
        good, _ = run_module(base, [ITEMS])
        assert good["T9.6"].status == Status.PASS
    with serve(create_app()) as base:
        unlimited, _ = run_module(base, [ITEMS])
        assert unlimited["T9.6"].status == Status.WARN


# ---- T9.7 routes and methods ------------------------------------------

def test_t9_7_unknown_route_and_method():
    with serve(create_app()) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/good"}])
        assert f["T9.7"].status == Status.PASS
    catch_all = Flask("catchall")

    @catch_all.route("/", defaults={"p": ""}, methods=["GET", "TESTKIT"])
    @catch_all.route("/<path:p>", methods=["GET", "TESTKIT"])
    def anything(p):
        return "hello"

    with serve(catch_all) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/"}])
    assert f["T9.7"].status == Status.WARN


# ---- T9.8 injection ---------------------------------------------------

def test_t9_8_injection_is_safe_on_a_validating_app_and_fails_on_reflection():
    with serve(create_app()) as base:
        f, _ = run_module(base, [ITEMS, {"method": "GET", "path": "/good"}])
        assert f["T9.8"].status == Status.PASS
    reflective = Flask("reflect")

    @reflective.get("/search")
    def search():
        return f"<html>You searched for {request.args.get('q', '')}</html>"

    with serve(reflective) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/search"}])
    assert f["T9.8"].status == Status.FAIL


# ---- T9.9 leakage -----------------------------------------------------

def test_t9_9_traceback_in_an_error_body_is_a_failure():
    with serve(create_app()) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/leaky"}])
    assert f["T9.9"].status == Status.FAIL
    kinds = {leak["kind"] for leak in f["T9.9"].evidence["leaks"]}
    assert "Python traceback" in kinds


def test_t9_9b_clean_error_bodies_pass():
    with serve(well_behaved_app()) as base:
        f, _ = run_module(base, [ITEMS])
    assert f["T9.9"].status == Status.PASS


# ---- T9.10 envelope ---------------------------------------------------

def test_t9_10_html_errors_mixed_with_json_errors_warn():
    with serve(create_app()) as base:     # JSON validation errors + HTML 404/405
        f, _ = run_module(base, [ITEMS])
    assert f["T9.10"].status == Status.WARN
    with serve(well_behaved_app()) as base:
        f, _ = run_module(base, [ITEMS])
    assert f["T9.10"].status == Status.PASS


# ---- T9.11 auth -------------------------------------------------------

def auth_app(enforce):
    app = Flask("auth")

    @app.get("/secret")
    def secret():
        if enforce and request.headers.get("Authorization") != "Bearer real-token":
            return jsonify({"error": "unauthorised"}), 401
        return jsonify({"ok": True})

    return app


def test_t9_11_auth_is_skipped_without_a_token():
    with serve(auth_app(True)) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/secret"}])
    assert f["T9.11"].status == Status.SKIPPED


def test_t9_11_enforced_auth_passes_and_ignored_auth_fails():
    ep = [{"method": "GET", "path": "/secret"}]
    with serve(auth_app(True)) as base:
        f, _ = run_module(base, ep, token="real-token")
        assert f["T9.11"].status == Status.PASS
    with serve(auth_app(False)) as base:
        f, _ = run_module(base, ep, token="real-token")
    assert f["T9.11"].status == Status.FAIL
    assert "invalid token" in f["T9.11"].detail


# ---- T9.12 speed ------------------------------------------------------

def test_t9_12_slow_error_responses_warn():
    app = Flask("slow")

    @app.errorhandler(404)
    def slow_404(e):
        time.sleep(0.4)
        return jsonify({"error": "not_found"}), 404

    @app.get("/ok")
    def ok():
        return jsonify({"ok": True})

    with serve(app) as base:
        f, _ = run_module(base, [{"method": "GET", "path": "/ok"}], slow_error_s=0.2)
    assert f["T9.12"].status == Status.WARN


# ---- whole-module behaviour -------------------------------------------

def test_t9_13_a_well_behaved_app_passes_everything_that_ran():
    with serve(well_behaved_app()) as base:
        f, result = run_module(base, [ITEMS, {"method": "GET", "path": "/ping"}])
    assert result.status == Status.PASS
    assert [c for c in f if f[c].status in (Status.FAIL, Status.WARN)] == []
    assert result.metrics["requests"] >= 15


def test_t9_14_findings_come_back_in_check_order():
    with serve(well_behaved_app()) as base:
        _, result = run_module(base, [ITEMS])
    numbers = [int(f.check_id.split(".")[1]) for f in result.findings]
    assert numbers == sorted(numbers)


def test_t9_15_unreachable_target_is_reported_as_a_failure():
    f, result = run_module("http://127.0.0.1:9")
    assert result.status == Status.FAIL
    assert list(f) == ["T9.0"]


def test_t9_16_private_targets_are_refused_unless_allowed(monkeypatch):
    monkeypatch.delenv("TESTKIT_ALLOW_PRIVATE")
    f, result = run_module("http://127.0.0.1:8100")
    assert result.status == Status.SKIPPED
    assert "public" in f["T9.0"].detail


def test_t9_17_budget_exhaustion_gives_partial_results_and_a_warning():
    with serve(well_behaved_app()) as base:
        f, result = run_module(base, [ITEMS], max_requests=8)
    assert f["T9.0"].status == Status.WARN
    assert "partial" in f["T9.0"].detail
    assert result.metrics["requests"] == 8


def test_t9_18_a_get_only_target_runs_the_checks_that_apply():
    with serve(well_behaved_app()) as base:
        f, result = run_module(base, [{"method": "GET", "path": "/ping"}])
    assert f["T9.1"].status == Status.SKIPPED
    assert f["T9.7"].status == Status.PASS


# ---- registration and end-to-end ---------------------------------------

def test_t9_19_module_is_discovered_and_selected_for_matching_criteria():
    assert "error_handling" in [m.id for m in registry.discover()]
    plan = build_plan({"reliability"}, Target(base_url="http://x"))
    assert "error_handling" in [i.module_id for i in plan.selected]
    other = build_plan({"performance"}, Target(base_url="http://x"))
    assert "error_handling" not in [i.module_id for i in other.selected]


def test_t9_20_runs_end_to_end_through_the_executor_and_store():
    with serve(create_app()) as base:
        target = Target(base_url=base)
        plan = build_plan({"reliability"}, target)
        run_id = executor.start_run({"reliability"}, target, plan,
                                    options={"error_handling": {"endpoints": [
                                        {"method": "GET", "path": "/leaky"}]}},
                                    background=False)
    run = store.get_run(run_id)
    assert run["status"] == "done" and run["verdict"] == "fail"
    findings = {f["check_id"]: f for f in run["results"][0]["findings"]}
    assert findings["T9.9"]["status"] == "fail"