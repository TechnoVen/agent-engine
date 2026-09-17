"""core/rooms/tasks.py

Task Objects as Workflow Steps for Native Collaborative Rooms (ADR-014).
Provides persistent task queues, dependency resolution, claim semantics,
and autonomous agent adapter execution dispatch (Milestone M4).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import inspect
from typing import Any, Dict, List, Optional, Union
import uuid

from core.rooms.roles import RoomGovernance
from core.storage.base import StorageBackend


class RoomTaskStatus(str, Enum):
    """Lifecycle status for workflow task objects in a room."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RoomTaskPriority(str, Enum):
    """Priority levels for room workflow tasks."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class RoomTask:
    """A task object functioning as a step in a room's workflow."""

    task_id: str
    room_id: str
    title: str
    description: str = ""
    status: RoomTaskStatus = RoomTaskStatus.PENDING
    priority: RoomTaskPriority = RoomTaskPriority.MEDIUM
    assigned_to: Optional[str] = None
    assigned_adapter: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    created_by: str = "human"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = RoomTaskStatus(self.status)
        if isinstance(self.priority, str):
            self.priority = RoomTaskPriority(self.priority)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "room_id": self.room_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value
            if isinstance(self.status, RoomTaskStatus)
            else str(self.status),
            "priority": self.priority.value
            if isinstance(self.priority, RoomTaskPriority)
            else str(self.priority),
            "assigned_to": self.assigned_to,
            "assigned_adapter": self.assigned_adapter,
            "parent_task_id": self.parent_task_id,
            "dependencies": self.dependencies,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoomTask":
        return cls(
            task_id=data["task_id"],
            room_id=data["room_id"],
            title=data["title"],
            description=data.get("description", ""),
            status=RoomTaskStatus(data.get("status", "pending")),
            priority=RoomTaskPriority(data.get("priority", "medium")),
            assigned_to=data.get("assigned_to"),
            assigned_adapter=data.get("assigned_adapter"),
            parent_task_id=data.get("parent_task_id"),
            dependencies=list(data.get("dependencies") or []),
            created_by=data.get("created_by", "human"),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            updated_at=data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
            result=data.get("result"),
            metadata=dict(data.get("metadata") or {}),
        )


