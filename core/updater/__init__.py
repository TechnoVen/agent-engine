"""core/updater/__init__.py

Core auto-update package for Agent Engine.
Exports UpdateManager, UpdateChannel, SemVer, and UpdateInfo.
"""

from core.updater.manager import (
    SemVer,
    UpdateChannel,
    UpdateInfo,
    UpdateManager,
    get_update_manager,
    reset_update_manager,
)

__all__ = [
    "SemVer",
    "UpdateChannel",
    "UpdateInfo",
    "UpdateManager",
    "get_update_manager",
    "reset_update_manager",
]
