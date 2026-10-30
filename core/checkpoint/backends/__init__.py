"""core/checkpoint/backends

Resource-specific checkpoint backends.
Part of Milestone R2 Task R2.11.
"""

from core.checkpoint.backends.base import BaseCheckpointBackend
from core.checkpoint.backends.file import FileCheckpointBackend
from core.checkpoint.backends.git import GitCheckpointBackend
from core.checkpoint.backends.database import DatabaseCheckpointBackend
from core.checkpoint.backends.config import ConfigCheckpointBackend

__all__ = [
    "BaseCheckpointBackend",
    "FileCheckpointBackend",
    "GitCheckpointBackend",
    "DatabaseCheckpointBackend",
    "ConfigCheckpointBackend",
]