class RoomTaskManager:
    """Manager for task queues, workflow dependencies, and agent dispatching in rooms."""

    def __init__(
        self, storage: StorageBackend, governance: Optional[RoomGovernance] = None
    ) -> None:
        self.storage = storage
        self.governance = governance

    def create_task(
        self,
        room_id: str,
        title: str,
        description: str = "",
        priority: Union[RoomTaskPriority, str] = RoomTaskPriority.MEDIUM,
        assigned_to: Optional[str] = None,
        assigned_adapter: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        created_by: str = "human",
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RoomTask:
        """Create a new task in the room, checking dependencies to set initial status."""
        room = self.storage.get_room(room_id)
        if not room:
            raise ValueError(f"Collaborative room '{room_id}' not found.")

        tid = task_id or f"rtask_{uuid.uuid4().hex[:10]}"
        prio_enum = RoomTaskPriority(priority) if isinstance(priority, str) else priority
        deps = list(dependencies or [])

        # Check if all dependencies are already met
        status = RoomTaskStatus.PENDING
        if deps:
            for dep_id in deps:
                dep_task_data = self.storage.get_room_task(room_id, dep_id)
                if not dep_task_data or dep_task_data.get("status") != "completed":
                    status = RoomTaskStatus.BLOCKED
                    break

        task = RoomTask(
            task_id=tid,
            room_id=room_id,
            title=title,
            description=description,
            status=status,
            priority=prio_enum,
            assigned_to=assigned_to,
            assigned_adapter=assigned_adapter,
            parent_task_id=parent_task_id,
            dependencies=deps,
            created_by=created_by,
            metadata=metadata or {},
        )

        self.storage.create_room_task(task.to_dict())
        return task

    def get_task(self, room_id: str, task_id: str) -> Optional[RoomTask]:
        """Fetch task by ID within a room."""
        data = self.storage.get_room_task(room_id, task_id)
        if not data:
            return None
        return RoomTask.from_dict(data)

    def list_tasks(
        self,
        room_id: str,
        status: Optional[Union[RoomTaskStatus, str]] = None,
        assigned_to: Optional[str] = None,
    ) -> List[RoomTask]:
        """List tasks in a room with optional filters."""
        status_str = status.value if isinstance(status, RoomTaskStatus) else status
        records = self.storage.list_room_tasks(
            room_id=room_id, status=status_str, assigned_to=assigned_to
        )
        return [RoomTask.from_dict(r) for r in records]

    def check_dependencies_met(self, room_id: str, task_id: str) -> bool:
        """Check if all dependencies for a task are COMPLETED."""
        task = self.get_task(room_id, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in room '{room_id}'.")
        if not task.dependencies:
            return True
        for dep_id in task.dependencies:
            dep_task = self.get_task(room_id, dep_id)
            if not dep_task or dep_task.status != RoomTaskStatus.COMPLETED:
                return False
        return True

    def claim_task(
        self,
        room_id: str,
        task_id: str,
        participant_id: str,
        adapter_type: Optional[str] = None,
    ) -> RoomTask:
        """Claim a task for execution by a human participant or agent adapter."""
        if self.governance:
            if not self.governance.can_perform(room_id, participant_id, "claim_tasks"):
                raise PermissionError(
                    f"Participant '{participant_id}' does not have 'claim_tasks' permission in room '{room_id}'."
                )

        task = self.get_task(room_id, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in room '{room_id}'.")

        if not self.check_dependencies_met(room_id, task_id):
            raise ValueError(f"Cannot claim task '{task_id}': dependencies are not yet completed.")

        if task.status not in (RoomTaskStatus.PENDING, RoomTaskStatus.BLOCKED):
            raise ValueError(
                f"Task '{task_id}' cannot be claimed; currently '{task.status.value}'."
            )

        updates: Dict[str, Any] = {
            "assigned_to": participant_id,
            "status": RoomTaskStatus.IN_PROGRESS.value,
        }
        if adapter_type:
            updates["assigned_adapter"] = adapter_type

        updated_data = self.storage.update_room_task(room_id, task_id, updates)
        if not updated_data:
            raise RuntimeError(f"Failed to claim task '{task_id}'.")

        return RoomTask.from_dict(updated_data)

    def update_task_status(
        self,
        room_id: str,
        task_id: str,
        status: Union[RoomTaskStatus, str],
        result: Optional[Dict[str, Any]] = None,
        updated_by: Optional[str] = None,
    ) -> RoomTask:
        """Update task status and unblock downstream dependent tasks when COMPLETED."""
        task = self.get_task(room_id, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in room '{room_id}'.")

        status_enum = RoomTaskStatus(status) if isinstance(status, str) else status
        updates: Dict[str, Any] = {"status": status_enum.value}
        if result is not None:
            updates["result"] = result

        updated_data = self.storage.update_room_task(room_id, task_id, updates)
        if not updated_data:
            raise RuntimeError(f"Failed to update task '{task_id}'.")

        # Unblock downstream tasks if this task is now completed
        if status_enum == RoomTaskStatus.COMPLETED:
            downstream = self.list_tasks(room_id=room_id)
            for d in downstream:
                if d.status == RoomTaskStatus.BLOCKED and task_id in d.dependencies:
                    if self.check_dependencies_met(room_id, d.task_id):
                        self.storage.update_room_task(
                            room_id, d.task_id, {"status": RoomTaskStatus.PENDING.value}
                        )

        return RoomTask.from_dict(updated_data)

    async def dispatch_task_to_adapter(
        self,
        room_id: str,
        task_id: str,
        adapter: Any,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch a task to an AgentAdapter, updating progress and saving completion result."""
        task = self.get_task(room_id, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found in room '{room_id}'.")

        # Claim the task for the adapter
        adapter_id = getattr(adapter, "adapter_id", getattr(adapter, "name", "agent"))
        adapter_name = getattr(adapter, "name", adapter_id)
        candidate_id = adapter_id
        if self.governance:
            if not self.governance.get_participant(
                room_id, candidate_id
            ) and self.governance.get_participant(room_id, adapter_name):
                candidate_id = adapter_name

        self.claim_task(room_id, task_id, participant_id=candidate_id, adapter_type=adapter_id)
        task_prompt = prompt or (
            f"Please execute workflow step: {task.title}\n"
            f"Details: {task.description or 'No additional details provided.'}"
        )

        try:
            # Check adapter execute or chat interface
            if hasattr(adapter, "execute"):
                from core.adapters.base import AdapterExecutionRequest

                req = AdapterExecutionRequest(prompt=task_prompt)
                if inspect.iscoroutinefunction(adapter.execute):
                    exec_res = await adapter.execute(req)
                else:
                    exec_res = adapter.execute(req)
                res_dict = (
                    exec_res.to_dict()
                    if hasattr(exec_res, "to_dict")
                    else {"content": getattr(exec_res, "content", str(exec_res))}
                )
            elif hasattr(adapter, "chat"):
                if inspect.iscoroutinefunction(adapter.chat):
                    res_raw = await adapter.chat(task_prompt)
                else:
                    res_raw = adapter.chat(task_prompt)
                res_dict = (
                    res_raw
                    if isinstance(res_raw, dict)
                    else {"content": getattr(res_raw, "content", str(res_raw))}
                )
            else:
                res_dict = {"content": f"Task '{task.title}' executed successfully."}

            self.update_task_status(
                room_id=room_id,
                task_id=task_id,
                status=RoomTaskStatus.COMPLETED,
                result=res_dict,
                updated_by=adapter_name,
            )
            return res_dict

        except Exception as e:
            err_dict = {"error": str(e), "failed_at": datetime.now(timezone.utc).isoformat()}
            self.update_task_status(
                room_id=room_id,
                task_id=task_id,
                status=RoomTaskStatus.FAILED,
                result=err_dict,
                updated_by=adapter_name,
            )
            raise
