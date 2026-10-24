"""T13: the /api/v2 endpoints and the HTML report."""
import time

import pytest
from flask import Flask

from demo_target.app import create_app, serve
from testkit import ownership, safety, store


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")
    monkeypatch.delenv("TESTKIT_AUTO_VERIFY_HOSTS", raising=False)


def wait_done(client, run_id, seconds=60):
    for _ in range(int(seconds * 10)):
        run = client.get(f"/api/v2/runs/{run_id}").get_json()
        if run["status"] in ("done", "failed"):
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


RELIABILITY = {"error_handling": {"endpoints": [{"method": "GET", "path": "/leaky"}]}}


# ---- catalogue ---------------------------------------------------------

def test_t13_1_lists_criteria_and_modules(client):
    criteria = client.get("/api/v2/criteria").get_json()
    assert {"reliability", "performance", "abuse-protection"} <= {c["id"] for c in criteria}
    modules = {m["id"]: m for m in client.get("/api/v2/modules").get_json()}
    assert {"error_handling", "api_contract", "rate_limiting", "load"} <= set(modules)
    assert modules["rate_limiting"]["intrusive"] is True
    assert modules["api_contract"]["requires"] == ["base_url", "openapi"]


# ---- validation --------------------------------------------------------

@pytest.mark.parametrize("body,fragment", [
    ({}, "url"),
    ({"url": "ftp://x.example", "criteria": ["reliability"]}, "http"),
    ({"url": "http://t.example", "criteria": []}, "criteria"),
    ({"url": "http://t.example", "criteria": ["nonsense"]}, "unknown criteria"),
    ({"url": "http://t.example", "criteria": ["reliability"], "options": "x"}, "options"),
    ({"url": "http://t.example", "criteria": ["reliability"], "options": {"a": 1}}, "options"),
    ({"url": "http://t.example", "criteria": ["reliability"], "openapi_url": 5}, "openapi_url"),
])
def test_t13_2_bad_requests_are_rejected_with_a_message(client, body, fragment):
    for path in ("/api/v2/plan", "/api/v2/runs"):
        r = client.post(path, json=body)
        assert r.status_code == 400 and fragment in r.get_json()["error"]


def test_t13_3_internal_targets_are_refused(client, monkeypatch):
    monkeypatch.delenv("TESTKIT_ALLOW_PRIVATE")
    for url in ("http://127.0.0.1:5000", "http://169.254.169.254/latest"):
        assert client.post("/api/v2/runs", json={"url": url, "criteria": ["reliability"]}).status_code == 400
    r = client.post("/api/v2/plan", json={"url": "http://t.example", "criteria": ["reliability"],
                                          "openapi_url": "http://10.0.0.1/o.json"})
    assert r.status_code == 400 and "openapi_url" in r.get_json()["error"]


# ---- plan --------------------------------------------------------------

def test_t13_4_plan_shows_selected_and_skipped_modules_with_reasons(client):
    body = {"url": "http://t.example", "criteria": ["reliability", "api-correctness", "abuse-protection"]}
    plan = client.post("/api/v2/plan", json=body).get_json()
    assert plan["ownership_verified"] is False
    assert [i["module_id"] for i in plan["selected"]] == ["error_handling"]
    reasons = {s["module_id"]: s["reason"] for s in plan["skipped"]}
    assert reasons["api_contract"] == "missing input: openapi"
    assert "ownership" in reasons["rate_limiting"]
    body["openapi_url"] = "http://t.example/openapi.json"
    plan = client.post("/api/v2/plan", json=body).get_json()
    assert "api_contract" in [i["module_id"] for i in plan["selected"]]


def test_t13_5_operator_trusted_hosts_count_as_verified(client, monkeypatch):
    monkeypatch.setenv("TESTKIT_AUTO_VERIFY_HOSTS", "t.example")
    plan = client.post("/api/v2/plan", json={"url": "http://t.example", "criteria": ["abuse-protection"]}).get_json()
    assert plan["ownership_verified"] is True
    assert [i["module_id"] for i in plan["selected"]] == ["rate_limiting"]


# ---- runs and report ---------------------------------------------------

def test_t13_6_a_run_executes_and_can_be_polled_and_reported(client):
    with serve(create_app()) as base:
        r = client.post("/api/v2/runs", json={"url": base, "criteria": ["reliability"], "options": RELIABILITY})
        assert r.status_code == 202
        run = wait_done(client, r.get_json()["run_id"])
    assert run["status"] == "done" and run["verdict"] == "fail"
    findings = {f["check_id"]: f for f in run["results"][0]["findings"]}
    assert findings["T9.9"]["status"] == "fail"
    assert "auth_token" not in str(run)
    page = client.get(f"/api/v2/runs/{run['run_id']}/report.html")
    assert page.status_code == 200 and page.mimetype == "text/html"
    html = page.get_data(as_text=True)
    assert "Overall verdict" in html and "T9.9" in html and "FAIL" in html


