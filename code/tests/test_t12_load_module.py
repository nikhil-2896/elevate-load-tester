"""T12: the Load Tester wrapped as a platform module."""
import pytest

import load_test_runner as ltr
from demo_target.app import create_app, serve
from stats_aggregator import CSV_HEADER
from testkit import registry
from testkit.models import Status, Target
from testkit.modules.load.module import LoadTest, parse_stats
from testkit.selector import build_plan


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")


def csv_text(requests=100, failures=0, avg=120, p95=300, rps=10.0, aggregated=True):
    def row(name):
        values = {h: "0" for h in CSV_HEADER}
        values.update({"Type": "GET", "Name": name, "Request Count": str(requests),
                       "Failure Count": str(failures), "Average Response Time": str(avg),
                       "95%": str(p95), "Requests/s": str(rps)})
        return ",".join(values[h] for h in CSV_HEADER)
    rows = [row("/")] + ([row("Aggregated")] if aggregated else [])
    return "\n".join([",".join(CSV_HEADER)] + rows)


def fake_runner(monkeypatch, statuses, group=False):
    """Replaces the runner so no Locust process starts."""
    calls = {"starts": []}
    seq = iter(statuses)
    last = {}

    def start(*args, **kwargs):
        calls["starts"].append(args)
        return "job-1", group

    def status(job_id):
        nonlocal last
        last = next(seq, last)
        return last

    monkeypatch.setattr(ltr, "start_website_load_test", start)
    monkeypatch.setattr(ltr, "start_load_test", start)
    monkeypatch.setattr(ltr, "get_job_status", status)
    monkeypatch.setattr(ltr, "get_group_status", status)
    return calls


def run_module(verified=True, **options):
    options.setdefault("poll_interval_s", 0.01)
    target = Target(base_url="http://127.0.0.1:8100", ownership_verified=verified)
    result = LoadTest().run(target, options)
    return {f.check_id: f for f in result.findings}, result


def done(**kw):
    return {"status": "completed", "stats_csv": csv_text(**kw)}


# ---- safety ----------------------------------------------------------

def test_t12_1_refuses_without_verified_ownership(monkeypatch):
    calls = fake_runner(monkeypatch, [done()])
    f, result = run_module(verified=False)
    assert result.status == Status.SKIPPED and calls["starts"] == []


def test_t12_2_private_targets_are_refused_unless_allowed(monkeypatch):
    calls = fake_runner(monkeypatch, [done()])
    monkeypatch.delenv("TESTKIT_ALLOW_PRIVATE")
    f, result = run_module()
    assert result.status == Status.SKIPPED and calls["starts"] == []


# ---- turning statistics into findings -------------------------------------

def test_t12_3_healthy_run_passes_every_check(monkeypatch):
    fake_runner(monkeypatch, [{"status": "running"}, done()])
    f, result = run_module()
    assert [f[c].status for c in ("T12.1", "T12.2", "T12.3", "T12.4")] == [Status.PASS] * 4
    assert result.metrics["requests"] == 100 and result.metrics["p95_ms"] == 300


def test_t12_4_error_rate_thresholds(monkeypatch):
    for failures, expected in ((0, Status.PASS), (3, Status.WARN), (10, Status.FAIL)):
        fake_runner(monkeypatch, [done(failures=failures)])
        f, _ = run_module()
        assert f["T12.2"].status == expected, failures


def test_t12_5_latency_thresholds_and_overrides(monkeypatch):
    for p95, expected in ((300, Status.PASS), (1500, Status.WARN), (4000, Status.FAIL)):
        fake_runner(monkeypatch, [done(p95=p95)])
        f, _ = run_module()
        assert f["T12.3"].status == expected, p95
    fake_runner(monkeypatch, [done(p95=300)])
    f, _ = run_module(p95_warn_ms=100, p95_fail_ms=200)
    assert f["T12.3"].status == Status.FAIL


