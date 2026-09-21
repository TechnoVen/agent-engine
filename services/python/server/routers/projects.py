"""services/python/server/routers/projects.py

Projects API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

# Core domain imports
from core.context import ContextSpec, MissingContextFieldError, build_context
from core.projects import (
    Project,
    ProjectSettings,
    generate_project_id,
)
from core.session import (
    AgentParticipant,
    ToolCall,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_session_store,
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.projects")
router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=List[Dict[str, Any]])
async def list_projects(
    limit: int = Query(50, ge=1, le=200, description="Max projects to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List canonical projects with pagination."""
    backend = get_storage_backend()
    return backend.list_projects(limit=limit, offset=offset)


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(req: CreateProjectRequest):
    """Create a new canonical project workspace."""
    backend = get_storage_backend()
    proj_id = generate_project_id()
    root_path = req.root_path or f"/workspace/{proj_id}"
    proj = Project(
        id=proj_id,
        name=req.name,
        description=req.description,
        root_path=root_path,
        instructions=req.instructions or "",
        settings=req.settings or ProjectSettings(),
    )
    created = backend.create_project(proj.model_dump())
    return created


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Fetch details for a specific canonical project."""
    backend = get_storage_backend()
    proj = backend.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return proj


@router.put("/projects/{project_id}")
@router.patch("/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    """Update canonical project attributes."""
    backend = get_storage_backend()
    existing = backend.get_project(project_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    updates = req.model_dump(exclude_unset=True)
    updated = backend.update_project(project_id, updates)
    return updated


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a canonical project."""
    backend = get_storage_backend()
    deleted = backend.delete_project(project_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return {"deleted": True, "project_id": project_id}


@router.post("/sessions", response_model=UnifiedSessionInfo, status_code=status.HTTP_201_CREATED)
async def create_unified_session(req: CreateSessionRequest):
    """Create a new unified cross-agent session."""
    store = get_session_store()
    parts = (
        [AgentParticipant(**p.model_dump()) for p in req.participants] if req.participants else None
    )
    session = store.create_session(
        session_id=req.session_id,
        title=req.title,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        channel=req.channel,
        status=req.status,
        metadata=req.metadata,
        participants=parts,
    )
    return UnifiedSessionInfo(**session.to_dict())


@router.get("/sessions", response_model=List[UnifiedSessionInfo])
async def list_unified_sessions(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status (active, archived, closed)"
    ),
    query: Optional[str] = Query(None, description="Keyword search query"),
    limit: int = Query(50, ge=1, le=200, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List cross-agent sessions with optional filters."""
    store = get_session_store()
    sessions = store.list_sessions(
        user_id=user_id,
        tenant_id=tenant_id,
        channel=channel,
        status=status_filter,
        query=query,
        limit=limit,
        offset=offset,
    )
    return [UnifiedSessionInfo(**s.to_dict()) for s in sessions]


@router.get("/sessions/search", response_model=List[SessionSearchResult])
async def search_unified_sessions(
    q: str = Query(..., min_length=1, description="Keyword to search across sessions and messages"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
):
    """Search messages and metadata across all sessions."""
    store = get_session_store()
    results = store.search_sessions(query=q, user_id=user_id, limit=limit)
    return [SessionSearchResult(**r) for r in results]


@router.get("/sessions/{session_id}", response_model=UnifiedSessionInfo)
async def get_unified_session(session_id: str):
    """Retrieve details and full message history of a unified session."""
    store = get_session_store()
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return UnifiedSessionInfo(**session.to_dict())


@router.patch("/sessions/{session_id}", response_model=UnifiedSessionInfo)
async def update_unified_session(session_id: str, req: UpdateSessionRequest):
    """Update title, status, summary, or metadata of a session."""
    store = get_session_store()
    session = store.update_session(
        session_id=session_id,
        title=req.title,
        status=req.status,
        summary=req.summary,
        metadata=req.metadata,
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return UnifiedSessionInfo(**session.to_dict())


@router.delete("/sessions/{session_id}")
async def delete_unified_session(session_id: str):
    """Permanently delete a session."""
    store = get_session_store()
    success = store.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"status": "deleted", "session_id": session_id}


@router.post(
    "/sessions/{session_id}/messages",
    response_model=UnifiedMessageInfo,
    status_code=status.HTTP_201_CREATED,
)
async def append_unified_message(session_id: str, req: AppendMessageRequest):
    """Append a message turn to a session."""
    store = get_session_store()
    tcs = [ToolCall(**tc.model_dump()) for tc in req.tool_calls] if req.tool_calls else None
    try:
        msg = store.append_message(
            session_id=session_id,
            role=req.role,
            content=req.content,
            sender_id=req.sender_id or "user",
            sender_name=req.sender_name,
            agent_id=req.agent_id,
            model=req.model,
            tokens=req.tokens,
            cost_usd=req.cost_usd,
            tool_calls=tcs,
            metadata=req.metadata,
        )
        return UnifiedMessageInfo(**msg.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/sessions/{session_id}/fork",
    response_model=UnifiedSessionInfo,
    status_code=status.HTTP_201_CREATED,
)
async def fork_unified_session(session_id: str, req: ForkSessionRequest):
    """Fork an existing session at a specific message point (or latest) into a new branch."""
    store = get_session_store()
    try:
        forked = store.fork_session(
            session_id=session_id,
            fork_point_message_id=req.fork_point_message_id,
            new_title=req.new_title,
            user_id=req.user_id,
            new_session_id=req.new_session_id,
        )
        return UnifiedSessionInfo(**forked.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sessions/{session_id}/export", response_model=SessionExportResponse)
async def export_unified_session(
    session_id: str,
    format: str = Query(
        "json", description="Export format: json, markdown, jsonl, openai, anthropic, dspy"
    ),
):
    """Export a session transcript into standard ecosystem formats."""
    store = get_session_store()
    try:
        content = store.export_session(session_id=session_id, format=format)
        return SessionExportResponse(session_id=session_id, format=format, content=content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/sessions/import", response_model=UnifiedSessionInfo, status_code=status.HTTP_201_CREATED
)
async def import_unified_session(req: SessionImportRequest):
    """Import a session from an external payload."""
    store = get_session_store()
    try:
        session = store.import_session(payload=req.payload, format=req.format)
        return UnifiedSessionInfo(**session.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


@router.post("/context/build", response_model=ContextBuildResponse)
async def build_context_endpoint(req: ContextBuildRequest):
    """Build a minimal, budgeted context according to declared specifications and token limits."""
    try:
        spec = ContextSpec(
            required_fields=req.required_fields,
            optional_fields=req.optional_fields or [],
            max_tokens=req.max_tokens if req.max_tokens is not None else 4000,
            hard_ceiling_tokens=req.hard_ceiling_tokens
            if req.hard_ceiling_tokens is not None
            else 32000,
            allow_retrieval=req.allow_retrieval or False,
            retrieval_budget_tokens=req.retrieval_budget_tokens
            if req.retrieval_budget_tokens is not None
            else 2000,
            truncation_strategy=req.truncation_strategy or "priority",
            field_priorities=req.field_priorities or {},
            system_prompt=req.system_prompt,
            strict_required=req.strict_required if req.strict_required is not None else True,
        )
        built = build_context(spec=spec, available=req.available_data)
        return ContextBuildResponse(**built.to_dict())
    except MissingContextFieldError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Context build failed: {str(e)}",
        )
