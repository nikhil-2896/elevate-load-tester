"""Saves test runs and their results in the same database as the load tester
(PostgreSQL when DATABASE_URL is set, otherwise the SQLite file in DB_PATH).
Tables are added beside the existing ones; nothing existing is changed.

The target's auth token is never stored.
"""
import json
import threading
from datetime import datetime, timedelta, timezone

import db
from testkit.models import Status, worst

_lock = threading.Lock()
_conn = db.connect      # other modules (ownership) open connections through here


def init_store():
    with _conn() as c:
        c.ddl_lock()
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                run_id TEXT PRIMARY KEY,
                target_url TEXT,
                openapi_url TEXT,
                criteria TEXT,
                plan TEXT,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )""")
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS test_results (
                id {db.autoinc_pk()},
                run_id TEXT,
                position INTEGER,
                module TEXT,
                status TEXT,
                result TEXT,
                duration_s REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")


def create_run(run_id, target, criteria, plan_dict):
    init_store()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO test_runs (run_id, target_url, openapi_url, criteria, plan, status) "
            "VALUES (?, ?, ?, ?, ?, 'queued')",
            (run_id, target.base_url, target.openapi_url,
             json.dumps(sorted(criteria)), json.dumps(plan_dict)),
        )


def update_run(run_id, status):
    with _lock, _conn() as c:
        if status in ("done", "failed"):
            c.execute("UPDATE test_runs SET status = ?, completed_at = CURRENT_TIMESTAMP "
                      "WHERE run_id = ?", (status, run_id))
        else:
            c.execute("UPDATE test_runs SET status = ? WHERE run_id = ?", (status, run_id))


def save_result(run_id, position, result):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO test_results (run_id, position, module, status, result, duration_s) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, position, result.module, result.status.value,
             json.dumps(result.to_dict()), result.duration_s),
        )


def get_run(run_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM test_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        rows = c.execute(
            "SELECT result FROM test_results WHERE run_id = ? ORDER BY position, id",
            (run_id,)).fetchall()
    results = [json.loads(r["result"]) for r in rows]
    run = dict(row)
    run["criteria"] = json.loads(run["criteria"])
    run["plan"] = json.loads(run["plan"])
    run["results"] = results
    run["verdict"] = (
        worst(Status(r["status"]) for r in results).value
        if run["status"] == "done" else None
    )
    return run


def list_runs(limit=50):
    with _conn() as c:
        rows = c.execute(
            "SELECT run_id, target_url, status, created_at, completed_at "
            "FROM test_runs ORDER BY created_at DESC" + ("" if db.is_postgres() else ", rowid DESC")
            + " LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def reap_stale(max_age_s=1800):
    """Marks runs that started long ago and never finished as failed. This
    happens when an instance is stopped mid-run; without it those runs would
    count as active forever and block new ones. Returns how many were marked."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).strftime("%Y-%m-%d %H:%M:%S")
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE test_runs SET status = 'failed', completed_at = CURRENT_TIMESTAMP "
            "WHERE status IN ('queued', 'running') AND created_at < ?", (cutoff,))
        return cur.rowcount