# Ensure numpy and core modules are loaded cleanly before dspy lazy-loads
import os
from pathlib import Path
import tempfile
import numpy  # noqa: F401
import pytest

from core.session.store import reset_session_store
from core.storage import reset_storage_backend

# Enforce test isolation: automated test suites must never write into the dogfood database (data/agent_engine.db)
# or dogfood vector store (data/chroma)
_TEST_DATA_DIR = tempfile.TemporaryDirectory(prefix="agent_engine_test_suite_")
_TEST_DB_PATH = str(Path(_TEST_DATA_DIR.name) / "test_agent_engine.db")
_TEST_CHROMA_DIR = str(Path(_TEST_DATA_DIR.name) / "test_chroma")
os.environ["SQLITE_DB_PATH"] = _TEST_DB_PATH
os.environ["CHROMA_PERSIST_DIR"] = _TEST_CHROMA_DIR
os.environ["AGENT_ENGINE_DATA_DIR"] = _TEST_DATA_DIR.name

from core.memory.vector import reset_chroma_clients
from services.python.server.container import set_services

reset_storage_backend()
reset_session_store()
reset_chroma_clients()
set_services(None)


@pytest.fixture(autouse=True)
def isolate_test_storage(monkeypatch):
    """Enforce that every test runs against an isolated database and vector store, protecting data/agent_engine.db and data/chroma."""
    monkeypatch.setenv("SQLITE_DB_PATH", _TEST_DB_PATH)
    monkeypatch.setenv("CHROMA_PERSIST_DIR", _TEST_CHROMA_DIR)
    monkeypatch.setenv("AGENT_ENGINE_DATA_DIR", _TEST_DATA_DIR.name)
    reset_chroma_clients()
    set_services(None)
