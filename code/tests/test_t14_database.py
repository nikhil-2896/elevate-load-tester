"""T14: the database adapter (SQLite by default, PostgreSQL with DATABASE_URL)
and cleanup of runs that were interrupted."""
import uuid

import db
from testkit import ownership, store
from testkit.models import Target


def make_run():
    run_id = uuid.uuid4().hex
    store.create_run(run_id, Target(base_url="http://x"), {"reliability"}, {"selected": [], "skipped": []})
    return run_id


def age(run_id, stamp):
    with db.connect() as c:
        c.execute("UPDATE test_runs SET created_at = ? WHERE run_id = ?", (stamp, run_id))


def test_t14_1_placeholders_and_rows_work_on_the_active_database():
    with db.connect() as c:
        c.ddl_lock()
        c.execute("CREATE TABLE IF NOT EXISTS t14_probe (k TEXT PRIMARY KEY, v INTEGER)")
        c.execute("DELETE FROM t14_probe WHERE k = ?", ("a",))
        c.execute("INSERT INTO t14_probe (k, v) VALUES (?, ?)", ("a", 7))
        row = c.execute("SELECT k, v FROM t14_probe WHERE k = ?", ("a",)).fetchone()
    assert row["k"] == "a" and dict(row) == {"k": "a", "v": 7}


def test_t14_2_interrupted_runs_are_marked_failed_and_recent_ones_are_kept():
    old, recent = make_run(), make_run()
    store.update_run(old, "running")
    age(old, "2000-01-01 00:00:00")
    store.reap_stale(max_age_s=1800)
    assert store.get_run(old)["status"] == "failed"
    assert store.get_run(recent)["status"] == "queued"


def test_t14_3_finished_runs_are_never_touched_by_cleanup():
    done = make_run()
    store.update_run(done, "done")
    age(done, "2000-01-01 00:00:00")
    store.reap_stale(max_age_s=1800)
    assert store.get_run(done)["status"] == "done"


def test_t14_4_stuck_runs_no_longer_block_new_ones(client, monkeypatch):
    for _ in range(3):
        stuck = make_run()
        store.update_run(stuck, "running")
        age(stuck, "2000-01-01 00:00:00")
    from testkit import api
    monkeypatch.setattr(api.executor, "start_run", lambda *a, **k: "started-run-id")
    r = client.post("/api/v2/runs", json={"url": "http://t.example", "criteria": ["reliability"]})
    assert r.status_code == 202


def test_t14_5_issuing_a_token_twice_returns_the_same_token():
    url = f"http://{uuid.uuid4().hex}.example"
    assert ownership.issue_token(url) == ownership.issue_token(url)