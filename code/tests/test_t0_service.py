"""T0.* - the service answers, and says the contract's word for it."""


def test_T0_1_health_says_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_T0_2_api_health_is_the_same_answer(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_T0_3_unknown_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.get_json() == {"error": "not_found"}
