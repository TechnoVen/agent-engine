"""core/rooms/roles.py

Room Roles, Permissions, and Governance for Native Collaborative Rooms (ADR-014).
Supports RBAC for human operators and autonomous agent adapters (Milestone M4).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union

from core.storage.base import StorageBackend


class RoomRole(str, Enum):
    """Roles for participants in a collaborative room."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    AGENT = "agent"


# Canonical permission sets per role
DEFAULT_ROLE_PERMISSIONS: Dict[RoomRole, Set[str]] = {
    RoomRole.ADMIN: {
        "manage_room",
        "manage_participants",
        "manage_tasks",
        "execute_tasks",
        "claim_tasks",
        "create_tasks",
        "invite_adapters",
        "change_roles",
        "view_history",
        "send_messages",
        "read_messages",
        "archive_room",
        "delete_room",
    },
    RoomRole.MEMBER: {
        "create_tasks",
        "execute_tasks",
        "claim_tasks",
        "send_messages",
        "read_messages",
        "view_history",
        "view_tasks",
    },
    RoomRole.VIEWER: {
        "view_history",
        "view_tasks",
        "read_messages",
    },
    RoomRole.AGENT: {
        "execute_tasks",
        "claim_tasks",
        "create_subtasks",
        "send_messages",
        "read_messages",
        "view_history",
        "view_tasks",
        "update_task_progress",
    },
}


@dataclass
class RoomParticipant:
    """Participant in a collaborative room (Human or Agent Adapter)."""

    room_id: str
    participant_id: str
    name: str
    role: RoomRole
    participant_type: str = "human"  # "human" | "agent"
    adapter_type: Optional[str] = None  # e.g. "claude-code", "codex", "hermes"
    permissions: List[str] = field(default_factory=list)
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.role, str):
            self.role = RoomRole(self.role)
        if not self.permissions:
            self.permissions = sorted(DEFAULT_ROLE_PERMISSIONS.get(self.role, set()))

    def has_permission(self, permission: str) -> bool:
        """Check whether participant has a specific permission."""
        if permission in self.permissions:
            return True
        return permission in DEFAULT_ROLE_PERMISSIONS.get(self.role, set())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room_id": self.room_id,
            "participant_id": self.participant_id,
            "name": self.name,
            "role": self.role.value if isinstance(self.role, RoomRole) else str(self.role),
            "participant_type": self.participant_type,
            "adapter_type": self.adapter_type,
            "permissions": self.permissions,
            "joined_at": self.joined_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoomParticipant":
        return cls(
            room_id=data["room_id"],
            participant_id=data["participant_id"],
            name=data.get("name", data["participant_id"]),
            role=RoomRole(data.get("role", "member")),
            participant_type=data.get("participant_type", "human"),
            adapter_type=data.get("adapter_type"),
            permissions=list(data.get("permissions") or []),
            joined_at=data.get("joined_at") or datetime.now(timezone.utc).isoformat(),
            metadata=dict(data.get("metadata") or {}),
        )


class RoomGovernance:
    """Governance and RBAC manager for Collaborative Rooms."""

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage

    def add_participant(
        self,
        room_id: str,
        participant_id: str,
        name: Optional[str] = None,
        role: Union[RoomRole, str] = RoomRole.MEMBER,
        participant_type: str = "human",
        adapter_type: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RoomParticipant:
        """Add or update a participant in the specified room."""
        room = self.storage.get_room(room_id)
        if not room:
            raise ValueError(f"Collaborative room '{room_id}' not found.")

        role_enum = RoomRole(role) if isinstance(role, str) else role
        resolved_perms = (
            permissions
            if permissions is not None
            else sorted(DEFAULT_ROLE_PERMISSIONS.get(role_enum, set()))
        )

        participant = RoomParticipant(
            room_id=room_id,
            participant_id=participant_id,
            name=name or participant_id,
            role=role_enum,
            participant_type=participant_type,
            adapter_type=adapter_type,
            permissions=resolved_perms,
            joined_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )

        self.storage.add_room_participant(participant.to_dict())

        # If participant is an agent adapter, ensure it is recorded in room's active_adapters
        if adapter_type and adapter_type not in (room.get("active_adapters") or []):
            current_adapters = list(room.get("active_adapters") or [])
            current_adapters.append(adapter_type)
            self.storage.update_room(room_id, {"active_adapters": current_adapters})

        return participant

    def get_participant(self, room_id: str, participant_id: str) -> Optional[RoomParticipant]:
        """Fetch participant details from storage."""
        data = self.storage.get_room_participant(room_id, participant_id)
        if not data:
            return None
        return RoomParticipant.from_dict(data)

    def list_participants(self, room_id: str) -> List[RoomParticipant]:
        """List all participants registered in the room."""
        records = self.storage.list_room_participants(room_id)
        return [RoomParticipant.from_dict(r) for r in records]

    def can_perform(self, room_id: str, participant_id: str, permission: str) -> bool:
        """Evaluate if participant has the required permission in the given room."""
        participant = self.get_participant(room_id, participant_id)
        if not participant:
            return False
        return participant.has_permission(permission)

    def change_role(
        self,
        room_id: str,
        participant_id: str,
        new_role: Union[RoomRole, str],
        requested_by_id: str,
    ) -> RoomParticipant:
        """Change participant role, enforcing that requested_by has 'change_roles' permission."""
        if not self.can_perform(room_id, requested_by_id, "change_roles"):
            raise PermissionError(
                f"Participant '{requested_by_id}' does not have 'change_roles' permission in room '{room_id}'."
            )

        participant = self.get_participant(room_id, participant_id)
        if not participant:
            raise ValueError(f"Participant '{participant_id}' not found in room '{room_id}'.")

        new_role_enum = RoomRole(new_role) if isinstance(new_role, str) else new_role
        new_permissions = sorted(DEFAULT_ROLE_PERMISSIONS.get(new_role_enum, set()))

        updated_data = self.storage.update_room_participant(
            room_id,
            participant_id,
            {
                "role": new_role_enum.value,
                "permissions": new_permissions,
            },
        )
        if not updated_data:
            raise RuntimeError(f"Failed to update participant '{participant_id}'.")

        return RoomParticipant.from_dict(updated_data)

    def remove_participant(
        self,
        room_id: str,
        participant_id: str,
        requested_by_id: str,
    ) -> bool:
        """Remove participant from room, enforcing admin rights or self-leave."""
        is_self = participant_id == requested_by_id
        if not is_self and not self.can_perform(room_id, requested_by_id, "manage_participants"):
            raise PermissionError(
                f"Participant '{requested_by_id}' does not have 'manage_participants' permission to remove '{participant_id}'."
            )

        return self.storage.remove_room_participant(room_id, participant_id)
