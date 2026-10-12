# Ensure numpy and core modules are loaded cleanly before dspy lazy-loads
import os
from pathlib import Path
import tempfile
import numpy  # noqa: F401
import pytest

from core.session.store import reset_session_store
from core.storage import reset_storage_backend

# Enforce test isolation: automated test suites must never write into the dogfood database (data/agent_engine.db)
_TEST_DATA_DIR = tempfile.TemporaryDirectory(prefix="agent_engine_test_suite_")
_TEST_DB_PATH = str(Path(_TEST_DATA_DIR.name) / "test_agent_engine.db")
os.environ["SQLITE_DB_PATH"] = _TEST_DB_PATH

reset_storage_backend()
reset_session_store()


@pytest.fixture(autouse=True)
def isolate_test_storage(monkeypatch):
    """Enforce that every test runs against an isolated database, protecting data/agent_engine.db."""
    monkeypatch.setenv("SQLITE_DB_PATH", _TEST_DB_PATH)
