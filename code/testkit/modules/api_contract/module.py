"""API contract and schema testing: does the service do what its own OpenAPI
description says?

By default only GET operations are called. POST, PUT and PATCH are called
only when the user passes options {"allow_write_calls": true}. DELETE is
never called.
"""
import requests

from testkit.base import TestModule
from testkit.models import Finding, Status, Target, TestResult
from testkit.modules.api_contract import checks as ck
from testkit.modules.api_contract import spec as sp
from testkit.registry import register
from testkit.safety import Budget, BudgetExceeded, SafeClient, UnsafeTarget


def _sort_key(finding):
    return int(finding.check_id.split(".")[1])


@register
class ApiContract(TestModule):
    id = "api_contract"
    title = "API contract and schema"
    criteria = {"api-correctness"}
    requires = {"base_url", "openapi"}
    intrusive = False
    cost = "fast"
    timeout_s = 60.0

    def run(self, target: Target, options: dict) -> TestResult:
        options = options or {}
        budget = Budget(options.get("max_requests", 100), options.get("max_seconds", 45))
        client = SafeClient(budget, timeout=options.get("request_timeout", 5.0))
        headers = {"Accept": "application/json"}
        if target.auth_token:
            headers["Authorization"] = f"Bearer {target.auth_token}"
        findings, notes = [], []

        try:
            spec = options.get("spec")
            if spec is None:
                spec, problem = ck.fetch_json(client, target.openapi_url, headers)
                if problem:
                    findings.append(Finding(
                        "T10.1", "The API description is valid OpenAPI", Status.FAIL, problem,
                        fix_hint="Publish the OpenAPI document as JSON at the URL you gave."))
                    return TestResult.from_findings(self.id, findings, {"requests": budget.used})

            valid = ck.check_valid_spec(spec)
            findings.append(valid)
            if valid.status == Status.FAIL:
                return TestResult.from_findings(self.id, findings, {"requests": budget.used})

            allow_write = bool(options.get("allow_write_calls"))
            allowed = {"get"} | (set(sp.WRITE_METHODS) if allow_write else set())
            all_ops = sp.operations(spec)
            callable_ops = [o for o in all_ops if o["method"] in allowed]
            records = self._probe(client, target, headers, spec, callable_ops, notes)
            findings += [ck.check_reachable(records), ck.check_status_declared(records),
                         ck.check_schema(spec, records), ck.check_content_type(records),
                         ck.check_headers(records)]
            findings.append(self._rejects_bad_requests(
                client, target, headers, spec, callable_ops if allow_write else [], notes))
            findings.append(ck.check_breaking_changes(spec, options.get("baseline_spec")))
            metrics = {"requests": budget.used, "operations": len(all_ops),
                       "operations_called": len(callable_ops)}
        except UnsafeTarget as e:
            return TestResult.from_findings(
                self.id, [Finding("T10.0", "Target may be tested", Status.SKIPPED, str(e))])
        except BudgetExceeded as e:
            notes.append(str(e))
            metrics = {"requests": budget.used}

        if notes:
            findings.append(Finding(
                "T10.0", "Test finished within its allowance", Status.WARN,
                "; ".join(notes) + "; results are partial",
                fix_hint="Test fewer operations per run, or raise max_requests."))
        findings.sort(key=_sort_key)
        return TestResult.from_findings(self.id, findings, metrics)

    # ---- probing -------------------------------------------------------

    def _call(self, client, target, headers, method, path, query, body):
        record = ck.Record(label="", method=method, path_template=path)
        kwargs = {"headers": headers, "params": query or None}
        if body is not None:
            kwargs["json"] = body
        try:
            resp = client.request(method.upper(), target.base_url.rstrip("/") + path, **kwargs)
        except requests.exceptions.RequestException as e:
            record.error = type(e).__name__
            return record
        record.status = resp.status_code
        record.content_type = resp.headers.get("Content-Type", "")
        record.headers = dict(resp.headers)
        record.body = resp.text[:200_000]
        return record

    def _probe(self, client, target, headers, spec, ops, notes):
        records = []
        try:
            for o in ops:
                path, query, body = sp.build_request(spec, o)
                rec = self._call(client, target, headers, o["method"], path, query, body)
                rec.label, rec.path_template, rec.operation = o["label"], o["path"], o["op"]
                if rec.status is not None:
                    rec.response_key, rec.response_def = sp.find_response(spec, o["op"], rec.status)
                records.append(rec)
        except BudgetExceeded as e:
            notes.append(str(e))
        return records

    def _rejects_bad_requests(self, client, target, headers, spec, ops, notes):
        """T10.7: a body missing a required field must draw a documented 4xx."""
        title = "Invalid requests are rejected the way the description says"
        fix = "Document the 4xx answer (400 or 422) and return it for invalid input."
        items = []
        try:
            for o in ops:
                schema = sp.request_schema(spec, o["op"])
                required = sp.required_fields(spec, schema) if schema is not None else []
                if not required:
                    continue
                path, query, body = sp.build_request(spec, o)
                body = {k: v for k, v in body.items() if k != required[0]}
                rec = self._call(client, target, headers, o["method"], path, query, body)
                key, _ = sp.find_response(spec, o["op"], rec.status) if rec.status else (None, None)
                if rec.status is None or rec.status >= 500:
                    items.append((o["label"], Status.FAIL, f"server failed ({rec.status or rec.error})"))
                elif rec.status < 400:
                    items.append((o["label"], Status.FAIL,
                                  f"accepted a body without '{required[0]}' ({rec.status})"))
                elif key is None:
                    items.append((o["label"], Status.WARN,
                                  f"rejected with {rec.status}, which is not documented"))
                else:
                    items.append((o["label"], Status.PASS, ""))
        except BudgetExceeded as e:
            notes.append(str(e))
        if not ops:
            return Finding("T10.7", title, Status.SKIPPED,
                           "write operations are only called with allow_write_calls", fix_hint=fix)
        return ck.summarise("T10.7", title, items, fix, "invalid requests were rejected and documented")