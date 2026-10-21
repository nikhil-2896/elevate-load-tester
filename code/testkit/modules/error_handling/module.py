"""Error handling and exception testing: does the service fail safely?"""
from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult
from testkit.modules.error_handling.checks import ALL_CHECKS, Context
from testkit.modules.error_handling.probe import Prober
from testkit.registry import register
from testkit.safety import Budget, BudgetExceeded, SafeClient, UnsafeTarget

DEFAULT_ENDPOINTS = [{"method": "GET", "path": "/"}]


def _normalise(endpoints):
    cleaned = []
    for e in endpoints or DEFAULT_ENDPOINTS:
        path = str(e.get("path", "/"))
        if not path.startswith("/"):
            path = "/" + path
        cleaned.append({"method": str(e.get("method", "GET")).upper(), "path": path,
                        "body": e.get("body")})
    return cleaned


def _sort_key(finding):
    return int(finding.check_id.split(".")[1])


@register
class ErrorHandling(TestModule):
    id = "error_handling"
    title = "Error handling and exceptions"
    criteria = {"reliability", "security-basics", "api-correctness"}
    requires = {"base_url"}
    intrusive = False
    cost = "fast"
    timeout_s = 60.0

    def run(self, target: Target, options: dict) -> TestResult:
        options = options or {}
        budget = Budget(options.get("max_requests", 200), options.get("max_seconds", 45))
        client = SafeClient(budget, timeout=options.get("request_timeout", 5.0))
        prober = Prober(client, target.base_url, target.auth_token)
        ctx = Context(prober=prober, endpoints=_normalise(options.get("endpoints")),
                      has_token=bool(target.auth_token),
                      slow_error_s=options.get("slow_error_s", 2.0))
        findings = []

        try:
            first = ctx.endpoints[0]
            reach = prober.send("reachability", "GET", first["path"])
            if reach.status is None:
                findings.append(Finding(
                    "T9.0", "Target is reachable", Status.FAIL,
                    f"no response from {target.base_url} ({reach.error})",
                    fix_hint="Check the URL, that the service is running and that it is "
                             "reachable from the internet."))
                return TestResult.from_findings(self.id, findings, {"requests": budget.used})

            for check in ALL_CHECKS:
                findings.append(check(ctx))
        except UnsafeTarget as e:
            findings.append(Finding("T9.0", "Target may be tested", Status.SKIPPED, str(e)))
        except BudgetExceeded as e:
            findings.append(Finding(
                "T9.0", "Test finished within its allowance", Status.WARN,
                f"{e}; results are partial",
                fix_hint="Test fewer endpoints per run, or raise max_requests."))

        findings.sort(key=_sort_key)
        return TestResult.from_findings(
            self.id, findings,
            {"requests": budget.used, "endpoints": len(ctx.endpoints)})