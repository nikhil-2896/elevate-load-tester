"""T0.10-T0.11: the API's own error responses are JSON and leak nothing."""
import app as app_module


def test_t0_10_wrong_method_returns_json_405():
    client = app_module.app.test_client()
    resp = client.post("/api/health")
    assert resp.status_code == 405
    assert resp.get_json() == {"error": "method_not_allowed"}


def test_t0_11_unhandled_error_does_not_leak_detail(monkeypatch):
    def boom(url):
        raise RuntimeError("secret internal detail /usr/lib/x.py")

    monkeypatch.setattr(app_module, "sanity_check", boom)
    app_module.app.testing = False  # let the error handler run
    try:
        resp = app_module.app.test_client().post(
            "/api/sanity-check", json={"url": "http://example.com"}
        )
    finally:
        app_module.app.testing = True
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "internal_server_error"}
    assert "secret" not in resp.get_data(as_text=True)