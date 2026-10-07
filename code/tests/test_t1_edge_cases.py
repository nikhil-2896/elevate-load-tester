"""T1.* - edge case generation. Contract: docs/features/edge-case-generation/2-contract.md"""
import copy

from analysis.edge_cases import generate_edge_cases

SAMPLE = {"username": "emilys", "age": 30, "score": 1.5, "active": True,
          "address": {"city": "x"}, "tags": ["a"]}


def labels(cases):
    return [c["label"] for c in cases]


def by_label(cases):
    return {c["label"]: c for c in cases}


def test_T1_1_every_field_gets_a_missing_case_with_that_field_removed():
    cases = by_label(generate_edge_cases(SAMPLE))
    for field in SAMPLE:
        payload = cases[f"missing_{field}"]["payload"]
        assert field not in payload
        assert set(payload) == set(SAMPLE) - {field}


def test_T1_2_every_field_gets_a_null_case():
    cases = by_label(generate_edge_cases(SAMPLE))
    for field in SAMPLE:
        assert cases[f"null_{field}"]["payload"][field] is None


def test_T1_3_string_field_gets_type_boundary_and_attack_cases():
    got = set(labels(generate_edge_cases({"username": "emilys"})))
    expected = {
        "missing_username", "null_username", "wrong_type_username",
        "empty_string_username", "very_long_string_username",
        "sqli_username_0", "sqli_username_1", "sqli_username_2",
        "xss_username_0", "xss_username_1",
    }
    assert got == expected


def test_T1_4_number_field_gets_boundary_cases_and_no_attack_cases():
    got = set(labels(generate_edge_cases({"age": 30})))
    assert got == {"missing_age", "null_age", "wrong_type_age",
                   "very_large_age", "negative_age", "zero_age"}


def test_T1_5_bool_field_is_not_treated_as_a_number():
    got = set(labels(generate_edge_cases({"active": True})))
    assert got == {"missing_active", "null_active", "wrong_type_active"}


def test_T1_6_nested_object_and_array_only_get_missing_and_null():
    got = set(labels(generate_edge_cases({"address": {"city": "x"}, "tags": ["a"]})))
    assert got == {"missing_address", "null_address", "missing_tags", "null_tags"}


def test_T1_7_labels_are_unique():
    ls = labels(generate_edge_cases(SAMPLE))
    assert len(ls) == len(set(ls))


def test_T1_8_sample_input_is_never_mutated():
    snapshot = copy.deepcopy(SAMPLE)
    generate_edge_cases(SAMPLE)
    assert SAMPLE == snapshot


def test_T1_9_no_case_payload_equals_the_sample():
    for c in generate_edge_cases(SAMPLE):
        assert c["payload"] != SAMPLE, c["label"]


def test_T1_10_every_case_carries_label_category_description_payload():
    for c in generate_edge_cases(SAMPLE):
        assert set(c) == {"label", "category", "description", "payload"}


def test_T1_11_same_input_gives_same_output():
    assert generate_edge_cases(SAMPLE) == generate_edge_cases(SAMPLE)


def test_T1_12_empty_sample_gives_no_cases():
    assert generate_edge_cases({}) == []


# ---- through the routes ----------------------------------------------------

def test_T1_13_route_total_cases_matches_cases(client):
    r = client.post("/api/generate-edge-cases", json={"sample_input": SAMPLE})
    body = r.get_json()
    assert r.status_code == 200
    assert body["total_cases"] == len(body["cases"])


def test_T1_14_route_refuses_missing_or_non_object_sample(client):
    for body in ({}, {"sample_input": {}}, {"sample_input": []}, {"sample_input": "x"}):
        r = client.post("/api/generate-edge-cases", json=body)
        assert r.status_code == 400, body


def test_T1_15_confirm_returns_exactly_the_selected_cases(client):
    r = client.post("/api/confirm-selection", json={
        "sample_input": SAMPLE, "selected_labels": ["missing_username", "null_age"]})
    body = r.get_json()
    assert r.status_code == 200
    assert body["confirmed_count"] == 2
    assert sorted(labels(body["confirmed_cases"])) == ["missing_username", "null_age"]


def test_T1_16_confirm_refuses_an_unknown_label(client):
    r = client.post("/api/confirm-selection", json={
        "sample_input": SAMPLE, "selected_labels": ["missing_username", "bogus"]})
    assert r.status_code == 400
    assert "bogus" in r.get_json()["error"]


def test_T1_17_confirm_refuses_empty_selection_or_missing_fields(client):
    for body in ({"sample_input": SAMPLE, "selected_labels": []},
                 {"sample_input": SAMPLE},
                 {"selected_labels": ["x"]}):
        r = client.post("/api/confirm-selection", json=body)
        assert r.status_code == 400, body
