"""core/rooms/mapper.py

Room ↔ Project Mapping subsystem for Agent Engine.
Part of Phase 5B (Task 5B.1 - Milestone M4).

Satisfies ADR-014: Collaborative Rooms as Project Overlay.
Rooms provide a persistent multi-agent collaboration space layered on top of projects
without duplicating workspace folders or Git repositories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from core.storage import get_storage_backend
from core.storage.base import StorageBackend

logger = logging.getLogger("agent_engine.rooms.mapper")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CollaborativeRoom:
    """
    Domain model for a collaborative multi-agent room overlaying a project.
    """

    room_id: str
    project_id: str
    name: str
    description: str = ""
    topic: str = ""
    status: str = "active"  # "active", "archived", "closed"
    policy_id: Optional[str] = None
    active_adapters: List[str] = field(default_factory=list)
    session_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room_id": self.room_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "topic": self.topic,
            "status": self.status,
            "policy_id": self.policy_id,
            "active_adapters": list(self.active_adapters),
            "session_ids": list(self.session_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CollaborativeRoom:
        return cls(
            room_id=data.get("room_id") or f"room_{uuid.uuid4().hex[:10]}",
            project_id=data.get("project_id", "default"),
            name=data.get("name", "Untitled Room"),
            description=data.get("description", ""),
            topic=data.get("topic", ""),
            status=data.get("status", "active"),
            policy_id=data.get("policy_id"),
            active_adapters=list(data.get("active_adapters") or []),
            session_ids=list(data.get("session_ids") or []),
            created_at=data.get("created_at") or _now_iso(),
            updated_at=data.get("updated_at") or _now_iso(),
            metadata=dict(data.get("metadata") or {}),
        )


class RoomProjectMapper:
    """
    Manages Room ↔ Project mappings and coordinates collaborative context overlay.
    """

    def __init__(self, storage: Optional[StorageBackend] = None):
        self.storage = storage or get_storage_backend()

    def create_room(
        self,
        project_id: str,
        name: str,
        description: str = "",
        topic: str = "",
        policy_id: Optional[str] = None,
        active_adapters: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        room_id: Optional[str] = None,
    ) -> CollaborativeRoom:
        """
        Create a new collaborative room overlaying a project.
        """
        r_id = room_id or f"room_{uuid.uuid4().hex[:10]}"
        now = _now_iso()
        adapters = (
            active_adapters if active_adapters is not None else ["claude-code", "codex", "goose"]
        )

        room = CollaborativeRoom(
            room_id=r_id,
            project_id=project_id,
            name=name,
            description=description,
            topic=topic,
            status="active",
            policy_id=policy_id,
            active_adapters=adapters,
            session_ids=[],
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        saved = self.storage.create_room(room.to_dict())
        return CollaborativeRoom.from_dict(saved)

    def get_room(self, room_id: str) -> Optional[CollaborativeRoom]:
        """Retrieve a room by ID."""
        data = self.storage.get_room(room_id)
        if not data:
            return None
        return CollaborativeRoom.from_dict(data)

    def list_rooms(
        self, project_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[CollaborativeRoom]:
        """List rooms matching optional project or status filters."""
        raw_rooms = self.storage.list_rooms(project_id=project_id, status=status)
        return [CollaborativeRoom.from_dict(r) for r in raw_rooms]

    def update_room(self, room_id: str, **updates) -> Optional[CollaborativeRoom]:
        """Update room metadata, topic, policy, or active adapters."""
        updated = self.storage.update_room(room_id, updates)
        if not updated:
            return None
        return CollaborativeRoom.from_dict(updated)

    def archive_room(self, room_id: str) -> bool:
        """Archive a room by setting its status to 'archived'."""
        updated = self.update_room(room_id, status="archived")
        return updated is not None and updated.status == "archived"

    def delete_room(self, room_id: str) -> bool:
        """Permanently delete a room record."""
        return self.storage.delete_room(room_id)

    def attach_session_to_room(self, room_id: str, session_id: str) -> bool:
        """Associate a multi-agent session thread with this room."""
        room = self.get_room(room_id)
        if not room:
            return False

        if session_id not in room.session_ids:
            new_sessions = list(room.session_ids) + [session_id]
            updated = self.update_room(room_id, session_ids=new_sessions)
            return updated is not None
        return True

    def build_room_context(
        self,
        room_id: str,
        prompt: str,
        project_instructions: Optional[str] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Build contextual overlay for agent execution in this room.
        Adheres to ADR-014: project instructions, room topic, and files are
        injected into context without altering project filesystem trees.
        """
        room = self.get_room(room_id)
        if not room:
            raise ValueError(f"Room '{room_id}' not found")

        # Combine instructions
        instructions_parts = []
        if project_instructions:
            instructions_parts.append(f"[Project Instructions]: {project_instructions}")
        if room.description:
            instructions_parts.append(f"[Room Description]: {room.description}")
        if room.topic:
            instructions_parts.append(f"[Room Current Topic]: {room.topic}")

        scoped_prefix = "\n".join(instructions_parts)

        return {
            "room_id": room.room_id,
            "project_id": room.project_id,
            "room_name": room.name,
            "topic": room.topic,
            "policy_id": room.policy_id,
            "active_adapters": list(room.active_adapters),
            "instructions_prefix": scoped_prefix,
            "augmented_prompt": f"{scoped_prefix}\n\n[User Request]: {prompt}"
            if scoped_prefix
            else prompt,
            "files": list(files or []),
            "metadata": dict(room.metadata),
        }
