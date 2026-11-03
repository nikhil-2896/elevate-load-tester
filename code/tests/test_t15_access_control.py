"""T15: API key and the allowed-host list."""
import pytest

from testkit.safety import Budget, SafeClient, UnsafeTarget, check_url
from tests.test_t7_safety import DNS, FakeResp, FakeSession

PLAN = {"url": "http://t.example", "criteria": ["reliability"]}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TESTKIT_API_KEY", raising=False)
    monkeypatch.delenv("TESTKIT_ALLOWED_HOSTS", raising=False)


# ---- API key ---------------------------------------------------------

def test_t15_1_without_a_configured_key_the_api_is_open_for_local_use(client):
    assert client.post("/api/v2/plan", json=PLAN).status_code == 200


def test_t15_2_with_a_key_every_api_route_needs_it(client, monkeypatch):
    monkeypatch.setenv("TESTKIT_API_KEY", "s3cret")
    for method, path in (("get", "/api/v2/criteria"), ("get", "/api/v2/modules"),
                         ("post", "/api/v2/plan"), ("post", "/api/v2/runs"),
                         ("get", "/api/v2/runs"), ("get", "/api/v2/runs/x/report.html"),
                         ("post", "/api/v2/ownership/token"), ("get", "/api/jobs")):
        r = getattr(client, method)(path)
        assert r.status_code == 401, path
        assert "API key" in r.get_json()["error"]


def test_t15_3_a_wrong_key_is_refused_and_the_right_key_works(client, monkeypatch):
    monkeypatch.setenv("TESTKIT_API_KEY", "s3cret")
    assert client.get("/api/v2/criteria", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/api/v2/criteria", headers={"X-API-Key": ""}).status_code == 401
    ok = client.post("/api/v2/plan", json=PLAN, headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/api/jobs", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_t15_4_health_checks_and_browser_preflights_stay_open(client, monkeypatch):
    monkeypatch.setenv("TESTKIT_API_KEY", "s3cret")
    assert client.get("/api/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.options("/api/v2/plan").status_code != 401


# ---- allowed hosts -------------------------------------------------------

def test_t15_5_only_listed_hosts_may_be_called(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOWED_HOSTS", "api.example.com, *.shop.example.org")
    for ok in ("https://api.example.com/x", "https://a.shop.example.org", "https://B.Shop.Example.org"):
        assert check_url(ok, strict_dns=False) == ok
    for bad in ("https://example.com", "https://evil.com", "https://shop.example.org",
                "https://api.example.com.evil.com", "https://notapi.example.com"):
        with pytest.raises(UnsafeTarget, match="allowed list"):
            check_url(bad, strict_dns=False)


def test_t15_6_an_unset_list_means_no_limit(monkeypatch):
    assert check_url("https://anything.example", strict_dns=False)


def test_t15_7_a_listed_host_cannot_redirect_the_platform_to_an_unlisted_one(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOWED_HOSTS", "good.test")
    c = SafeClient(Budget(10, 60), resolver=DNS,
                   session=FakeSession({"http://good.test/a": FakeResp(302, "http://inner.test/")}))
    with pytest.raises(UnsafeTarget, match="allowed list"):
        c.get("http://good.test/a")
    assert len(c.session.calls) == 1


def test_t15_8_the_api_refuses_unlisted_targets_and_specs(client, monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOWED_HOSTS", "t.example")
    assert client.post("/api/v2/plan", json=PLAN).status_code == 200
    r = client.post("/api/v2/plan", json={**PLAN, "url": "http://other.example"})
    assert r.status_code == 400 and "allowed list" in r.get_json()["error"]
    r = client.post("/api/v2/runs", json={**PLAN, "openapi_url": "http://other.example/o.json"})
    assert r.status_code == 400 and "openapi_url" in r.get_json()["error"]
    assert client.post("/api/v2/ownership/verify", json={"url": "http://other.example"}).status_code == 400