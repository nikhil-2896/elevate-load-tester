"""Runs a plan, one module at a time, and saves each result as it finishes.

A module that crashes, hangs, or returns rubbish becomes an ERROR result; the
remaining modules still run. ERROR means "the test itself broke" and says
nothing about the target.
"""
import threading
import time
import uuid

from testkit import registry, store
from testkit.models import Finding, Status, TestResult

MAX_MESSAGE = 300


def _error_result(module_id, message, duration_s=0.0, target=None):
    if target is not None and target.auth_token:
        message = message.replace(target.auth_token, "[redacted]")
    return TestResult.from_findings(
        module_id,
        [Finding(check_id=f"{module_id}.run", title="Module could not complete",
                 status=Status.ERROR, detail=message[:MAX_MESSAGE])],
        duration_s=duration_s,
    )


def _skipped_result(item):
    return TestResult.from_findings(
        item.module_id,
        [Finding(check_id=f"{item.module_id}.skipped", title="Module was not run",
                 status=Status.SKIPPED, detail=item.reason)],
    )


def _call_with_timeout(fn, timeout_s):
    """Runs fn in a daemon thread. Returns its value, re-raises its exception,
    or raises TimeoutError. A hung thread cannot be killed; it is abandoned."""
    box = {}

    def work():
        try:
            box["value"] = fn()
        except Exception as e:  # noqa: BLE001 - reported as an ERROR result
            box["error"] = e

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise TimeoutError(f"timed out after {timeout_s:g}s")
    if "error" in box:
        raise box["error"]
    if "value" not in box:
        raise RuntimeError("module exited without a result")
    return box["value"]


def _run_one(cls, target, options):
    started = time.monotonic()
    try:
        result = _call_with_timeout(lambda: cls().run(target, options), cls.timeout_s)
    except Exception as e:  # noqa: BLE001
        return _error_result(cls.id, f"{type(e).__name__}: {e}",
                             time.monotonic() - started, target)
    if not isinstance(result, TestResult):
        return _error_result(cls.id, "module returned something other than a TestResult",
                             time.monotonic() - started, target)
    result.module = cls.id
    result.duration_s = round(time.monotonic() - started, 3)
    return result


def execute_run(run_id, plan, target, options=None, modules=None):
    """Runs every selected module of `plan`, saving results as they finish.

    options: {module_id: {...}} passed to that module's run().
    modules: module classes to look ids up in (default: the registry).
    """
    options = options or {}
    lookup = {m.id: m for m in modules} if modules is not None else None
    position = 0
    store.update_run(run_id, "running")
    try:
        for item in plan.selected:
            cls = lookup.get(item.module_id) if lookup is not None else (
                registry.get_module(item.module_id)
                if item.module_id in {m.id for m in registry.all_modules()} else None)
            if cls is None:
                result = _error_result(item.module_id, "module is not registered")
            else:
                result = _run_one(cls, target, options.get(item.module_id, {}))
            store.save_result(run_id, position, result)
            position += 1
        for item in plan.skipped:
            store.save_result(run_id, position, _skipped_result(item))
            position += 1
    except Exception:  # noqa: BLE001 - something outside the modules broke
        store.update_run(run_id, "failed")
        raise
    store.update_run(run_id, "done")


def start_run(criteria, target, plan, options=None, modules=None, background=True):
    """Creates the run record, then executes it (in a background thread by
    default). Returns the run id; poll store.get_run(run_id) for progress."""
    run_id = str(uuid.uuid4())
    store.create_run(run_id, target, criteria, plan.to_dict())
    args = (run_id, plan, target, options, modules)
    if background:
        threading.Thread(target=execute_run, args=args, daemon=True).start()
    else:
        execute_run(*args)
    return run_id