def test_t12_6_throughput_floor_is_optional(monkeypatch):
    fake_runner(monkeypatch, [done(rps=10)])
    f, _ = run_module(min_rps=50)
    assert f["T12.4"].status == Status.WARN
    fake_runner(monkeypatch, [done(rps=10)])
    f, _ = run_module()
    assert f["T12.4"].status == Status.PASS


def test_t12_7_failed_timed_out_or_empty_jobs_fail(monkeypatch):
    fake_runner(monkeypatch, [{"status": "failed", "error": "locustfile not found"}])
    f, result = run_module()
    assert f["T12.1"].status == Status.FAIL and "locustfile not found" in f["T12.1"].detail
    fake_runner(monkeypatch, [{"status": "timeout"}])
    f, _ = run_module()
    assert f["T12.1"].status == Status.FAIL
    fake_runner(monkeypatch, [{"status": "completed", "stats_csv": None}])
    f, _ = run_module()
    assert f["T12.1"].status == Status.FAIL and "no requests" in f["T12.1"].detail


def test_t12_8_a_job_that_never_finishes_times_out_the_wait(monkeypatch):
    fake_runner(monkeypatch, [{"status": "running"}])
    f, _ = run_module(duration_seconds=1, grace_s=0.1)
    assert f["T12.1"].status == Status.FAIL and "did not finish" in f["T12.1"].detail


# ---- how it drives the existing runner --------------------------------------

def test_t12_9_parameters_are_clamped_to_the_safe_limits(monkeypatch):
    calls = fake_runner(monkeypatch, [done()])
    run_module(users=999999, spawn_rate=500, duration_seconds=99999)
    *_, users, spawn, duration = calls["starts"][0]
    assert (users, spawn, duration) == (1000, 20, 300)


def test_t12_10_uses_api_mode_when_cases_are_given_and_site_mode_otherwise(monkeypatch):
    calls = fake_runner(monkeypatch, [done()])
    run_module(confirmed_cases=[{"label": "a", "payload": {}}], path="/login")
    assert calls["starts"][0][1] == "/login"            # (host, path, cases, ...)
    calls = fake_runner(monkeypatch, [done()])
    run_module(paths=["/a", "/b"])
    assert calls["starts"][0][1] == ["/a", "/b"]         # (host, paths, ...)


def test_t12_11_split_jobs_use_the_aggregated_statistics(monkeypatch):
    fake_runner(monkeypatch, [{"status": "completed", "aggregated_stats_csv": csv_text(requests=500)}],
                group=True)
    f, result = run_module(users=200)
    assert result.metrics["requests"] == 500


def test_t12_12_stats_parser_handles_missing_aggregate_row_and_junk():
    assert parse_stats("") is None and parse_stats(None) is None
    summed = parse_stats(csv_text(requests=50, aggregated=False))
    assert summed["requests"] == 50 and summed["p95_ms"] == 300
    assert parse_stats(csv_text(requests=70))["requests"] == 70


# ---- registration and one real run --------------------------------------------

def test_t12_13_selected_for_performance_only_for_verified_owners():
    assert "load" in [m.id for m in registry.discover()]
    ok = build_plan({"performance"}, Target(base_url="http://x", ownership_verified=True))
    assert [i.module_id for i in ok.selected] == ["load"]
    no = build_plan({"performance"}, Target(base_url="http://x"))
    assert no.selected == [] and "ownership" in no.skipped[0].reason


def test_t12_14_real_locust_run_against_the_demo_target():
    with serve(create_app()) as base:
        target = Target(base_url=base, ownership_verified=True)
        result = LoadTest().run(target, {"users": 2, "spawn_rate": 2, "duration_seconds": 3,
                                          "path": "/unlimited", "poll_interval_s": 0.5})
    f = {x.check_id: x for x in result.findings}
    assert f["T12.1"].status == Status.PASS, f["T12.1"].detail
    assert result.metrics["requests"] >= 2 and f["T12.2"].status == Status.PASS