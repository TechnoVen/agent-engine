"""tests/test_rooms.py

Unit and integration tests for Native Collaborative Rooms (Phase 5B - Milestone M4).
Covers:
- Task 5B.1: Room ↔ Project Mapping, CollaborativeRoom domain model, storage persistence, and context injection.
"""

from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
import pytest

from core.adapters.mock import MockAgentAdapter
from core.rooms import (
    CollaborativeRoom,
    RoomGovernance,
    RoomParticipant,
    RoomProjectMapper,
    RoomRole,
    RoomTask,
    RoomTaskManager,
    RoomTaskPriority,
    RoomTaskStatus,
)
from core.storage.sqlite import SQLiteBackend
from services.python.server.api import app

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


def test_room_task_domain_model():
    """Verify RoomTask serialization, deserialization, and enum conversions."""
    task = RoomTask(
        task_id="rtask_101",
        room_id="room_alpha",
        title="Implement DSPy signature",
        description="Write typed signatures for intent parser",
        status=RoomTaskStatus.PENDING,
        priority=RoomTaskPriority.HIGH,
        assigned_to="agent_codex",
        assigned_adapter="codex",
        parent_task_id=None,
        dependencies=["rtask_100"],
        created_by="alice",
        metadata={"milestone": "M4"},
    )

    data = task.to_dict()
    assert data["task_id"] == "rtask_101"
    assert data["status"] == "pending"
    assert data["priority"] == "high"
    assert data["dependencies"] == ["rtask_100"]
    assert data["assigned_adapter"] == "codex"

    rebuilt = RoomTask.from_dict(data)
    assert rebuilt.task_id == task.task_id
    assert rebuilt.status == RoomTaskStatus.PENDING
    assert rebuilt.priority == RoomTaskPriority.HIGH
    assert rebuilt.metadata["milestone"] == "M4"


def test_room_task_manager_lifecycle_and_dependencies(temp_sqlite):
    """Verify RoomTaskManager task creation, dependencies blocking, claiming, and unblocking."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    gov = RoomGovernance(storage=temp_sqlite)
    mgr = RoomTaskManager(storage=temp_sqlite, governance=gov)

    room = mapper.create_room(project_id="p-alpha", name="Workflow Room")
    gov.add_participant(room_id=room.room_id, participant_id="worker_bob", role=RoomRole.MEMBER)

    # 1. Create root task (no dependencies -> PENDING)
    t1 = mgr.create_task(
        room_id=room.room_id,
        title="Step 1: Database Schema",
        description="Migrate SQLite tables",
        created_by="alice",
    )
    assert t1.status == RoomTaskStatus.PENDING

    # 2. Create dependent task (depends on t1 -> BLOCKED)
    t2 = mgr.create_task(
        room_id=room.room_id,
        title="Step 2: Backend API",
        description="Expose FastAPI endpoints",
        dependencies=[t1.task_id],
        created_by="alice",
    )
    assert t2.status == RoomTaskStatus.BLOCKED

    # 3. Attempting to claim blocked task raises ValueError
    with pytest.raises(ValueError, match="dependencies are not yet completed"):
        mgr.claim_task(
            room_id=room.room_id,
            task_id=t2.task_id,
            participant_id="worker_bob",
        )

    # 4. Claim root task
    claimed_t1 = mgr.claim_task(
        room_id=room.room_id,
        task_id=t1.task_id,
        participant_id="worker_bob",
    )
    assert claimed_t1.status == RoomTaskStatus.IN_PROGRESS
    assert claimed_t1.assigned_to == "worker_bob"

    # 5. Complete root task -> auto unblock downstream t2
    completed_t1 = mgr.update_task_status(
        room_id=room.room_id,
        task_id=t1.task_id,
        status=RoomTaskStatus.COMPLETED,
        result={"tables_created": 3},
    )
    assert completed_t1.status == RoomTaskStatus.COMPLETED

    # Check that t2 has been automatically unblocked to PENDING
    re_t2 = mgr.get_task(room_id=room.room_id, task_id=t2.task_id)
    assert re_t2.status == RoomTaskStatus.PENDING

    # 6. Now claim t2
    claimed_t2 = mgr.claim_task(
        room_id=room.room_id,
        task_id=t2.task_id,
        participant_id="worker_bob",
    )
    assert claimed_t2.status == RoomTaskStatus.IN_PROGRESS


@pytest.mark.anyio
async def test_room_task_manager_adapter_dispatch(temp_sqlite):
    """Verify autonomous agent adapter execution dispatch for workflow steps."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    gov = RoomGovernance(storage=temp_sqlite)
    mgr = RoomTaskManager(storage=temp_sqlite, governance=gov)

    room = mapper.create_room(project_id="p-alpha", name="Dispatch Room")
    gov.add_participant(
        room_id=room.room_id,
        participant_id="mock-agent",
        role=RoomRole.AGENT,
        participant_type="agent",
        adapter_type="mock-agent",
    )

    task = mgr.create_task(
        room_id=room.room_id,
        title="Generate test summary",
        description="Echo input and calculate progress",
        created_by="system",
    )

    mock_adapter = MockAgentAdapter(adapter_id="mock-agent", name="Mock Agent")
    mock_adapter.initialize()

    result = await mgr.dispatch_task_to_adapter(
        room_id=room.room_id,
        task_id=task.task_id,
        adapter=mock_adapter,
        prompt="Execute step: Echo calculate 2 + 2",
    )

    assert "Echo [mock-agent]" in result.get("content", "")

    # Task should now be COMPLETED with result attached
    completed_task = mgr.get_task(room.room_id, task.task_id)
    assert completed_task.status == RoomTaskStatus.COMPLETED
    assert completed_task.assigned_to == "mock-agent"
    assert completed_task.result is not None


