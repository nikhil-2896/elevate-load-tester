"""T8: running a plan and saving results."""
import time
import uuid

import pytest

from testkit import executor, store
from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult
from testkit.selector import build_plan

TARGET = Target(base_url="http://x", openapi_url="http://x/o",
                auth_token="SECRET-TOKEN", ownership_verified=True)


def make(module_id, behaviour, criteria=("reliability",), intrusive=False,
         cost="fast", timeout_s=5.0, requires=("base_url",)):
    def run(self, target, options):
        return behaviour(target, options)
    return type(module_id, (TestModule,), dict(
        id=module_id, title=module_id.title(), criteria=set(criteria),
        requires=set(requires), intrusive=intrusive, cost=cost,
        timeout_s=timeout_s, run=run))


def ok(module_id, status=Status.PASS):
    return lambda t, o: TestResult.from_findings(
        module_id, [Finding("T.1", "check", status)], metrics=dict(o))


def run_plan(modules, criteria=("reliability",), target=TARGET, options=None):
    plan = build_plan(criteria, target, modules)
    run_id = executor.start_run(criteria, target, plan, options, modules, background=False)
    return store.get_run(run_id)


# ---- store -----------------------------------------------------------

def test_t8_1_run_round_trips_through_the_store():
    plan = build_plan({"reliability"}, TARGET, [make("a", ok("a"))])
    rid = str(uuid.uuid4())
    store.create_run(rid, TARGET, {"reliability"}, plan.to_dict())
    run = store.get_run(rid)
    assert run["status"] == "queued" and run["verdict"] is None
    assert run["target_url"] == "http://x" and run["criteria"] == ["reliability"]
    assert run["plan"]["selected"][0]["module_id"] == "a"
    assert store.get_run("no-such-run") is None


def test_t8_2_the_auth_token_is_never_stored():
    run = run_plan([make("a", ok("a"))])
    assert "SECRET-TOKEN" not in repr(run)
    import os, sqlite3
    raw = sqlite3.connect(os.environ["DB_PATH"]).execute(
        "SELECT group_concat(plan || criteria || target_url) FROM test_runs").fetchone()[0]
    assert "SECRET-TOKEN" not in raw


def test_t8_3_runs_are_listed_newest_first():
    first = run_plan([make("a", ok("a"))])
    second = run_plan([make("a", ok("a"))])
    ids = [r["run_id"] for r in store.list_runs()]
    assert ids.index(second["run_id"]) < ids.index(first["run_id"])


# ---- executor --------------------------------------------------------

def test_t8_4_modules_run_in_plan_order_and_results_are_saved():
    mods = [make("slow_one", ok("slow_one"), cost="slow", criteria=("reliability",)),
            make("fast_one", ok("fast_one"))]
    run = run_plan(mods)
    assert [r["module"] for r in run["results"]] == ["fast_one", "slow_one"]
    assert run["status"] == "done" and run["verdict"] == "pass"
    assert run["results"][0]["duration_s"] >= 0


def test_t8_5_a_crashing_module_becomes_error_and_the_rest_still_run():
    def boom(t, o):
        raise RuntimeError("kaboom")
    run = run_plan([make("a_crash", boom), make("b_fine", ok("b_fine"))])
    by = {r["module"]: r for r in run["results"]}
    assert by["a_crash"]["status"] == "error"
    assert "RuntimeError: kaboom" in by["a_crash"]["findings"][0]["detail"]
    assert by["b_fine"]["status"] == "pass"
    assert run["verdict"] == "error"


def test_t8_6_a_hanging_module_times_out():
    def hang(t, o):
        time.sleep(3)
    started = time.monotonic()
    run = run_plan([make("a_hang", hang, timeout_s=0.2), make("b_fine", ok("b_fine"))])
    assert time.monotonic() - started < 2
    by = {r["module"]: r for r in run["results"]}
    assert by["a_hang"]["status"] == "error"
    assert "timed out" in by["a_hang"]["findings"][0]["detail"]
    assert by["b_fine"]["status"] == "pass"


def test_t8_7_a_module_returning_rubbish_becomes_error():
    run = run_plan([make("a_bad", lambda t, o: "not a result")])
    assert run["results"][0]["status"] == "error"


def test_t8_8_secrets_are_scrubbed_from_error_messages():
    def leak(t, o):
        raise RuntimeError(f"auth failed with {t.auth_token}")
    run = run_plan([make("a_leak", leak)])
    detail = run["results"][0]["findings"][0]["detail"]
    assert "SECRET-TOKEN" not in detail and "[redacted]" in detail


def test_t8_9_skipped_modules_are_recorded_with_their_reason():
    mods = [make("a_ok", ok("a_ok")),
            make("b_needs_spec", ok("b_needs_spec"), requires=("base_url", "openapi"))]
    plain = Target(base_url="http://x")
    run = run_plan(mods, target=plain)
    by = {r["module"]: r for r in run["results"]}
    assert by["b_needs_spec"]["status"] == "skipped"
    assert by["b_needs_spec"]["findings"][0]["detail"] == "missing input: openapi"
    assert run["verdict"] == "pass"   # a skipped module never hides or causes a verdict


def test_t8_10_options_reach_only_their_own_module():
    mods = [make("a_one", ok("a_one")), make("b_two", ok("b_two"))]
    run = run_plan(mods, options={"a_one": {"limit": 7}})
    by = {r["module"]: r for r in run["results"]}
    assert by["a_one"]["metrics"] == {"limit": 7}
    assert by["b_two"]["metrics"] == {}


def test_t8_11_verdict_is_the_worst_module_status():
    run = run_plan([make("a_warn", ok("a_warn", Status.WARN)),
                    make("b_fail", ok("b_fail", Status.FAIL)),
                    make("c_pass", ok("c_pass"))])
    assert run["verdict"] == "fail"


def test_t8_12_a_plan_item_for_an_unregistered_module_is_an_error():
    mods = [make("a_ghost", ok("a_ghost"))]
    plan = build_plan({"reliability"}, TARGET, mods)
    rid = executor.start_run({"reliability"}, TARGET, plan, modules=[], background=False)
    run = store.get_run(rid)
    assert run["results"][0]["status"] == "error"
    assert "not registered" in run["results"][0]["findings"][0]["detail"]


def test_t8_13_background_run_completes_and_can_be_polled():
    plan = build_plan({"reliability"}, TARGET, [make("a", ok("a"))])
    rid = executor.start_run({"reliability"}, TARGET, plan, modules=[make("a", ok("a"))])
    for _ in range(50):
        if store.get_run(rid)["status"] == "done":
            break
        time.sleep(0.1)
    assert store.get_run(rid)["status"] == "done"


def test_t8_14_a_storage_failure_marks_the_run_failed(monkeypatch):
    plan = build_plan({"reliability"}, TARGET, [make("a", ok("a"))])
    rid = str(uuid.uuid4())
    store.create_run(rid, TARGET, {"reliability"}, plan.to_dict())

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(store, "save_result", broken)
    with pytest.raises(OSError):
        executor.execute_run(rid, plan, TARGET, modules=[make("a", ok("a"))])
    assert store.get_run(rid)["status"] == "failed"