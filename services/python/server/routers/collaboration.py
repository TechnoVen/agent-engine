"""services/python/server/routers/collaboration.py

Collaboration API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

# Core domain imports
from core.rooms import (
    RoomGovernance,
    RoomProjectMapper,
    RoomTaskManager,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.collaboration")
router = APIRouter(tags=["collaboration"])


@router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(req: CreateRoomRequest):
    """Create a new collaborative room overlay on a project."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    room = mapper.create_room(
        project_id=req.project_id,
        name=req.name,
        description=req.description,
        topic=req.topic,
        policy_id=req.policy_id,
        active_adapters=req.active_adapters,
        metadata=req.metadata,
    )
    return room.to_dict()


@router.get("/rooms")
async def list_rooms(
    project_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """List collaborative rooms, optionally filtered by project or status."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    rooms = mapper.list_rooms(project_id=project_id, status=status_filter)
    return [r.to_dict() for r in rooms]


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    """Fetch details for a specific collaborative room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    room = mapper.get_room(room_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return room.to_dict()


@router.patch("/rooms/{room_id}")
async def update_room(room_id: str, req: UpdateRoomRequest):
    """Update room attributes."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    updates = req.model_dump(exclude_unset=True)
    updated = mapper.update_room(room_id, **updates)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return updated.to_dict()


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str):
    """Delete a collaborative room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    deleted = mapper.delete_room(room_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return {"deleted": True, "room_id": room_id}


@router.get("/rooms/{room_id}/context")
async def get_room_context(
    room_id: str,
    prompt: str = Query(""),
    project_instructions: str = Query(""),
):
    """Build ADR-014 dynamic context overlay for the room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    try:
        context = mapper.build_room_context(
            room_id=room_id,
            prompt=prompt,
            project_instructions=project_instructions,
        )
        return context
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/rooms/{room_id}/participants", status_code=status.HTTP_201_CREATED)
async def add_room_participant(room_id: str, req: AddRoomParticipantRequest):
    """Add or register a participant (human or agent) in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    try:
        participant = gov.add_participant(
            room_id=room_id,
            participant_id=req.participant_id,
            name=req.name,
            role=req.role,
            participant_type=req.participant_type,
            adapter_type=req.adapter_type,
            permissions=req.permissions,
            metadata=req.metadata,
        )
        return participant.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/rooms/{room_id}/participants")
async def list_room_participants(room_id: str):
    """List all participants registered in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    participants = gov.list_participants(room_id)
    return [p.to_dict() for p in participants]


@router.delete("/rooms/{room_id}/participants/{participant_id}")
async def remove_room_participant(
    room_id: str,
    participant_id: str,
    requested_by: Optional[str] = Query(None),
):
    """Remove a participant from the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    req_by = requested_by or participant_id
    try:
        removed = gov.remove_participant(
            room_id=room_id,
            participant_id=participant_id,
            requested_by_id=req_by,
        )
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Participant '{participant_id}' not found in room '{room_id}'",
            )
        return {"removed": True, "participant_id": participant_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/rooms/{room_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_room_task(room_id: str, req: CreateRoomTaskRequest):
    """Create a task object as a workflow step in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.create_task(
            room_id=room_id,
            title=req.title,
            description=req.description,
            priority=req.priority,
            assigned_to=req.assigned_to,
            assigned_adapter=req.assigned_adapter,
            parent_task_id=req.parent_task_id,
            dependencies=req.dependencies,
            created_by=req.created_by,
            metadata=req.metadata,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/rooms/{room_id}/tasks")
async def list_room_tasks(
    room_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    assigned_to: Optional[str] = Query(None),
):
    """List tasks in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    tasks = task_mgr.list_tasks(room_id=room_id, status=status_filter, assigned_to=assigned_to)
    return [t.to_dict() for t in tasks]


@router.get("/rooms/{room_id}/tasks/{task_id}")
async def get_room_task(room_id: str, task_id: str):
    """Fetch details for a task in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    task = task_mgr.get_task(room_id, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found in room '{room_id}'",
        )
    return task.to_dict()


@router.post("/rooms/{room_id}/tasks/{task_id}/claim")
async def claim_room_task(room_id: str, task_id: str, req: ClaimRoomTaskRequest):
    """Claim a task for execution."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.claim_task(
            room_id=room_id,
            task_id=task_id,
            participant_id=req.participant_id,
            adapter_type=req.adapter_type,
        )
        return task.to_dict()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/rooms/{room_id}/tasks/{task_id}")
async def update_room_task(room_id: str, task_id: str, req: UpdateRoomTaskRequest):
    """Update task status or completion result."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.update_task_status(
            room_id=room_id,
            task_id=task_id,
            status=req.status or "completed",
            result=req.result,
            updated_by=req.updated_by,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
