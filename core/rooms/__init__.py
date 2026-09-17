"""core/rooms package.

Native Collaborative Rooms subsystem for Agent Engine (ADR-014).
Provides multi-agent project overlays, roles & governance, and persistent task queues.
Part of Phase 5B (Milestone M4).
"""

from core.rooms.mapper import CollaborativeRoom, RoomProjectMapper
from core.rooms.roles import (
    DEFAULT_ROLE_PERMISSIONS,
    RoomGovernance,
    RoomParticipant,
    RoomRole,
)
from core.rooms.tasks import (
    RoomTask,
    RoomTaskManager,
    RoomTaskPriority,
    RoomTaskStatus,
)

__all__ = [
    "CollaborativeRoom",
    "RoomProjectMapper",
    "RoomRole",
    "RoomParticipant",
    "RoomGovernance",
    "DEFAULT_ROLE_PERMISSIONS",
    "RoomTask",
    "RoomTaskStatus",
    "RoomTaskPriority",
    "RoomTaskManager",
]
