import os
import threading
from contextlib import contextmanager

import db

DB_PATH = os.environ.get("DB_PATH", "load_tests.db")
_lock = threading.Lock()


@contextmanager
def _get_conn():
    with db.connect(DB_PATH) as conn:
        yield conn


def init_db():
    with _get_conn() as conn:
        conn.ddl_lock()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                target_url TEXT,
                users INTEGER,
                spawn_rate INTEGER,
                duration_seconds INTEGER,
                status TEXT,
                stats_csv TEXT,
                stdout TEXT,
                stderr TEXT,
                error TEXT,
                group_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_groups (
                group_id TEXT PRIMARY KEY,
                target_url TEXT,
                job_type TEXT,
                users INTEGER,
                spawn_rate INTEGER,
                duration_seconds INTEGER,
                child_count INTEGER,
                status TEXT,
                aggregated_stats_csv TEXT,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)
        # Databases created before group_id existed need the column added.
        # PostgreSQL tables are always created with it; SQLite is checked first.
        if not conn.pg:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
            if "group_id" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN group_id TEXT")


def create_job(job_id, target_url, users, spawn_rate, duration_seconds, group_id=None):
    with _lock, _get_conn() as conn:
        conn.execute(
            """INSERT INTO jobs (job_id, target_url, users, spawn_rate, duration_seconds, status, group_id)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (job_id, target_url, users, spawn_rate, duration_seconds, group_id),
        )


def update_job(job_id, **fields):
    if not fields:
        return
    with _lock, _get_conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [job_id]
        if "status" in fields and fields["status"] in ("completed", "failed", "timeout"):
            set_clause += ", completed_at = CURRENT_TIMESTAMP"
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)


def get_job(job_id):
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit=50):
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT job_id, target_url, users, status, created_at, completed_at "
            "FROM jobs WHERE group_id IS NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_job_group(group_id, target_url, job_type, users, spawn_rate, duration_seconds, child_count):
    with _lock, _get_conn() as conn:
        conn.execute(
            """INSERT INTO job_groups
               (group_id, target_url, job_type, users, spawn_rate, duration_seconds, child_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')""",
            (group_id, target_url, job_type, users, spawn_rate, duration_seconds, child_count),
        )


def update_job_group(group_id, **fields):
    if not fields:
        return
    with _lock, _get_conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [group_id]
        if "status" in fields and fields["status"] in ("completed", "failed"):
            set_clause += ", completed_at = CURRENT_TIMESTAMP"
        conn.execute(f"UPDATE job_groups SET {set_clause} WHERE group_id = ?", values)


def get_job_group(group_id):
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM job_groups WHERE group_id = ?", (group_id,)).fetchone()
        return dict(row) if row else None


def list_child_jobs(group_id):
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE group_id = ? ORDER BY created_at ASC", (group_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_job_groups(limit=50):
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT group_id, target_url, users, status, created_at, completed_at "
            "FROM job_groups ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]