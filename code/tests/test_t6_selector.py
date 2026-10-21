"""T6: criteria in, plan out. The selector runs nothing."""
import pytest

from testkit.base import TestModule
from testkit.models import Target, TestResult
from testkit.selector import build_plan


def mod(module_id, criteria, requires=(), intrusive=False, cost="fast"):
    return type(module_id, (TestModule,), dict(
        id=module_id, title=module_id.title(), criteria=set(criteria),
        requires=set(requires), intrusive=intrusive, cost=cost,
        run=lambda self, target, options: TestResult.from_findings(module_id, []),
    ))


ERRORS = mod("errors", {"reliability", "security-basics", "api-correctness"}, {"base_url"})
CONTRACT = mod("contract", {"api-correctness"}, {"base_url", "openapi"})
RATE = mod("rate", {"abuse-protection", "security-basics"}, {"base_url"}, intrusive=True)
LOAD = mod("load", {"performance", "reliability"}, {"base_url"}, intrusive=True, cost="slow")
ALL = [LOAD, RATE, CONTRACT, ERRORS]  # deliberately not in run order

PLAIN = Target(base_url="http://x")
FULL = Target(base_url="http://x", openapi_url="http://x/o", ownership_verified=True)


def ids(items):
    return [i.module_id for i in items]


def test_t6_1_modules_are_picked_by_matching_criteria():
    plan = build_plan({"abuse-protection"}, FULL, ALL)
    assert ids(plan.selected) == ["rate"]


def test_t6_2_a_module_matching_several_criteria_appears_once():
    plan = build_plan({"reliability", "security-basics", "api-correctness"}, FULL, ALL)
    assert ids(plan.selected).count("errors") == 1
    errors = next(i for i in plan.selected if i.module_id == "errors")
    assert errors.matched_criteria == ["api-correctness", "reliability", "security-basics"]


def test_t6_3_unmatched_modules_are_left_out_entirely():
    plan = build_plan({"performance"}, FULL, ALL)
    assert ids(plan.selected) == ["load"]
    assert plan.skipped == []


def test_t6_4_missing_input_skips_with_a_reason():
    plan = build_plan({"api-correctness"}, PLAIN, ALL)
    assert ids(plan.selected) == ["errors"]
    assert ids(plan.skipped) == ["contract"]
    assert plan.skipped[0].reason == "missing input: openapi"


def test_t6_5_intrusive_modules_are_blocked_without_ownership():
    unverified = Target(base_url="http://x")
    plan = build_plan({"abuse-protection", "performance"}, unverified, ALL)
    assert plan.selected == []
    assert ids(plan.skipped) == ["load", "rate"]
    assert all("ownership" in s.reason for s in plan.skipped)


def test_t6_6_order_is_cheap_first_then_intrusive_then_slow():
    plan = build_plan(
        {"reliability", "api-correctness", "abuse-protection", "performance"}, FULL, ALL)
    assert ids(plan.selected) == ["contract", "errors", "rate", "load"]


def test_t6_7_unknown_or_empty_criteria_are_rejected():
    with pytest.raises(ValueError):
        build_plan({"made-up"}, FULL, ALL)
    with pytest.raises(ValueError):
        build_plan(set(), FULL, ALL)


def test_t6_8_plan_serialises_to_plain_json_types():
    d = build_plan({"api-correctness"}, PLAIN, ALL).to_dict()
    assert d["selected"][0]["module_id"] == "errors"
    assert d["skipped"][0]["reason"] == "missing input: openapi"


def test_t6_9_defaults_to_the_registry():
    from testkit import registry
    cls = registry.register(mod("t6_registry_demo", {"performance"}, {"base_url"}))
    try:
        plan = build_plan({"performance"}, PLAIN)
        assert "t6_registry_demo" in ids(plan.selected)
    finally:
        registry.unregister("t6_registry_demo")