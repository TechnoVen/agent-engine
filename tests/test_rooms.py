"""tests/test_rooms.py

Unit and integration tests for Native Collaborative Rooms (Phase 5B - Milestone M4).
Covers:
- Task 5B.1: Room ↔ Project Mapping, CollaborativeRoom domain model, storage persistence, and context injection.
"""

from pathlib import Path
import tempfile

import pytest

from core.rooms import (
    CollaborativeRoom,
    RoomGovernance,
    RoomParticipant,
    RoomProjectMapper,
    RoomRole,
)
from core.storage.sqlite import SQLiteBackend

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def temp_sqlite():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    backend = SQLiteBackend(db_path=db_path)
    yield backend
    try:
        Path(db_path).unlink(missing_ok=True)
    except Exception:
        pass


def test_collaborative_room_domain_model():
    """Verify CollaborativeRoom data model serialization and deserialization."""
    room = CollaborativeRoom(
        room_id="room_arch_1",
        project_id="p-1",
        name="Architecture Review",
        description="Core system architecture planning",
        topic="Evaluate ADR-014 Room Overlays",
        policy_id="policy_strict",
        active_adapters=["claude-code", "codex"],
        session_ids=["sess_101"],
        metadata={"priority": "high"},
    )

    data = room.to_dict()
    assert data["room_id"] == "room_arch_1"
    assert data["project_id"] == "p-1"
    assert data["name"] == "Architecture Review"
    assert "claude-code" in data["active_adapters"]
    assert "sess_101" in data["session_ids"]
    assert data["status"] == "active"

    rebuilt = CollaborativeRoom.from_dict(data)
    assert rebuilt.room_id == room.room_id
    assert rebuilt.project_id == room.project_id
    assert rebuilt.topic == room.topic
    assert rebuilt.active_adapters == room.active_adapters
    assert rebuilt.metadata["priority"] == "high"


def test_room_project_mapper_crud(temp_sqlite):
    """Verify RoomProjectMapper CRUD operations and persistence in SQLite."""
    mapper = RoomProjectMapper(storage=temp_sqlite)

    # 1. Create Room
    room = mapper.create_room(
        project_id="p-project-alpha",
        name="Incident Response #404",
        description="Investigating sidecar socket timeout",
        topic="Triage sidecar IPC latency",
        policy_id="strict_zero_trust",
        active_adapters=["claude-code", "goose"],
        metadata={"incident_id": "INC-404"},
    )
    assert room.room_id.startswith("room_")
    assert room.project_id == "p-project-alpha"
    assert room.name == "Incident Response #404"
    assert room.status == "active"

    # 2. Get Room
    retrieved = mapper.get_room(room.room_id)
    assert retrieved is not None
    assert retrieved.room_id == room.room_id
    assert retrieved.name == room.name
    assert "claude-code" in retrieved.active_adapters

    # 3. List Rooms by Project
    rooms_p1 = mapper.list_rooms(project_id="p-project-alpha")
    assert len(rooms_p1) == 1
    assert rooms_p1[0].room_id == room.room_id

    rooms_p2 = mapper.list_rooms(project_id="p-other")
    assert len(rooms_p2) == 0

    # 4. Update Room
    updated = mapper.update_room(
        room.room_id,
        topic="Resolution verified",
        description="Root cause identified in socket timeout",
    )
    assert updated is not None
    assert updated.topic == "Resolution verified"
    assert "Root cause" in updated.description

    # 5. Attach Session
    assert mapper.attach_session_to_room(room.room_id, "session_live_1") is True
    re_retrieved = mapper.get_room(room.room_id)
    assert "session_live_1" in re_retrieved.session_ids

    # 6. Archive Room
    assert mapper.archive_room(room.room_id) is True
    archived = mapper.get_room(room.room_id)
    assert archived.status == "archived"

    # 7. Delete Room
    assert mapper.delete_room(room.room_id) is True
    assert mapper.get_room(room.room_id) is None


def test_room_context_overlay_injection(temp_sqlite):
    """Verify build_room_context injects project & room context according to ADR-014."""
    mapper = RoomProjectMapper(storage=temp_sqlite)

    room = mapper.create_room(
        project_id="p-core",
        name="Feature Engineering",
        description="Refactoring DSPy modules",
        topic="Implement multi-agent consensus",
        policy_id="policy_strict",
        active_adapters=["claude-code", "codex", "hermes"],
    )

    context = mapper.build_room_context(
        room_id=room.room_id,
        prompt="Synthesize consensus algorithm for voting agents",
        project_instructions="Always write modular clean code with type annotations.",
        files=[{"name": "consensus.py", "size": "2kb"}],
    )

    assert context["room_id"] == room.room_id
    assert context["project_id"] == "p-core"
    assert context["policy_id"] == "policy_strict"
    assert "claude-code" in context["active_adapters"]
    assert len(context["files"]) == 1

    # Check prompt augmentation
    aug = context["augmented_prompt"]
    assert "[Project Instructions]: Always write modular clean code with type annotations." in aug
    assert "[Room Description]: Refactoring DSPy modules" in aug
    assert "[Room Current Topic]: Implement multi-agent consensus" in aug
    assert "[User Request]: Synthesize consensus algorithm for voting agents" in aug


