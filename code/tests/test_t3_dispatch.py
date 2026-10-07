"""T3.* - starting load tests, splitting large ones, reading status back.
Contract: docs/features/load-test-dispatch/2-contract.md
Queue mode is exercised with SQS stood in; no AWS call is made."""
import csv
import io
import uuid

import pytest

import load_test_runner as ltr
import job_store
from stats_aggregator import merge_stats_csvs

CASES = [{"label": "missing_username", "category": "missing_field",
          "description": "d", "payload": {"password": "p"}}]


@pytest.fixture()
def sent(monkeypatch):
    """Queue mode on; collects every message that would have gone to SQS."""
    box = []
    monkeypatch.setattr(ltr, "USE_SQS", True)
    monkeypatch.setattr(ltr, "send_job_message", box.append)
    return box


def start(users, **kw):
    return ltr.start_load_test("https://t.example", "/login", CASES, users, 1, 10, **kw)


# ---- starting ----------------------------------------------------------------

def test_T3_1_up_to_threshold_is_one_job_and_one_message(sent):
    job_id, is_group = start(ltr.SPLIT_THRESHOLD)
    assert is_group is False and len(sent) == 1
    assert sent[0]["job_id"] == job_id and sent[0]["users"] == ltr.SPLIT_THRESHOLD
    assert job_store.get_job(job_id)["status"] == "queued"


def test_T3_2_above_threshold_is_a_group_of_children(sent):
    group_id, is_group = start(ltr.SPLIT_THRESHOLD + 1)
    assert is_group is True and len(sent) >= 2
    assert job_store.get_job_group(group_id)["child_count"] == len(sent)


@pytest.mark.parametrize("users", [51, 99, 100, 101, 237, 500, 999, 1000])
def test_T3_3_children_add_up_to_the_request_and_none_exceeds_the_threshold(sent, users):
    start(users)
    assert sum(m["users"] for m in sent) == users
    assert all(1 <= m["users"] <= ltr.SPLIT_THRESHOLD for m in sent), [m["users"] for m in sent]


def test_T3_4_children_are_balanced_within_one_user(sent):
    start(237)
    sizes = [m["users"] for m in sent]
    assert max(sizes) - min(sizes) <= 1


def test_T3_5_every_child_carries_the_same_target_cases_and_timing(sent):
    start(120)
    for m in sent:
        assert m["target_url"] == "https://t.example" and m["target_path"] == "/login"
        assert m["cases"] == CASES and m["spawn_rate"] == 1 and m["duration_seconds"] == 10
        assert m["job_type"] == "api"


def test_T3_6_children_have_distinct_job_ids_and_belong_to_the_group(sent):
    group_id, _ = start(120)
    ids = [m["job_id"] for m in sent]
    assert len(ids) == len(set(ids))
    assert {c["job_id"] for c in job_store.list_child_jobs(group_id)} == set(ids)


def test_T3_7_website_test_sends_paths_not_cases(sent):
    ltr.start_website_load_test("https://t.example", ["/", "/about"], 5, 1, 10)
    assert sent[0]["job_type"] == "website" and sent[0]["paths"] == ["/", "/about"]
    assert "cases" not in sent[0]


# ---- status ------------------------------------------------------------------

def _group_with(statuses):
    gid = "g-" + uuid.uuid4().hex[:8]
    job_store.create_job_group(gid, "https://t.example", "api", 100, 1, 10, len(statuses))
    for i, s in enumerate(statuses):
        jid = f"{gid}-{i}"
        job_store.create_job(jid, "https://t.example", 50, 1, 10, group_id=gid)
        job_store.update_job(jid, status=s, stats_csv=STATS if s == "completed" else None)
    return gid


STATS = ("Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
         "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
         "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%\n"
         "POST,missing_username,10,2,100,110,50,300,5,1.0,0.2,100,110,120,130,150,200,250,280,300,300,300\n")


@pytest.mark.parametrize("statuses,expected", [
    (["completed", "failed"], "failed"),
    (["completed", "timeout"], "timeout"),
    (["failed", "timeout"], "failed"),
    (["completed", "running"], "running"),
    (["queued", "queued"], "queued"),
    (["completed", "queued"], "queued"),
    (["completed", "completed"], "completed"),
])
def test_T3_8_group_status_is_the_worst_of_its_children(statuses, expected):
    assert ltr.get_group_status(_group_with(statuses))["status"] == expected


