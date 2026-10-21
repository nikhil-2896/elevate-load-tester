"""The interface every test module implements."""
from abc import ABC, abstractmethod
from typing import ClassVar

from testkit.models import Target, TestResult


class TestModule(ABC):
    __test__ = False  # stops pytest treating this class as a test class

    id: ClassVar[str]                  # unique, e.g. "error_handling"
    title: ClassVar[str]               # shown to the user
    criteria: ClassVar[set]            # criteria this module serves
    requires: ClassVar[set] = set()    # inputs needed: "base_url", "openapi", "auth"
    intrusive: ClassVar[bool] = False  # True = needs ownership verification
    cost: ClassVar[str] = "fast"       # "fast" runs inline, "slow" is queued
    timeout_s: ClassVar[float] = 60.0  # the executor gives up after this long

    @abstractmethod
    def run(self, target: Target, options: dict) -> TestResult:
        """Runs the checks and returns one result. Must not raise for
        problems with the target; report them as findings."""