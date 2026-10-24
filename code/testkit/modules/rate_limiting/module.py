"""Rate limiting and throttling: does the service protect itself from
excessive traffic, and does it do so politely?

Intrusive: it sends a burst of rapid requests. It refuses to run unless the
target's ownership has been verified, and it never sends more than
`max_requests` (hard ceiling 300).
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult
from testkit.registry import register
from testkit.safety import Budget, BudgetExceeded, SafeClient, UnsafeTarget

HARD_CEILING = 300
DEFAULT_ENDPOINT = {"method": "GET", "path": "/"}


@dataclass
class Hit:
    status: int = None
    elapsed: float = 0.0
    headers: dict = field(default_factory=dict)   # lower-cased names
    body: str = ""
    error: str = ""

    @property
    def throttled(self):
        return self.status == 429 or (self.status == 503 and "retry-after" in self.headers)


def retry_after_seconds(value):
    """Seconds from a Retry-After header (number or HTTP date), or None."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, int((when - datetime.now(timezone.utc)).total_seconds()))


def _finding(check_id, title, status, detail, fix="", evidence=None):
    return Finding(check_id, title, status, detail, evidence or {}, fix)


def _sort_key(f):
    return int(f.check_id.split(".")[1])


@register
class RateLimiting(TestModule):
    id = "rate_limiting"
    title = "Rate limiting and throttling"
    criteria = {"abuse-protection", "security-basics"}
    requires = {"base_url"}
    intrusive = True
    cost = "fast"
    timeout_s = 120.0

    def run(self, target: Target, options: dict) -> TestResult:
        options = options or {}
        if not target.ownership_verified:
            return TestResult.from_findings(self.id, [_finding(
                "T11.0", "Ownership is verified", Status.SKIPPED,
                "this test sends a burst of requests, so ownership of the target must be proven first")])

        self.cap = min(int(options.get("max_requests", 100)), HARD_CEILING)
        self.max_wait = float(options.get("max_wait_s", 30))
        self.slow_s = float(options.get("slow_throttle_s", 1.0))
        budget = Budget(self.cap * 2 + 40, options.get("max_seconds", 90))
        self.client = SafeClient(budget, timeout=options.get("request_timeout", 5.0))
        self.base = target.base_url.rstrip("/")
        self.token = target.auth_token
        endpoint = options.get("endpoint") or DEFAULT_ENDPOINT
        findings = []

        try:
            hits = self._burst(endpoint, self.token, self.cap)
            if hits and hits[0].status is None:
                findings.append(_finding(
                    "T11.0", "Target is reachable", Status.FAIL,
                    f"no response from {self.base} ({hits[0].error})",
                    "Check the URL and that the service is running."))
                return TestResult.from_findings(self.id, findings, {"requests": budget.used})

            first = next((i for i, h in enumerate(hits) if h.throttled), None)
            throttled = [h for h in hits if h.throttled]
            allowed = first if first is not None else len(hits)
            findings.append(self._detected(hits, first, allowed))
            findings.append(self._status_code(hits, throttled))
            findings.append(self._retry_after(throttled))
            findings.append(self._ratelimit_headers(hits))
            findings.append(self._documented(options.get("documented_limit"), first, allowed))
            findings.append(self._well_formed(throttled))
            findings.append(self._isolation(endpoint, options.get("second_token"), first))
            findings.append(self._recovery(endpoint, throttled))
            findings.append(self._sensitive(options.get("sensitive_endpoint"), first, allowed))
            metrics = {"requests": budget.used, "allowed_before_limit": allowed if first is not None else None}
        except UnsafeTarget as e:
            return TestResult.from_findings(
                self.id, [_finding("T11.0", "Target may be tested", Status.SKIPPED, str(e))])
        except BudgetExceeded as e:
            findings.append(_finding("T11.0", "Test finished within its allowance", Status.WARN,
                                     f"{e}; results are partial"))
            metrics = {"requests": budget.used}

        findings.sort(key=_sort_key)
        return TestResult.from_findings(self.id, findings, metrics)

    # ---- sending -------------------------------------------------------

    def _send(self, endpoint, token):
        hdrs = {"Accept": "application/json"}
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        kwargs = {"headers": hdrs}
        if endpoint.get("body") is not None:
            kwargs["json"] = endpoint["body"]
        hit = Hit()
        started = time.monotonic()
        try:
            resp = self.client.request(endpoint.get("method", "GET").upper(),
                                       self.base + endpoint.get("path", "/"), **kwargs)
            hit.status = resp.status_code
            hit.headers = {k.lower(): v for k, v in resp.headers.items()}
            hit.body = resp.text[:2000]
        except requests.exceptions.RequestException as e:
            hit.error = type(e).__name__
        hit.elapsed = time.monotonic() - started
        return hit

    def _burst(self, endpoint, token, cap):
        """Sends requests back to back until the limiter answers (plus two
        more throttled answers to inspect), the target breaks, or the cap."""
        hits, extra, failures = [], 0, 0
        for _ in range(cap):
            hit = self._send(endpoint, token)
            hits.append(hit)
            if hit.status is None:
                break
            failures = failures + 1 if hit.status >= 500 and not hit.throttled else 0
            if failures >= 3:
                break
            if any(h.throttled for h in hits):
                extra += 1
                if extra >= 3:
                    break
        return hits

    # ---- checks --------------------------------------------------------

    def _detected(self, hits, first, allowed):
        title = "A rate limit is enforced"
        if first is not None:
            spent = sum(h.elapsed for h in hits[:first]) or 0.001
            return _finding("T11.1", title, Status.PASS,
                            f"throttled after {allowed} requests (about {allowed / spent:.0f} per second)")
        return _finding("T11.1", title, Status.WARN,
                        f"no limit appeared within {len(hits)} rapid requests",
                        "Add rate limiting, or raise max_requests if your limit is higher.")

    def _status_code(self, hits, throttled):
        title = "Throttled requests get 429, not an error"
        if not throttled:
            crashes = [h for h in hits if h.status and h.status >= 500]
            if crashes:
                return _finding("T11.2", title, Status.FAIL,
                                f"{len(crashes)} server errors under rapid requests and no throttling",
                                "Protect the service so overload produces 429, not 5xx.")
            return _finding("T11.2", title, Status.SKIPPED, "no throttling was seen")
        if all(h.status == 429 for h in throttled):
            return _finding("T11.2", title, Status.PASS, "limited requests answered 429")
        return _finding("T11.2", title, Status.WARN,
                        f"limiter answers {throttled[0].status}; the standard status is 429",
                        "Answer 429 Too Many Requests.")

    def _retry_after(self, throttled):
        title = "Throttled responses say when to retry"
        fix = "Send a Retry-After header (seconds) with every 429."
        if not throttled:
            return _finding("T11.3", title, Status.SKIPPED, "no throttling was seen")
        values = [h.headers.get("retry-after") for h in throttled]
        if any(v is None for v in values):
            return _finding("T11.3", title, Status.WARN, "429 responses have no Retry-After header", fix)
        if any(retry_after_seconds(v) is None for v in values):
            return _finding("T11.3", title, Status.WARN,
                            f"Retry-After '{values[0]}' is neither seconds nor an HTTP date", fix)
        return _finding("T11.3", title, Status.PASS, f"Retry-After: {values[0]}")

    def _ratelimit_headers(self, hits):
        title = "Rate limit headers are exposed"
        names = ("x-ratelimit-limit", "x-ratelimit-remaining", "ratelimit-limit",
                 "ratelimit-remaining", "ratelimit", "x-rate-limit-limit")
        seen = {n for h in hits for n in h.headers if n in names}
        if seen:
            return _finding("T11.4", title, Status.PASS, f"found: {', '.join(sorted(seen))}")
        return _finding("T11.4", title, Status.WARN,
                        "no RateLimit / X-RateLimit headers on any response",
                        "Tell clients their limit and remaining quota so they can back off before hitting 429.")

    def _documented(self, documented, first, allowed):
        title = "The enforced limit matches the documented limit"
        if not documented:
            return _finding("T11.5", title, Status.SKIPPED, "no documented_limit was given")
        if first is None:
            return _finding("T11.5", title, Status.WARN,
                            f"no limit seen, but {documented} was documented")
        documented = int(documented)
        if allowed > documented * 1.2 + 1:
            return _finding("T11.5", title, Status.FAIL,
                            f"{allowed} requests got through; the documented limit is {documented}",
                            "Make the enforced limit match the documented one.")
        if allowed < documented * 0.8:
            return _finding("T11.5", title, Status.WARN,
                            f"throttled after {allowed}, below the documented {documented} "
                            "(or the window was already partly used)")
        return _finding("T11.5", title, Status.PASS,
                        f"throttled after {allowed}; documented limit is {documented}")

    def _well_formed(self, throttled):
        title = "Throttled responses are clear and fast"
        if not throttled:
            return _finding("T11.7", title, Status.SKIPPED, "no throttling was seen")
        empty = [h for h in throttled if not h.body.strip()]
        slow = [h for h in throttled if h.elapsed > self.slow_s]
        if empty or slow:
            what = "empty body" if empty else f"took {max(h.elapsed for h in slow):.1f}s"
            return _finding("T11.7", title, Status.WARN, f"throttled response: {what}",
                            "Answer fast, with a short message explaining the limit.")
        return _finding("T11.7", title, Status.PASS, "throttled responses have a message and were quick")

    def _isolation(self, endpoint, second_token, first):
        title = "One client's limit does not block another"
        if not second_token:
            return _finding("T11.9", title, Status.SKIPPED, "no second_token was given")
        if first is None:
            return _finding("T11.9", title, Status.SKIPPED, "the first client was never limited")
        hit = self._send(endpoint, second_token)
        if hit.status is None or hit.status >= 500:
            return _finding("T11.9", title, Status.FAIL, f"second client got {hit.status or hit.error}")
        if hit.throttled:
            return _finding("T11.9", title, Status.WARN,
                            "a second client was throttled right after the first: the limit looks global",
                            "Key limits per user, token or IP so one noisy client cannot lock out the rest.")
        return _finding("T11.9", title, Status.PASS, "second client was served while the first was limited")

    def _recovery(self, endpoint, throttled):
        title = "Service recovers after the limit window"
        if not throttled:
            return _finding("T11.6", title, Status.SKIPPED, "no throttling was seen")
        advised = retry_after_seconds(throttled[-1].headers.get("retry-after"))
        wait = (advised if advised is not None else 3) + 0.3
        if wait > self.max_wait:
            return _finding("T11.6", title, Status.WARN,
                            f"Retry-After asks for {wait:.0f}s, longer than max_wait_s ({self.max_wait:g}s); "
                            "recovery was not checked")
        for attempt in (1, 2):
            time.sleep(wait)
            hit = self._send(endpoint, self.token)
            if hit.status is not None and not hit.throttled and hit.status < 500:
                return _finding("T11.6", title, Status.PASS,
                                f"requests were accepted again after {wait * attempt:.1f}s")
        return _finding("T11.6", title, Status.FAIL,
                        f"still throttled after waiting {wait * 2:.1f}s",
                        "Reset the window (or lift the block) when Retry-After has passed.")

    def _sensitive(self, endpoint, first, allowed):
        title = "Sensitive endpoints are limited more strictly"
        if not endpoint:
            return _finding("T11.8", title, Status.SKIPPED, "no sensitive_endpoint was given")
        if first is None:
            return _finding("T11.8", title, Status.SKIPPED, "the general endpoint was never limited")
        hits = self._burst(endpoint, self.token, self.cap)
        idx = next((i for i, h in enumerate(hits) if h.throttled), None)
        if idx is None:
            return _finding("T11.8", title, Status.WARN,
                            f"{endpoint.get('path')} was not limited within {len(hits)} requests",
                            "Login and password-reset style endpoints need tighter limits than the rest.")
        if idx > allowed:
            return _finding("T11.8", title, Status.WARN,
                            f"{endpoint.get('path')} allowed {idx} requests, more than the general {allowed}",
                            "Sensitive endpoints should allow fewer requests than ordinary ones.")
        return _finding("T11.8", title, Status.PASS,
                        f"{endpoint.get('path')} limited after {idx} (general: {allowed})")