def test_T3_9_finished_group_carries_one_merged_csv_and_keeps_it():
    gid = _group_with(["completed", "completed"])
    first = ltr.get_group_status(gid)["aggregated_stats_csv"]
    again = ltr.get_group_status(gid)["aggregated_stats_csv"]
    assert first and first == again


def test_T3_10_unknown_id_is_none():
    assert ltr.get_group_status("nope") is None and ltr.get_job_status("nope") is None


def test_T3_11_status_route_404_for_unknown_id(client):
    r = client.get("/api/load-test-status/does-not-exist")
    assert r.status_code == 404


def test_T3_12_status_route_answers_for_a_group_id(client):
    gid = _group_with(["running", "queued"])
    r = client.get(f"/api/load-test-status/{gid}")
    assert r.status_code == 200 and r.get_json()["status"] == "running"


# ---- merging -----------------------------------------------------------------

def _rows(text):
    return {r["Name"]: r for r in csv.DictReader(io.StringIO(text))}


def test_T3_13_merge_sums_counts_and_throughput_and_takes_extremes():
    other = STATS.replace(",10,2,100,110,50,300,", ",30,0,100,130,40,500,")
    merged = _rows(merge_stats_csvs([STATS, other]))
    row = merged["missing_username"]
    assert row["Request Count"] == "40" and row["Failure Count"] == "2"
    assert row["Min Response Time"] in ("40", "40.0") and row["Max Response Time"] in ("500", "500.0")
    assert float(row["Requests/s"]) == pytest.approx(2.0)


def test_T3_14_merge_adds_an_aggregated_row_totalling_everything():
    merged = _rows(merge_stats_csvs([STATS, STATS]))
    assert merged["Aggregated"]["Request Count"] == "20"


def test_T3_15_merge_of_nothing_is_just_a_header_and_an_empty_aggregate():
    merged = _rows(merge_stats_csvs([]))
    assert list(merged) == ["Aggregated"] and merged["Aggregated"]["Request Count"] == "0"


# ---- the routes' refusals ----------------------------------------------------

GOOD = {"url": "https://t.example/login", "confirmed_cases": CASES,
        "users": 5, "spawn_rate": 1, "duration_seconds": 10}


@pytest.mark.parametrize("change", [
    {"users": 0}, {"users": 1001}, {"spawn_rate": 0}, {"spawn_rate": 21},
    {"duration_seconds": 0}, {"duration_seconds": 301}, {"users": "many"},
    {"url": "ftp://x.example"}, {"url": ""}, {"confirmed_cases": []}, {"confirmed_cases": "x"},
])
def test_T3_16_start_route_refuses_bad_input(client, sent, change):
    r = client.post("/api/start-load-test", json={**GOOD, **change})
    assert r.status_code == 400, change
    assert sent == []


def test_T3_17_start_route_accepts_the_limits_exactly(client, sent):
    r = client.post("/api/start-load-test", json={**GOOD, "users": 1000, "spawn_rate": 20, "duration_seconds": 300})
    assert r.status_code == 202


def test_T3_18_start_route_answers_202_with_job_id_and_is_group(client, sent):
    r = client.post("/api/start-load-test", json=GOOD)
    body = r.get_json()
    assert r.status_code == 202 and body["status"] == "started"
    assert body["is_group"] is False and body["job_id"]


def test_T3_19_website_route_falls_back_to_the_given_path_without_a_sitemap(client, sent):
    r = client.post("/api/start-website-load-test", json={"url": "https://t.example/pricing", "users": 5})
    assert r.status_code == 202 and r.get_json()["paths_used"] == ["/pricing"]


def test_T3_20_website_route_falls_back_to_root_for_a_bare_host(client, sent):
    r = client.post("/api/start-website-load-test", json={"url": "https://t.example", "users": 5})
    assert r.get_json()["paths_used"] == ["/"]


def test_T3_21_compare_route_refuses_missing_ids_and_404s_unknown_ones(client):
    assert client.post("/api/compare-jobs", json={"job_id_a": "x"}).status_code == 400
    assert client.post("/api/compare-jobs", json={"job_id_a": "x", "job_id_b": "y"}).status_code == 404
