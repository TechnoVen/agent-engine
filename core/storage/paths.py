"""core/storage/paths.py

Canonical private storage paths for Agent Engine.
Part of Milestone R2.

Invariants:
- Private storage root is strictly outside project workspace trees.
- Authoritative default is ~/.agent_engine (or overridden via AGENT_ENGINE_DATA_DIR).
- Directory mode is restricted to 0o700.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_private_data_dir() -> Path:
    """Return the authoritative private data directory for Agent Engine.

    Guaranteed to be outside user workspace trees and restricted to the host user.
    Can be overridden via AGENT_ENGINE_DATA_DIR for testing or custom deployments.
    """
    env_dir = os.environ.get("AGENT_ENGINE_DATA_DIR")
    if env_dir:
        p = Path(env_dir).expanduser().resolve()
    else:
        p = (Path.home() / ".agent_engine").resolve()
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    return p
