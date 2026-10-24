"""Proof that the person running a test controls the target.

1. POST /api/v2/ownership/token  -> a random token for the target's host.
2. The owner serves that token at <target>/.well-known/testkit-verify.
3. POST /api/v2/ownership/verify -> we fetch it; a match marks the host verified.

Operators can also list hosts they trust (for local demos) in the
TESTKIT_AUTO_VERIFY_HOSTS environment variable, comma separated.
"""
import os
from urllib.parse import urlparse

from testkit import store
from testkit.safety import Budget, SafeClient, new_ownership_token, verify_ownership


def host_of(url):
    return (urlparse(url).netloc or "").lower()


def _init():
    with store._conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS testkit_ownership (
            host TEXT PRIMARY KEY, token TEXT, verified INTEGER DEFAULT 0, verified_at TEXT)""")


def issue_token(url):
    _init()
    host = host_of(url)
    with store._lock, store._conn() as c:
        row = c.execute("SELECT token FROM testkit_ownership WHERE host = ?", (host,)).fetchone()
        if row:
            return row["token"]
        token = new_ownership_token()
        c.execute("INSERT INTO testkit_ownership (host, token) VALUES (?, ?)", (host, token))
        return token


def verify(url):
    """Fetches the token file and records the result. Returns True/False."""
    _init()
    host = host_of(url)
    with store._conn() as c:
        row = c.execute("SELECT token FROM testkit_ownership WHERE host = ?", (host,)).fetchone()
    if not row:
        return False
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    ok = verify_ownership(base, row["token"], SafeClient(Budget(3, 20)))
    if ok:
        with store._lock, store._conn() as c:
            c.execute("UPDATE testkit_ownership SET verified = 1, verified_at = CURRENT_TIMESTAMP "
                      "WHERE host = ?", (host,))
    return ok


def is_verified(url):
    host = host_of(url)
    trusted = {h.strip().lower() for h in os.environ.get("TESTKIT_AUTO_VERIFY_HOSTS", "").split(",") if h.strip()}
    if host in trusted or (urlparse(url).hostname or "").lower() in trusted:
        return True
    _init()
    with store._conn() as c:
        row = c.execute("SELECT verified FROM testkit_ownership WHERE host = ?", (host,)).fetchone()
    return bool(row and row["verified"])