def test_room_rest_api_contract():
    """Verify full FastAPI REST API contract for Collaborative Rooms, participants, and tasks."""
    client = TestClient(app)

    # 1. Create Room
    create_payload = {
        "project_id": "p-api-test",
        "name": "API Review Room",
        "description": "Validating /v1/rooms REST endpoints",
        "topic": "Phase 5B verification",
        "active_adapters": ["claude-code"],
        "metadata": {"test": True},
    }
    res = client.post("/v1/rooms", json=create_payload)
    assert res.status_code == 201
    room = res.json()
    room_id = room["room_id"]
    assert room["name"] == "API Review Room"

    # 2. Get Room
    res = client.get(f"/v1/rooms/{room_id}")
    assert res.status_code == 200
    assert res.json()["room_id"] == room_id

    # 3. List Rooms
    res = client.get("/v1/rooms?project_id=p-api-test")
    assert res.status_code == 200
    rooms = res.json()
    assert any(r["room_id"] == room_id for r in rooms)

    # 4. Patch Room
    res = client.patch(
        f"/v1/rooms/{room_id}",
        json={"topic": "Updated Topic", "description": "New description"},
    )
    assert res.status_code == 200
    assert res.json()["topic"] == "Updated Topic"

    # 5. Room Context Overlay (ADR-014)
    res = client.get(
        f"/v1/rooms/{room_id}/context?prompt=TestPrompt&project_instructions=DoCleanCode"
    )
    assert res.status_code == 200
    ctx = res.json()
    assert "[Project Instructions]: DoCleanCode" in ctx["augmented_prompt"]

    # 6. Add Participant
    res = client.post(
        f"/v1/rooms/{room_id}/participants",
        json={
            "participant_id": "user_api_1",
            "name": "Tester",
            "role": "admin",
        },
    )
    assert res.status_code == 201
    assert res.json()["role"] == "admin"

    # 7. List Participants
    res = client.get(f"/v1/rooms/{room_id}/participants")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # 8. Create Task
    task_res = client.post(
        f"/v1/rooms/{room_id}/tasks",
        json={
            "title": "API Test Task",
            "description": "Task created via REST API",
            "priority": "high",
        },
    )
    assert task_res.status_code == 201
    task = task_res.json()
    task_id = task["task_id"]
    assert task["status"] == "pending"

    # 9. Claim Task
    claim_res = client.post(
        f"/v1/rooms/{room_id}/tasks/{task_id}/claim",
        json={"participant_id": "user_api_1"},
    )
    assert claim_res.status_code == 200
    assert claim_res.json()["status"] == "in_progress"

    # 10. Update Task
    update_res = client.patch(
        f"/v1/rooms/{room_id}/tasks/{task_id}",
        json={"status": "completed", "result": {"success": True}},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "completed"

    # 11. Delete Participant (self-leave)
    del_part = client.delete(f"/v1/rooms/{room_id}/participants/user_api_1?requested_by=user_api_1")
    assert del_part.status_code == 200
    assert del_part.json()["removed"] is True

    # 12. Delete Room
    del_room = client.delete(f"/v1/rooms/{room_id}")
    assert del_room.status_code == 200
    assert del_room.json()["deleted"] is True


def test_room_task_filtering_and_subtasks(temp_sqlite):
    """Verify task query filtering by status and assignee, plus subtask relationships."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    mgr = RoomTaskManager(storage=temp_sqlite)

    room = mapper.create_room(project_id="p-alpha", name="Subtask Room")

    # Parent Task
    parent = mgr.create_task(
        room_id=room.room_id,
        title="Parent Workflow",
        description="Coordinates subtasks",
        created_by="lead",
    )

    # Subtasks
    sub1 = mgr.create_task(
        room_id=room.room_id,
        title="Subtask 1: Parse AST",
        parent_task_id=parent.task_id,
        assigned_to="developer_1",
        created_by="lead",
    )
    sub2 = mgr.create_task(
        room_id=room.room_id,
        title="Subtask 2: Verify Lint",
        parent_task_id=parent.task_id,
        assigned_to="developer_2",
        created_by="lead",
    )

    # Filter by assignee
    dev1_tasks = mgr.list_tasks(room_id=room.room_id, assigned_to="developer_1")
    assert len(dev1_tasks) == 1
    assert dev1_tasks[0].task_id == sub1.task_id
    assert dev1_tasks[0].parent_task_id == parent.task_id
    assert sub2.parent_task_id == parent.task_id

    # Filter by status
    mgr.update_task_status(
        room_id=room.room_id, task_id=sub1.task_id, status=RoomTaskStatus.COMPLETED
    )
    completed_tasks = mgr.list_tasks(room_id=room.room_id, status=RoomTaskStatus.COMPLETED)
    assert len(completed_tasks) == 1
    assert completed_tasks[0].task_id == sub1.task_id


@pytest.mark.anyio
async def test_room_task_adapter_failure_handling(temp_sqlite):
    """Verify adapter failure transitions task to FAILED status and records error metadata."""
    mapper = RoomProjectMapper(storage=temp_sqlite)
    mgr = RoomTaskManager(storage=temp_sqlite)

    room = mapper.create_room(project_id="p-alpha", name="Failure Test Room")

    task = mgr.create_task(
        room_id=room.room_id,
        title="Crashing task",
        created_by="test",
    )

    class FailingAdapter:
        adapter_id = "failing-adapter"
        name = "Failing Adapter"

        async def execute(self, req):
            raise RuntimeError("Simulated network timeout")

    failing = FailingAdapter()
    with pytest.raises(RuntimeError, match="Simulated network timeout"):
        await mgr.dispatch_task_to_adapter(
            room_id=room.room_id,
            task_id=task.task_id,
            adapter=failing,
        )

    failed_task = mgr.get_task(room_id=room.room_id, task_id=task.task_id)
    assert failed_task.status == RoomTaskStatus.FAILED
    assert "Simulated network timeout" in failed_task.result["error"]
