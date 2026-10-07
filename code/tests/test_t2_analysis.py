"""T2.* - target analysis: sanity check, type detection, sitemap paths.
Contract: docs/features/target-analysis/2-contract.md
All network calls are stood in; nothing here touches the internet."""
import requests

from analysis import sanity_check as sc
from analysis import type_detector as td


class FakeResp:
    def __init__(self, status=200, headers=None, text="", url="https://t.example/x"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.url = url


def fake_requests(monkeypatch, by_method):
    """by_method: {"HEAD": FakeResp | Exception, ...}"""
    def _do(method, url, **kw):
        out = by_method[method]
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(sc.requests, "request", lambda m, u, **kw: _do(m, u))
    monkeypatch.setattr(sc.requests, "post", lambda u, **kw: _do("POST", u))


# ---- sanity check ------------------------------------------------------------

def test_T2_1_malformed_url_is_refused_without_a_network_call():
    r = sc.sanity_check("not a url")
    assert r["valid_format"] is False and r["reachable"] is False


def test_T2_2_only_http_and_https_are_valid():
    assert sc.sanity_check("ftp://x.example")["valid_format"] is False
    assert sc.sanity_check("http://")["valid_format"] is False


def test_T2_3_post_only_endpoint_is_reachable(monkeypatch):
    fake_requests(monkeypatch, {"HEAD": FakeResp(405), "GET": FakeResp(405), "POST": FakeResp(200)})
    r = sc.sanity_check("https://t.example/auth/login")
    assert r["reachable"] is True and r["checked_with_method"] == "POST"


def test_T2_4_server_error_is_not_reachable(monkeypatch):
    fake_requests(monkeypatch, {"HEAD": FakeResp(503), "GET": FakeResp(503), "POST": FakeResp(503)})
    assert sc.sanity_check("https://t.example")["reachable"] is False


def test_T2_5_connection_failure_is_not_reachable(monkeypatch):
    boom = requests.exceptions.ConnectionError("down")
    fake_requests(monkeypatch, {"HEAD": boom, "GET": boom, "POST": boom})
    r = sc.sanity_check("https://t.example")
    assert r["valid_format"] is True and r["reachable"] is False and "error" in r


def test_T2_6_a_404_on_every_method_still_counts_as_the_server_answering(monkeypatch):
    fake_requests(monkeypatch, {"HEAD": FakeResp(404), "GET": FakeResp(404), "POST": FakeResp(404)})
    r = sc.sanity_check("https://t.example/missing")
    assert r["reachable"] is True and r["status_code"] == 404


# ---- type detection ----------------------------------------------------------

def test_T2_7_json_content_type_is_an_api():
    r = td.detect_type("https://t.example/x", {"Content-Type": "application/json"})
    assert r["classification"] == "api"


def test_T2_8_html_content_type_is_a_website():
    r = td.detect_type("https://t.example/", {"Content-Type": "text/html; charset=utf-8"})
    assert r["classification"] == "website"


def test_T2_9_no_signal_is_unknown_with_zero_confidence():
    r = td.detect_type("https://t.example/x", {})
    assert r["classification"] == "unknown" and r["confidence"] == 0.0


def test_T2_10_path_hint_alone_says_api():
    r = td.detect_type("https://t.example/api/users", {})
    assert r["classification"] == "api"


def test_T2_11_confidence_never_exceeds_one():
    r = td.detect_type("https://t.example/api/x", {"Content-Type": "application/json"})
    assert r["confidence"] <= 1.0


# ---- sitemap paths -----------------------------------------------------------

URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://t.example/</loc></url>
  <url><loc>https://t.example/about</loc></url>
  <url><loc>https://t.example/logo.png</loc></url>
  <url><loc>https://t.example/style.css</loc></url>
</urlset>"""

INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://t.example/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://t.example/sitemap-2.xml</loc></sitemap>
</sitemapindex>"""


def test_T2_12_urlset_gives_page_paths_and_drops_assets():
    assert td.extract_paths_from_sitemap(URLSET) == ["/", "/about"]


def test_T2_13_paths_are_capped_at_max_paths():
    many = "<urlset>" + "".join(f"<url><loc>https://t.example/p{i}</loc></url>" for i in range(50)) + "</urlset>"
    assert len(td.extract_paths_from_sitemap(many)) == 20
    assert len(td.extract_paths_from_sitemap(many, max_paths=5)) == 5


def test_T2_14_malformed_xml_gives_no_paths():
    assert td.extract_paths_from_sitemap("<urlset><oops>") == []


def test_T2_15_sitemap_index_is_followed_one_level_to_real_pages(monkeypatch):
    pages = {
        "https://t.example/sitemap-1.xml": URLSET,
        "https://t.example/sitemap-2.xml": URLSET.replace("/about", "/contact"),
    }
    monkeypatch.setattr(td.requests, "get", lambda u, timeout=5: FakeResp(200, text=pages[u]))
    paths = td.extract_paths_from_sitemap(INDEX)
    assert "/about" in paths and "/contact" in paths
    assert not any(p.endswith(".xml") for p in paths)


def test_T2_16_a_sitemap_index_inside_an_index_is_not_followed(monkeypatch):
    monkeypatch.setattr(td.requests, "get", lambda u, timeout=5: FakeResp(200, text=INDEX))
    assert td.extract_paths_from_sitemap(INDEX) == []


# ---- through the routes ------------------------------------------------------

def test_T2_17_sanity_route_refuses_empty_and_malformed(client):
    assert client.post("/api/sanity-check", json={}).status_code == 400
    assert client.post("/api/sanity-check", json={"url": "nope"}).status_code == 400


def test_T2_18_analyze_route_refuses_empty_url(client):
    assert client.post("/api/analyze", json={"url": "  "}).status_code == 400


def test_T2_19_analyze_unreachable_is_400_and_carries_sanity(client, monkeypatch):
    boom = requests.exceptions.ConnectionError("down")
    fake_requests(monkeypatch, {"HEAD": boom, "GET": boom, "POST": boom})
    r = client.post("/api/analyze", json={"url": "https://t.example"})
    assert r.status_code == 400 and "sanity" in r.get_json()


def _reachable(monkeypatch, content_type):
    resp = FakeResp(200, headers={"Content-Type": content_type}, url="https://t.example/")
    fake_requests(monkeypatch, {"HEAD": resp, "GET": resp, "POST": resp})


def test_T2_20_analyze_website_includes_sitemap_and_api_does_not(client, monkeypatch):
    _reachable(monkeypatch, "text/html")
    monkeypatch.setattr(td.requests, "get", lambda u, timeout=5: FakeResp(404))
    site = client.post("/api/analyze", json={"url": "https://t.example/"}).get_json()
    assert site["type_detection"]["classification"] == "website" and "sitemap" in site

    _reachable(monkeypatch, "application/json")
    api = client.post("/api/analyze", json={"url": "https://t.example/"}).get_json()
    assert api["type_detection"]["classification"] == "api" and "sitemap" not in api
