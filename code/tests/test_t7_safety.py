"""T7: the safety layer. No test here touches the real internet."""
import pytest
import requests
from flask import Flask

from demo_target.app import serve
from testkit import safety
from testkit.safety import (
    Budget, BudgetExceeded, SafeClient, UnsafeTarget, check_url,
    new_ownership_token, verify_ownership,
)


def resolver_for(mapping):
    """Fake DNS: name -> list of IP strings; unknown names fail."""
    def resolve(host, port):
        if host not in mapping:
            raise OSError("no such host")
        return [(0, 0, 0, "", (ip, 0)) for ip in mapping[host]]
    return resolve


# ---- check_url -------------------------------------------------------

@pytest.mark.parametrize("url", [
    "ftp://example.com", "file:///etc/passwd", "gopher://x", "http://", "javascript:1",
])
def test_t7_1_only_http_and_https_with_a_host(url):
    with pytest.raises(UnsafeTarget):
        check_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "http://0.0.0.0/", "http://[::ffff:127.0.0.1]/",
    "http://100.64.0.1/", "http://224.0.0.1/",
])
def test_t7_2_non_public_literal_addresses_are_refused(url):
    with pytest.raises(UnsafeTarget):
        check_url(url)


def test_t7_3_public_literal_address_is_allowed():
    assert check_url("http://8.8.8.8/x") == "http://8.8.8.8/x"


def test_t7_4_name_resolving_to_a_private_address_is_refused():
    r = resolver_for({"evil.test": ["10.1.2.3"]})
    with pytest.raises(UnsafeTarget):
        check_url("http://evil.test/", resolver=r)


def test_t7_5_one_private_answer_among_public_ones_is_refused():
    r = resolver_for({"mixed.test": ["8.8.8.8", "169.254.169.254"]})
    with pytest.raises(UnsafeTarget):
        check_url("http://mixed.test/", resolver=r)


def test_t7_6_name_resolving_to_public_addresses_is_allowed():
    r = resolver_for({"ok.test": ["8.8.8.8", "1.1.1.1"]})
    assert check_url("https://ok.test/a", resolver=r)


def test_t7_7_credentials_in_the_url_are_refused():
    with pytest.raises(UnsafeTarget):
        check_url("http://user:pw@8.8.8.8/")


def test_t7_8_private_addresses_can_be_allowed_for_local_demos(monkeypatch):
    assert check_url("http://127.0.0.1:8100/", allow_private=True)
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")
    assert check_url("http://127.0.0.1:8100/")
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "false")
    with pytest.raises(UnsafeTarget):
        check_url("http://127.0.0.1:8100/")


def test_t7_9_unresolvable_names_follow_strict_dns():
    r = resolver_for({})
    with pytest.raises(UnsafeTarget):
        check_url("http://nowhere.test/", resolver=r, strict_dns=True)
    assert check_url("http://nowhere.test/", resolver=r, strict_dns=False)


# ---- budget ----------------------------------------------------------

def test_t7_10_budget_stops_at_the_request_cap():
    b = Budget(max_requests=3, max_seconds=60)
    for _ in range(3):
        b.spend()
    with pytest.raises(BudgetExceeded):
        b.spend()
    assert b.used == 3


def test_t7_11_budget_stops_at_the_time_cap():
    now = [0.0]
    b = Budget(max_requests=100, max_seconds=10, clock=lambda: now[0])
    b.spend()
    now[0] = 11.0
    with pytest.raises(BudgetExceeded):
        b.spend()


# ---- SafeClient (fake session, no network) -----------------------------

class FakeResp:
    def __init__(self, status=200, location=None, text=""):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.text = text


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.routes[url]


DNS = resolver_for({"good.test": ["8.8.8.8"], "inner.test": ["10.0.0.9"]})


def client(routes, max_requests=10, **kw):
    return SafeClient(Budget(max_requests, 60), session=FakeSession(routes),
                      resolver=DNS, **kw)


def test_t7_12_client_follows_a_safe_redirect_and_charges_each_hop():
    c = client({"http://good.test/a": FakeResp(302, "/b"),
                "http://good.test/b": FakeResp(200, text="done")})
    assert c.get("http://good.test/a").text == "done"
    assert c.budget.used == 2


def test_t7_13_client_refuses_a_redirect_to_an_internal_address():
    c = client({"http://good.test/a": FakeResp(302, "http://169.254.169.254/latest/")})
    with pytest.raises(UnsafeTarget):
        c.get("http://good.test/a")
    assert len(c.session.calls) == 1   # the internal address was never called


def test_t7_14_client_refuses_a_redirect_to_a_name_that_resolves_internally():
    c = client({"http://good.test/a": FakeResp(301, "http://inner.test/")})
    with pytest.raises(UnsafeTarget):
        c.get("http://good.test/a")


def test_t7_15_client_gives_up_on_redirect_loops():
    c = client({"http://good.test/a": FakeResp(302, "/a")}, max_redirects=3)
    with pytest.raises(UnsafeTarget):
        c.get("http://good.test/a")


def test_t7_16_client_stops_when_the_budget_is_spent():
    c = client({"http://good.test/a": FakeResp(200)}, max_requests=2)
    c.get("http://good.test/a")
    c.get("http://good.test/a")
    with pytest.raises(BudgetExceeded):
        c.get("http://good.test/a")


def test_t7_17_client_never_lets_the_library_follow_redirects_itself():
    c = client({"http://good.test/a": FakeResp(200)})
    c.get("http://good.test/a")
    assert c.session.calls[0][2]["allow_redirects"] is False


# ---- ownership ---------------------------------------------------------

def owner_app(token):
    app = Flask(__name__)

    @app.get(safety.WELL_KNOWN_PATH)
    def verify():
        return token

    return app


def local_client():
    return SafeClient(Budget(10, 30), allow_private=True)


def test_t7_18_ownership_is_proven_by_serving_the_token():
    token = new_ownership_token()
    with serve(owner_app(token)) as base:
        assert verify_ownership(base, token, local_client()) is True


def test_t7_19_wrong_missing_or_empty_token_is_not_ownership():
    token = new_ownership_token()
    with serve(owner_app("something-else")) as base:
        assert verify_ownership(base, token, local_client()) is False
    with serve(Flask("nothing")) as base:
        assert verify_ownership(base, token, local_client()) is False
    with serve(owner_app("")) as base:
        assert verify_ownership(base, "", local_client()) is False


def test_t7_20_tokens_are_unique_and_unguessable():
    a, b = new_ownership_token(), new_ownership_token()
    assert a != b and a.startswith("testkit-") and len(a) > 20


# ---- wired into the existing service -----------------------------------

def test_t7_21_sanity_check_will_not_probe_an_internal_address(client):
    r = client.post("/api/sanity-check", json={"url": "http://169.254.169.254/latest/"})
    assert r.get_json()["reachable"] is False
    assert "public" in r.get_json()["error"]


def test_t7_22_load_test_endpoints_refuse_internal_targets(client):
    body = {"url": "http://127.0.0.1:9/x", "confirmed_cases": [{"label": "a", "payload": {}}]}
    assert client.post("/api/start-load-test", json=body).status_code == 400
    r = client.post("/api/start-website-load-test", json={"url": "http://10.0.0.1/"})
    assert r.status_code == 400