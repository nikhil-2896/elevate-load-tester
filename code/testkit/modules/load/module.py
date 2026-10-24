"""The existing Load Tester, wrapped as a platform module.

It does not change load_test_runner.py: it starts a job through the same
functions the old endpoints use, waits for it, and turns the Locust numbers
into findings. Intrusive, so ownership must be verified.

Options: users, spawn_rate, duration_seconds, paths (website mode) or
confirmed_cases + path (API mode), error_rate_warn / error_rate_fail (percent),
p95_warn_ms / p95_fail_ms, min_rps, poll_interval_s, grace_s.
"""
import time

import load_test_runner as ltr
from job_store import init_db
from stats_aggregator import _parse_csv
from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult
from testkit.registry import register
from testkit.safety import UnsafeTarget, check_url

# Same ceilings the old /api/start-load-test endpoints enforce.
MAX_USERS, MAX_SPAWN_RATE, MAX_DURATION_SECONDS = 1000, 20, 300
FINISHED = ("completed", "failed", "timeout")


def _clamp(value, low, high):
    return max(low, min(high, int(value)))


def _finding(check_id, title, status, detail, fix="", evidence=None):
    return Finding(check_id, title, status, detail, evidence or {}, fix)


def parse_stats(csv_text):
    """Headline numbers from a Locust stats CSV, or None if there are none.
    Uses the 'Aggregated' row when present, otherwise combines the rows."""
    rows = _parse_csv(csv_text)
    if not rows:
        return None
    num = lambda row, key: float(row.get(key) or 0)
    for row in rows:
        if row.get("Name") == "Aggregated":
            return {"requests": int(num(row, "Request Count")), "failures": int(num(row, "Failure Count")),
                    "rps": num(row, "Requests/s"), "avg_ms": num(row, "Average Response Time"),
                    "p95_ms": num(row, "95%"), "p99_ms": num(row, "99%")}
    total = sum(num(r, "Request Count") for r in rows)
    weight = total or 1
    return {"requests": int(total), "failures": int(sum(num(r, "Failure Count") for r in rows)),
            "rps": sum(num(r, "Requests/s") for r in rows),
            "avg_ms": sum(num(r, "Average Response Time") * num(r, "Request Count") for r in rows) / weight,
            "p95_ms": max(num(r, "95%") for r in rows), "p99_ms": max(num(r, "99%") for r in rows)}


@register
class LoadTest(TestModule):
    id = "load"
    title = "Load and performance"
    criteria = {"performance", "reliability"}
    requires = {"base_url"}
    intrusive = True
    cost = "slow"
    timeout_s = MAX_DURATION_SECONDS + 120.0

    def run(self, target: Target, options: dict) -> TestResult:
        options = options or {}
        if not target.ownership_verified:
            return TestResult.from_findings(self.id, [_finding(
                "T12.0", "Ownership is verified", Status.SKIPPED,
                "load testing needs proof that you own the target")])
        try:
            check_url(target.base_url, strict_dns=True)
        except UnsafeTarget as e:
            return TestResult.from_findings(
                self.id, [_finding("T12.0", "Target may be tested", Status.SKIPPED, str(e))])

        users = _clamp(options.get("users", 5), 1, MAX_USERS)
        spawn = _clamp(options.get("spawn_rate", 1), 1, MAX_SPAWN_RATE)
        duration = _clamp(options.get("duration_seconds", 10), 1, MAX_DURATION_SECONDS)
        host = target.base_url.rstrip("/")
        path = str(options.get("path") or "/")
        path = path if path.startswith("/") else "/" + path

        init_db()   # safe to repeat; makes the module work without the web app running

        if options.get("confirmed_cases"):
            job_id, is_group = ltr.start_load_test(host, path, options["confirmed_cases"],
                                                   users, spawn, duration)
        else:
            paths = [p if str(p).startswith("/") else "/" + str(p)
                     for p in (options.get("paths") or [path])]
            job_id, is_group = ltr.start_website_load_test(host, paths, users, spawn, duration)

        job = self._wait(job_id, is_group, duration + float(options.get("grace_s", 90)),
                         float(options.get("poll_interval_s", 1.0)))
        metrics = {"job_id": job_id, "users": users, "duration_seconds": duration}
        title = "The load test completed"
        if job is None:
            return TestResult.from_findings(self.id, [_finding(
                "T12.1", title, Status.FAIL, "the load job did not finish in time",
                "Check that the load worker is running and the target is reachable.")], metrics)
        if job.get("status") != "completed":
            detail = f"the load job ended with status '{job.get('status')}'"
            if job.get("error"):
                detail += f": {job['error']}"
            return TestResult.from_findings(self.id, [_finding(
                "T12.1", title, Status.FAIL, detail,
                "Check that the target is reachable from the load workers.")], metrics)

        stats = parse_stats(job.get("aggregated_stats_csv") if is_group else job.get("stats_csv"))
        if stats is None or stats["requests"] == 0:
            return TestResult.from_findings(self.id, [_finding(
                "T12.1", title, Status.FAIL, "no requests were recorded",
                "Check the URL and paths; the target may be refusing connections.")], metrics)

        err_pct = stats["failures"] / stats["requests"] * 100
        metrics.update({"requests": stats["requests"], "failures": stats["failures"],
                        "error_rate_pct": round(err_pct, 2),
                        "requests_per_second": round(stats["rps"], 2),
                        "avg_ms": round(stats["avg_ms"], 1),
                        "p95_ms": stats["p95_ms"], "p99_ms": stats["p99_ms"]})

        findings = [_finding("T12.1", title, Status.PASS,
                             f"{stats['requests']} requests from {users} users over {duration}s")]

        warn_e, fail_e = options.get("error_rate_warn", 1.0), options.get("error_rate_fail", 5.0)
        level = Status.FAIL if err_pct >= fail_e else Status.WARN if err_pct >= warn_e else Status.PASS
        findings.append(_finding(
            "T12.2", "Error rate stays low", level,
            f"{err_pct:.1f}% of requests failed ({stats['failures']} of {stats['requests']})",
            "Find what fails under load: timeouts, 5xx, connection limits." if level != Status.PASS else ""))

        warn_p, fail_p = options.get("p95_warn_ms", 1000), options.get("p95_fail_ms", 3000)
        level = Status.FAIL if stats["p95_ms"] >= fail_p else Status.WARN if stats["p95_ms"] >= warn_p else Status.PASS
        findings.append(_finding(
            "T12.3", "Responses stay fast (95th percentile)", level,
            f"95% of requests finished within {stats['p95_ms']:.0f} ms (average {stats['avg_ms']:.0f} ms)",
            "Profile the slowest endpoints; add caching or capacity." if level != Status.PASS else ""))

        floor = options.get("min_rps")
        low = bool(floor) and stats["rps"] < float(floor)
        findings.append(_finding(
            "T12.4", "Throughput", Status.WARN if low else Status.PASS,
            f"{stats['rps']:.1f} requests per second with {users} users"
            + (f" (below the {floor} you required)" if low else ""),
            "Add capacity or remove the bottleneck." if low else ""))
        return TestResult.from_findings(self.id, findings, metrics)

    def _wait(self, job_id, is_group, limit_s, poll_s):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            job = ltr.get_group_status(job_id) if is_group else ltr.get_job_status(job_id)
            if job and job.get("status") in FINISHED:
                return job
            time.sleep(poll_s)
        return None