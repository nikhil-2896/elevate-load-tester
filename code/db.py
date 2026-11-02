"""One place that opens database connections.

DATABASE_URL set to postgresql://...  -> PostgreSQL (use this when running more
than one instance, so every instance sees the same data).
Otherwise                              -> the SQLite file in DB_PATH (local use).

Callers write SQL with '?' placeholders; they are translated for PostgreSQL.
Rows can be read as row["column"] and converted with dict(row) on both.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

_pool = None
_pool_lock = threading.Lock()


def is_postgres():
    return os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://"))


def autoinc_pk():
    """Column type for an auto-numbered primary key."""
    return "BIGSERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"


class _Conn:
    def __init__(self, raw, pg):
        self.raw, self.pg = raw, pg

    def execute(self, sql, params=()):
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(sql.replace("?", "%s"), tuple(params))
            return cur
        return self.raw.execute(sql, params)

    def ddl_lock(self):
        """Stops two instances creating the same tables at the same moment."""
        if self.pg:
            self.execute("SELECT pg_advisory_xact_lock(724301)")


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg2.extras import RealDictCursor
            from psycopg2.pool import ThreadedConnectionPool
            _pool = ThreadedConnectionPool(
                1, int(os.environ.get("DB_POOL_MAX", "10")), os.environ["DATABASE_URL"],
                cursor_factory=RealDictCursor, options="-c timezone=UTC")
        return _pool


@contextmanager
def connect(sqlite_path=None):
    if is_postgres():
        pool = _get_pool()
        raw = pool.getconn()
        try:
            yield _Conn(raw, True)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            pool.putconn(raw)
    else:
        raw = sqlite3.connect(sqlite_path or os.environ.get("DB_PATH", "load_tests.db"), timeout=10)
        raw.row_factory = sqlite3.Row
        try:
            yield _Conn(raw, False)
            raw.commit()
        finally:
            raw.close()