def test_t13_7_the_auth_token_is_used_but_never_stored_or_returned(client):
    with serve(create_app()) as base:
        r = client.post("/api/v2/runs", json={"url": base, "criteria": ["reliability"],
                                              "auth_token": "TOP-SECRET-TOKEN-123", "options": RELIABILITY})
        run = wait_done(client, r.get_json()["run_id"])
    assert "TOP-SECRET-TOKEN-123" not in str(run)
    assert "TOP-SECRET-TOKEN-123" not in client.get(f"/api/v2/runs/{run['run_id']}/report.html").get_data(as_text=True)
    assert "TOP-SECRET-TOKEN-123" not in str(client.get("/api/v2/runs").get_json())


def test_t13_8_unknown_runs_give_404_and_runs_are_listed(client):
    assert client.get("/api/v2/runs/nope").status_code == 404
    assert client.get("/api/v2/runs/nope/report.html").status_code == 404
    runs = client.get("/api/v2/runs").get_json()["runs"]
    assert isinstance(runs, list)


def test_t13_9_a_request_no_module_can_serve_is_refused(client):
    r = client.post("/api/v2/runs", json={"url": "http://t.example", "criteria": ["abuse-protection"]})
    assert r.status_code == 400 and r.get_json()["skipped"]


def test_t13_10_too_many_active_runs_are_refused(client, monkeypatch):
    busy = [{"run_id": str(i), "status": "running"} for i in range(3)]
    monkeypatch.setattr(store, "list_runs", lambda limit=50: busy)
    r = client.post("/api/v2/runs", json={"url": "http://t.example", "criteria": ["reliability"]})
    assert r.status_code == 429


def test_t13_11_report_escapes_hostile_content(client):
    run = {"run_id": "abc12345", "target_url": "http://x/<script>alert(1)</script>",
           "criteria": ["reliability"], "created_at": "now", "status": "done", "verdict": "fail",
           "results": [{"module": "m", "status": "fail", "duration_s": 0.1, "metrics": {},
                        "findings": [{"check_id": "T.1", "title": "<b>t</b>", "status": "fail",
                                      "detail": "<img src=x onerror=alert(1)>", "evidence": {"k": "<i>"},
                                      "fix_hint": "<u>fix</u>"}]}]}
    from testkit.report import render_html
    html = render_html(run)
    assert "<script>alert" not in html and "<img src=x" not in html and "<u>fix" not in html
    assert "&lt;script&gt;" in html


# ---- ownership ---------------------------------------------------------

def test_t13_12_ownership_flow_unlocks_intrusive_modules(client):
    holder = {"token": ""}
    owner = Flask("owner")

    @owner.get(safety.WELL_KNOWN_PATH)
    def token_file():
        return holder["token"]

    with serve(owner) as base:
        assert client.post("/api/v2/ownership/verify", json={"url": base}).get_json()["verified"] is False
        t = client.post("/api/v2/ownership/token", json={"url": base}).get_json()
        assert t["path"] == "/.well-known/testkit-verify" and t["token"].startswith("testkit-")
        assert client.post("/api/v2/ownership/token", json={"url": base}).get_json()["token"] == t["token"]
        assert client.post("/api/v2/ownership/verify", json={"url": base}).get_json()["verified"] is False
        holder["token"] = t["token"]
        assert client.post("/api/v2/ownership/verify", json={"url": base}).get_json()["verified"] is True
        assert ownership.is_verified(base) is True
        plan = client.post("/api/v2/plan", json={"url": base, "criteria": ["abuse-protection"]}).get_json()
    assert plan["ownership_verified"] is True
    assert [i["module_id"] for i in plan["selected"]] == ["rate_limiting"]


def test_t13_13_ownership_endpoints_validate_input(client):
    assert client.post("/api/v2/ownership/token", json={}).status_code == 400
    assert client.post("/api/v2/ownership/verify", json={"url": "ftp://x"}).status_code == 400


def test_t13_14_the_old_endpoints_still_work(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}
    assert client.get("/api/jobs").status_code == 200


def test_t13_15_a_full_run_with_rate_limiting_on_a_trusted_host(client, monkeypatch):
    with serve(create_app()) as base:
        monkeypatch.setenv("TESTKIT_AUTO_VERIFY_HOSTS", "127.0.0.1")
        r = client.post("/api/v2/runs", json={
            "url": base, "criteria": ["abuse-protection"],
            "options": {"rate_limiting": {"endpoint": {"method": "GET", "path": "/limited"},
                                          "max_wait_s": 0}}})
        run = wait_done(client, r.get_json()["run_id"])
    result = next(x for x in run["results"] if x["module"] == "rate_limiting")
    assert {f["check_id"]: f for f in result["findings"]}["T11.1"]["status"] == "pass"