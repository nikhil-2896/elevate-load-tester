"""T5: the demo target behaves the way its name says, so platform tests can
rely on known answers."""
import time

import requests

from demo_target.app import LIMIT, WINDOW_SECONDS, create_app, serve


def client():
    return create_app().test_client()


def test_t5_1_good_endpoint_is_healthy():
    r = client().get("/good")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_t5_2_items_validates_input_properly():
    c = client()
    assert c.post("/items", data="{oops", content_type="application/json").status_code == 400
    assert c.post("/items", json={}).status_code == 422
    assert c.post("/items", json={"name": 5}).status_code == 422
    assert c.post("/items", json={"name": "a"}).status_code == 201


def test_t5_3_crash_endpoint_returns_500_on_bad_json():
    app = create_app()
    app.testing = False
    r = app.test_client().post("/crash", data="{oops", content_type="application/json")
    assert r.status_code == 500


def test_t5_4_leaky_endpoint_exposes_a_traceback():
    r = client().get("/leaky")
    assert r.status_code == 500
    assert "Traceback" in r.get_data(as_text=True)


def test_t5_5_limited_endpoint_answers_429_with_retry_after():
    c = client()
    codes = [c.get("/limited").status_code for _ in range(LIMIT + 2)]
    assert codes[:LIMIT] == [200] * LIMIT
    assert codes[LIMIT:] == [429, 429]
    assert c.get("/limited").headers["Retry-After"].isdigit()


def test_t5_6_limited_endpoint_recovers_after_the_window():
    c = client()
    for _ in range(LIMIT + 1):
        c.get("/limited")
    time.sleep(WINDOW_SECONDS + 0.2)
    assert c.get("/limited").status_code == 200


def test_t5_7_unlimited_endpoint_never_throttles():
    c = client()
    assert {c.get("/unlimited").status_code for _ in range(30)} == {200}


def test_t5_8_spec_is_served_and_spec_lies_is_wrong_on_purpose():
    c = client()
    spec = c.get("/openapi.json").get_json()
    assert spec["openapi"].startswith("3.")
    declared = spec["paths"]["/spec-lies"]["get"]["responses"]["200"]["content"][
        "application/json"]["schema"]["properties"]["count"]["type"]
    assert declared == "integer"
    assert isinstance(c.get("/spec-lies").get_json()["count"], str)


def test_t5_9_serve_runs_a_real_server_on_a_free_port():
    with serve() as base:
        assert base.startswith("http://127.0.0.1:")
        assert requests.get(base + "/good", timeout=5).status_code == 200