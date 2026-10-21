"""T4: platform models, base class and registry (testkit core)."""
import pytest

from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult, worst
from testkit import registry
from testkit.registry import RegistrationError, register


def f(status):
    return Finding(check_id="T0.0", title="x", status=status)


# ---- models ----------------------------------------------------------

def test_t4_1_worst_wins_order():
    assert worst([Status.PASS, Status.WARN]) == Status.WARN
    assert worst([Status.WARN, Status.FAIL, Status.PASS]) == Status.FAIL
    assert worst([Status.FAIL, Status.ERROR]) == Status.ERROR


def test_t4_2_skipped_never_hides_a_verdict():
    assert worst([Status.PASS, Status.SKIPPED]) == Status.PASS
    assert worst([Status.FAIL, Status.SKIPPED]) == Status.FAIL


def test_t4_3_all_skipped_or_empty_is_skipped():
    assert worst([Status.SKIPPED, Status.SKIPPED]) == Status.SKIPPED
    assert worst([]) == Status.SKIPPED


def test_t4_4_result_status_is_worst_of_findings():
    r = TestResult.from_findings("m", [f(Status.PASS), f(Status.FAIL)])
    assert r.status == Status.FAIL
    assert r.module == "m"


def test_t4_5_result_serialises_to_plain_json_types():
    r = TestResult.from_findings("m", [f(Status.WARN)], metrics={"n": 1}, duration_s=1.5)
    d = r.to_dict()
    assert d["status"] == "warn"
    assert d["findings"][0]["status"] == "warn"
    assert d["metrics"] == {"n": 1}
    assert d["duration_s"] == 1.5


def test_t4_6_target_reports_which_inputs_it_provides():
    assert Target(base_url="http://x").provides() == {"base_url"}
    t = Target(base_url="http://x", openapi_url="http://x/o", auth_token="t")
    assert t.provides() == {"base_url", "openapi", "auth"}


# ---- base class ------------------------------------------------------

def test_t4_7_module_without_run_cannot_be_instantiated():
    class Broken(TestModule):
        id = "broken"; title = "B"; criteria = {"c"}
    with pytest.raises(TypeError):
        Broken()


# ---- registry --------------------------------------------------------

def make_module(module_id="t4_demo", **overrides):
    attrs = dict(id=module_id, title="Demo", criteria={"reliability"},
                 run=lambda self, target, options: TestResult.from_findings(module_id, []))
    attrs.update(overrides)
    return type("Demo", (TestModule,), attrs)


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for mid in ("t4_demo", "t4_other", ""):
        registry.unregister(mid)


def test_t4_8_registered_module_can_be_found():
    cls = register(make_module())
    assert registry.get_module("t4_demo") is cls
    assert cls in registry.all_modules()


def test_t4_9_duplicate_id_is_rejected():
    register(make_module())
    with pytest.raises(RegistrationError):
        register(make_module())


def test_t4_10_missing_or_bad_declaration_is_rejected():
    with pytest.raises(RegistrationError):
        register(make_module(id=""))
    with pytest.raises(RegistrationError):
        register(make_module(criteria=set()))
    with pytest.raises(RegistrationError):
        register(make_module(cost="medium"))


def test_t4_11_non_module_is_rejected():
    with pytest.raises(RegistrationError):
        register(object)


def test_t4_12_discover_runs_with_no_modules_installed():
    assert isinstance(registry.discover(), list)