def test_room_context_nonexistent_room(temp_sqlite):
    """Verify build_room_context raises ValueError for nonexistent room ID."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    with pytest.raises(ValueError, match="not found"):
        mapper.build_room_context("room_ghost", prompt="test")


def test_room_role_permissions_matrix():
    """Verify RoomRole permissions matrix for ADMIN, MEMBER, VIEWER, and AGENT."""
    admin = RoomParticipant(
        room_id="room_1",
        participant_id="user_admin",
        name="Lead Engineer",
        role=RoomRole.ADMIN,
    )
    assert admin.has_permission("manage_room")
    assert admin.has_permission("change_roles")
    assert admin.has_permission("manage_participants")
    assert admin.has_permission("execute_tasks")

    member = RoomParticipant(
        room_id="room_1",
        participant_id="user_member",
        name="Developer",
        role=RoomRole.MEMBER,
    )
    assert member.has_permission("create_tasks")
    assert member.has_permission("execute_tasks")
    assert not member.has_permission("manage_room")
    assert not member.has_permission("change_roles")

    viewer = RoomParticipant(
        room_id="room_1",
        participant_id="user_viewer",
        name="Auditor",
        role=RoomRole.VIEWER,
    )
    assert viewer.has_permission("view_history")
    assert viewer.has_permission("read_messages")
    assert not viewer.has_permission("create_tasks")
    assert not viewer.has_permission("execute_tasks")

    agent = RoomParticipant(
        room_id="room_1",
        participant_id="agent_claude",
        name="Claude Code Adapter",
        role=RoomRole.AGENT,
        participant_type="agent",
        adapter_type="claude-code",
    )
    assert agent.has_permission("execute_tasks")
    assert agent.has_permission("claim_tasks")
    assert agent.has_permission("update_task_progress")
    assert not agent.has_permission("manage_room")

    # Custom permission grant
    custom = RoomParticipant(
        room_id="room_1",
        participant_id="user_custom",
        name="Senior Dev",
        role=RoomRole.MEMBER,
        permissions=["create_tasks", "custom_permission_x"],
    )
    assert custom.has_permission("custom_permission_x")


def test_room_governance_add_and_list_participants(temp_sqlite):
    """Verify RoomGovernance adds, lists, and queries room participants."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    gov = RoomGovernance(storage=temp_sqlite)

    room = mapper.create_room(
        project_id="p-alpha",
        name="Dev Room",
        description="Collaborative room for dev",
    )

    # Add Admin
    admin = gov.add_participant(
        room_id=room.room_id,
        participant_id="user_1",
        name="Alice",
        role=RoomRole.ADMIN,
    )
    assert admin.role == RoomRole.ADMIN
    assert admin.has_permission("manage_room")

    # Add Agent Adapter
    agent = gov.add_participant(
        room_id=room.room_id,
        participant_id="agent_1",
        name="Claude Worker",
        role=RoomRole.AGENT,
        participant_type="agent",
        adapter_type="claude-code",
    )
    assert agent.participant_type == "agent"
    assert agent.adapter_type == "claude-code"

    # Verify room's active_adapters was updated automatically
    updated_room = mapper.get_room(room.room_id)
    assert "claude-code" in updated_room.active_adapters

    # List participants
    participants = gov.list_participants(room.room_id)
    assert len(participants) == 2
    participant_ids = {p.participant_id for p in participants}
    assert "user_1" in participant_ids
    assert "agent_1" in participant_ids

    # Query individual participant
    p = gov.get_participant(room.room_id, "user_1")
    assert p is not None
    assert p.name == "Alice"


def test_room_governance_rbac_and_role_change(temp_sqlite):
    """Verify RBAC rules: changing roles, permissions, and participant removal."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    gov = RoomGovernance(storage=temp_sqlite)

    room = mapper.create_room(
        project_id="p-alpha",
        name="Gov Room",
    )

    gov.add_participant(
        room_id=room.room_id,
        participant_id="admin_user",
        role=RoomRole.ADMIN,
    )
    gov.add_participant(
        room_id=room.room_id,
        participant_id="regular_member",
        role=RoomRole.MEMBER,
    )
    gov.add_participant(
        room_id=room.room_id,
        participant_id="viewer_user",
        role=RoomRole.VIEWER,
    )

    # 1. Non-admin cannot change roles
    with pytest.raises(PermissionError, match="does not have 'change_roles'"):
        gov.change_role(
            room_id=room.room_id,
            participant_id="viewer_user",
            new_role=RoomRole.MEMBER,
            requested_by_id="regular_member",
        )

    # 2. Admin can change role
    promoted = gov.change_role(
        room_id=room.room_id,
        participant_id="viewer_user",
        new_role=RoomRole.MEMBER,
        requested_by_id="admin_user",
    )
    assert promoted.role == RoomRole.MEMBER
    assert promoted.has_permission("create_tasks")

    # 3. Non-admin cannot remove other participant
    with pytest.raises(PermissionError, match="does not have 'manage_participants'"):
        gov.remove_participant(
            room_id=room.room_id,
            participant_id="viewer_user",
            requested_by_id="regular_member",
        )

    # 4. Self-removal is permitted without admin
    assert (
        gov.remove_participant(
            room_id=room.room_id,
            participant_id="regular_member",
            requested_by_id="regular_member",
        )
        is True
    )
    assert gov.get_participant(room.room_id, "regular_member") is None

    # 5. Admin removal of participant
    assert (
        gov.remove_participant(
            room_id=room.room_id,
            participant_id="viewer_user",
            requested_by_id="admin_user",
        )
        is True
    )
    assert gov.get_participant(room.room_id, "viewer_user") is None
