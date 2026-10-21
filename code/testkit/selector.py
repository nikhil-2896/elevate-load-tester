"""Turns the user's chosen criteria into a plan: which modules run, which are
skipped and why, and in what order. Pure logic; runs nothing."""
from dataclasses import dataclass, field

from testkit import registry
from testkit.criteria import is_known


@dataclass
class PlanItem:
    module_id: str
    title: str
    matched_criteria: list
    intrusive: bool
    cost: str


@dataclass
class SkippedItem:
    module_id: str
    title: str
    reason: str


@dataclass
class Plan:
    selected: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def to_dict(self):
        return {
            "selected": [vars(i) for i in self.selected],
            "skipped": [vars(i) for i in self.skipped],
        }


def _order_key(cls):
    # Cheap, read-only modules first; intrusive next; slow (queued) last, so
    # heavy tests never degrade the target before the light ones have run.
    return (cls.cost == "slow", cls.intrusive, cls.id)


def build_plan(criteria, target, modules=None):
    """criteria: iterable of criterion ids. target: testkit.models.Target.
    modules: module classes to choose from (default: everything registered).
    Raises ValueError for an unknown or empty criteria list."""
    wanted = set(criteria)
    if not wanted:
        raise ValueError("choose at least one criterion")
    unknown = sorted(c for c in wanted if not is_known(c))
    if unknown:
        raise ValueError(f"unknown criteria: {unknown}")

    if modules is None:
        modules = registry.all_modules()

    have = target.provides()
    plan = Plan()
    runnable = []

    for cls in modules:
        matched = sorted(cls.criteria & wanted)
        if not matched:
            continue
        missing = sorted(cls.requires - have)
        if missing:
            plan.skipped.append(SkippedItem(
                cls.id, cls.title, "missing input: " + ", ".join(missing)))
        elif cls.intrusive and not target.ownership_verified:
            plan.skipped.append(SkippedItem(
                cls.id, cls.title, "ownership of the target is not verified"))
        else:
            runnable.append((cls, matched))

    for cls, matched in sorted(runnable, key=lambda p: _order_key(p[0])):
        plan.selected.append(PlanItem(
            cls.id, cls.title, matched, cls.intrusive, cls.cost))
    plan.skipped.sort(key=lambda s: s.module_id)
    return plan