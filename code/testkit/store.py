"""Saves test runs and their results in the same SQLite file as the load
tester (DB_PATH). Tables are added beside the existing ones; nothing existing
is changed.

The target's auth token is never stored.
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from testkit.models import Status, worst

_lock = threading.Lock()


@contextmanager
def _conn():
    conn = sqlite3.connect(os.environ.get("DB_PATH", "load_tests.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_store():
    with _conn() as c:
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            "FROM test_runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]