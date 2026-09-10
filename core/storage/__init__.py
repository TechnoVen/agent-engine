"""Storage repository module for Agent Engine.

Provides unified storage abstraction (ADR-003 / Conflict C3) supporting both
local SQLite and cloud PostgreSQL backends.
"""

import os
from typing import Optional

from core.storage.base import (
    BenchmarkRecord,
    CostRecord,
    PatchRecord,
    PolicyRecord,
    SessionRecord,
    StorageBackend,
    UserRecord,
)
from core.storage.postgres import PostgresBackend
from core.storage.sqlite import DEFAULT_SQLITE_PATH, SQLiteBackend

_GLOBAL_BACKEND: Optional[StorageBackend] = None


def get_storage_backend(
    backend_type: Optional[str] = None,
    db_path: Optional[str] = None,
    connection_url: Optional[str] = None,
    force_new: bool = False,
) -> StorageBackend:
    """Retrieve or initialize configured StorageBackend.

    Selection priority:
    1. Explicit `backend_type` parameter ('sqlite' or 'postgres')
    2. `STORAGE_BACKEND` environment variable ('sqlite' or 'postgres')
    3. Defaults to 'sqlite' for zero-setup local execution.
    """
    global _GLOBAL_BACKEND
    if (
        _GLOBAL_BACKEND is not None
        and not force_new
        and db_path is None
        and backend_type is None
        and connection_url is None
    ):
        return _GLOBAL_BACKEND

    b_type = (backend_type or os.getenv("STORAGE_BACKEND") or "sqlite").strip().lower()

    backend: StorageBackend
    if b_type in ("postgres", "postgresql"):
        url = connection_url or os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
        backend = PostgresBackend(connection_url=url)
    else:
        path = db_path or os.getenv("SQLITE_DB_PATH") or DEFAULT_SQLITE_PATH
        backend = SQLiteBackend(db_path=path)

    if not force_new and db_path is None and connection_url is None:
        _GLOBAL_BACKEND = backend
    return backend


def reset_storage_backend() -> None:
    """Reset the global storage backend instance (useful for test teardown)."""
    global _GLOBAL_BACKEND
    if _GLOBAL_BACKEND is not None:
        _GLOBAL_BACKEND.close()
        _GLOBAL_BACKEND = None


__all__ = [
    "StorageBackend",
    "SQLiteBackend",
    "PostgresBackend",
    "PatchRecord",
    "SessionRecord",
    "UserRecord",
    "PolicyRecord",
    "CostRecord",
    "BenchmarkRecord",
    "get_storage_backend",
    "reset_storage_backend",
    "DEFAULT_SQLITE_PATH",
]
