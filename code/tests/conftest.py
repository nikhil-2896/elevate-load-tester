"""Shared test setup. Runs before any test module imports the app.

Isolates the SQLite file and the results folder in a temp directory so tests
never touch real data, and puts code/ on sys.path so tests import the modules
through the same names the app uses (the contract's names).
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="load_tester_tests_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ.pop("USE_SQS", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def pytest_sessionstart(session):
    # Before collection: the results folder is made relative to the cwd on import.
    os.chdir(_TMP)


@pytest.fixture()
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()
