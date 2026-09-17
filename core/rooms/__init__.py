"""core/rooms package.

Native Collaborative Rooms subsystem for Agent Engine (ADR-014).
Provides multi-agent project overlays, roles & governance, and persistent task queues.
Part of Phase 5B (Milestone M4).
"""

from core.rooms.mapper import CollaborativeRoom, RoomProjectMapper

__all__ = [
    "CollaborativeRoom",
    "RoomProjectMapper",
]
