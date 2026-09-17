"""tests/test_rooms.py

Unit and integration tests for Native Collaborative Rooms (Phase 5B - Milestone M4).
Covers:
- Task 5B.1: Room ↔ Project Mapping, CollaborativeRoom domain model, storage persistence, and context injection.
"""

from pathlib import Path
import tempfile

import pytest

from core.rooms import CollaborativeRoom, RoomProjectMapper
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
