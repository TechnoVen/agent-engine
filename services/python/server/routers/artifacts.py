"""services/python/server/routers/artifacts.py

Artifacts API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

# Generated domain router
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response

# Core domain imports
from core.artifacts import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactSecurityError,
    ArtifactService,
)
from core.execution import (
    ExecutionCoordinator,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_artifact_service,
    get_execution_coordinator,
    get_storage_backend,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.artifacts")
router = APIRouter(tags=["artifacts"])


@router.get("/executions/{execution_id}/artifacts")
async def list_execution_artifacts_endpoint(
    execution_id: str,
    project_id: Optional[str] = Query(None),
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    include_deleted: bool = Query(
        False, description="Whether to include deleted artifact tombstones"
    ),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """List artifacts associated with an execution with project-scope integrity verification.

    NOTE: X-Project-ID / query project_id enforces project-scope integrity to prevent
    accidental cross-project leakage in R1. TODO(R2): Replace with authenticated actor RBAC authorization.
    """
    effective_project_id = project_id or x_project_id
    record = coordinator.get_execution(execution_id)
    if not record:
        active_exec = coordinator._active_executions.get(execution_id)
        if active_exec:
            record = active_exec.model_dump()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    exec_project_id = (
        record.get("project_id")
        if isinstance(record, dict)
        else getattr(record, "project_id", None)
    )
    if effective_project_id and exec_project_id and exec_project_id != effective_project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Execution '{execution_id}' belongs to project '{exec_project_id}'",
        )

    artifacts = artifact_service.list_artifacts_by_execution(
        execution_id, project_id=effective_project_id, include_deleted=include_deleted
    )
    return JSONResponse(content=[a.to_dict() for a in artifacts])


@router.get("/projects/{project_id}/artifacts")
async def list_project_artifacts_endpoint(
    project_id: str,
    include_deleted: bool = Query(
        False, description="Whether to include deleted artifact tombstones"
    ),
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """List all artifacts belonging to a project with project ownership validation."""
    backend = get_storage_backend()
    if hasattr(backend, "get_project") and not backend.get_project(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    try:
        artifacts = artifact_service.list_artifacts_by_project(
            project_id, include_deleted=include_deleted
        )
        return JSONResponse(content=[a.to_dict() for a in artifacts])
    except ArtifactSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/artifacts/{artifact_id}")
async def get_artifact_endpoint(
    artifact_id: str,
    project_id: Optional[str] = Query(None),
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get artifact metadata with project-scope integrity verification."""
    effective_project_id = project_id or x_project_id
    try:
        artifact = artifact_service.get_artifact(artifact_id, project_id=effective_project_id)
        if not artifact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact '{artifact_id}' not found",
            )
        return JSONResponse(content=artifact.to_dict())
    except ArtifactSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content_endpoint(
    artifact_id: str,
    project_id: Optional[str] = Query(None),
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Download artifact content bytes with cryptographic SHA-256 integrity verification."""
    effective_project_id = project_id or x_project_id
    try:
        artifact = artifact_service.get_artifact(artifact_id, project_id=effective_project_id)
        if not artifact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact '{artifact_id}' not found",
            )
        payload = artifact_service.get_artifact_payload(
            artifact_id, project_id=effective_project_id
        )
        # Sanitize filename against CRLF / header injection attacks
        sanitized_filename = re.sub(r'[\r\n";\\]', "_", artifact.name)
        headers = {
            "Content-Disposition": f'attachment; filename="{sanitized_filename}"',
            "ETag": f'"{artifact.sha256_hash}"',
            "Content-Length": str(len(payload)),
        }
        return Response(content=payload, media_type=artifact.mime_type, headers=headers)
    except ArtifactSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ArtifactNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ArtifactIntegrityError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact_endpoint(
    artifact_id: str,
    project_id: Optional[str] = Query(None),
    x_project_id: Optional[str] = Header(None, alias="X-Project-ID"),
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Delete an artifact (marks tombstone in metadata and removes physical payload)."""
    effective_project_id = project_id or x_project_id
    try:
        artifact = artifact_service.get_artifact(artifact_id, project_id=effective_project_id)
        if not artifact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact '{artifact_id}' not found",
            )
        deleted = artifact_service.delete_artifact(artifact_id, project_id=effective_project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact '{artifact_id}' not found",
            )
        return JSONResponse(content={"success": True, "artifact_id": artifact_id})
    except ArtifactSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
