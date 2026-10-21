"""Data shapes shared by every part of the testing platform.

Nothing in here knows about any specific test module.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(str, Enum):
    PASS = "pass"
    SKIPPED = "skipped"   # could not run (missing input, blocked)
    WARN = "warn"         # worth a look, not a failure
    FAIL = "fail"         # the target is wrong
    ERROR = "error"       # the test itself broke; says nothing about the target


_RANK = {
    Status.PASS: 0,
    Status.SKIPPED: 1,
    Status.WARN: 2,
    Status.FAIL: 3,
    Status.ERROR: 4,
}


def worst(statuses):
    """Returns the worst status in the list ("worst wins").

    SKIPPED only wins when every item was skipped, so a skipped check never
    hides the verdict of the checks that did run. An empty list is SKIPPED:
    nothing was checked.
    """
    statuses = list(statuses)
    ran = [s for s in statuses if s != Status.SKIPPED]
    if not ran:
        return Status.SKIPPED
    return max(ran, key=lambda s: _RANK[s])


@dataclass
class Finding:
    check_id: str                 # e.g. "T11.4"
    title: str
    status: Status
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    fix_hint: str = ""

    def to_dict(self):
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class TestResult:
    __test__ = False  # stops pytest treating this class as a test class

    module: str
    status: Status
    findings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0

    @classmethod
    def from_findings(cls, module, findings, metrics=None, duration_s=0.0):
        """Builds a result whose status is the worst of its findings."""
        findings = list(findings)
        return cls(
            module=module,
            status=worst(f.status for f in findings),
            findings=findings,
            metrics=dict(metrics or {}),
            duration_s=duration_s,
        )

    def to_dict(self):
        return {
            "module": self.module,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
            "duration_s": self.duration_s,
        }


@dataclass
class Target:
    """What the user wants tested."""
    base_url: str
    openapi_url: str = ""
    auth_token: str = ""
    ownership_verified: bool = False

    def provides(self):
        """Names of the inputs this target supplies (matched against a
        module's `requires`)."""
        have = set()
        if self.base_url:
            have.add("base_url")
        if self.openapi_url:
            have.add("openapi")
        if self.auth_token:
            have.add("auth")
        return have