"""services/python/server/routers/writing.py

API router for Writing Pack MVP (Task R5.2).
Provides endpoints for multi-stage article creation:
notes -> outline -> draft -> style review -> revised draft -> claim review -> finalized document.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.writing.models import ArticleWorkflowState
from services.python.server.container import get_writing_workflow_service

logger = logging.getLogger("agent_engine.api.writing")
router = APIRouter(prefix="/writing", tags=["writing"])


class CreateWorkflowRequest(BaseModel):
    project_id: str
    title: str
    source_notes: str
    audience: Optional[str] = "General technical / professional"
    objective: Optional[str] = None
    desired_length: Optional[str] = "Medium (~1,000-1,500 words)"
    style_guidance: Optional[str] = None
    factuality_requirement: str = "strict"


class GenerateOutlineRequest(BaseModel):
    title: Optional[str] = None
    source_notes: Optional[str] = None
    audience: Optional[str] = None
    objective: Optional[str] = None
    style_guidance: Optional[str] = None


class GenerateDraftRequest(BaseModel):
    target_word_count: Optional[int] = None


class ReviseDraftRequest(BaseModel):
    accepted_findings_only: bool = True


class FinalizeArticleRequest(BaseModel):
    final_content: Optional[str] = None


class ManualEditRequest(BaseModel):
    stage: str = Field(..., description="Stage to edit: outline, draft, revised_draft, final")
    content: str = Field(..., description="Updated text or markdown content")


@router.post("/workflows", response_model=Dict[str, Any])
async def create_writing_workflow_endpoint(req: CreateWorkflowRequest) -> Dict[str, Any]:
    """Create a new article workflow instance."""
    service = get_writing_workflow_service()
    state = ArticleWorkflowState(
        project_id=req.project_id,
        title=req.title,
        source_notes=req.source_notes,
        audience=req.audience,
        objective=req.objective,
        desired_length=req.desired_length,
        style_guidance=req.style_guidance,
        factuality_requirement=req.factuality_requirement,
    )
    created = service.create_workflow(state)
    return created.model_dump()


@router.get("/workflows", response_model=List[Dict[str, Any]])
async def list_writing_workflows_endpoint(
    project_id: Optional[str] = Query(None, description="Optional project filter"),
) -> List[Dict[str, Any]]:
    """List active writing workflows."""
    service = get_writing_workflow_service()
    states = service.list_workflows(project_id=project_id)
    return [s.model_dump() for s in states]


@router.get("/workflows/{workflow_run_id}", response_model=Dict[str, Any])
async def get_writing_workflow_endpoint(workflow_run_id: str) -> Dict[str, Any]:
    """Retrieve full state for a specific writing workflow."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )
    return state.model_dump()


@router.post("/workflows/{workflow_run_id}/outline", response_model=Dict[str, Any])
async def generate_outline_endpoint(
    workflow_run_id: str, req: Optional[GenerateOutlineRequest] = None
) -> Dict[str, Any]:
    """Generate or regenerate structured outline from source notes."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.generate_outline(
        state,
        title=req.title if req else None,
        source_notes=req.source_notes if req else None,
        audience=req.audience if req else None,
        objective=req.objective if req else None,
        style_guidance=req.style_guidance if req else None,
    )
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/draft", response_model=Dict[str, Any])
async def generate_draft_endpoint(
    workflow_run_id: str, req: Optional[GenerateDraftRequest] = None
) -> Dict[str, Any]:
    """Generate prose draft from approved outline."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.generate_draft(
        state, target_word_count=req.target_word_count if req else None
    )
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/style-review", response_model=Dict[str, Any])
async def review_style_endpoint(workflow_run_id: str) -> Dict[str, Any]:
    """Audit draft for clarity, structure, repetition, tone, phrasing, and verbosity."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.review_style(state)
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/revise", response_model=Dict[str, Any])
async def revise_draft_endpoint(
    workflow_run_id: str, req: Optional[ReviseDraftRequest] = None
) -> Dict[str, Any]:
    """Incorporate accepted style findings into a revised draft."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.revise_draft(
        state,
        accepted_findings_only=req.accepted_findings_only if req else True,
    )
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/claim-review", response_model=Dict[str, Any])
async def review_claims_endpoint(workflow_run_id: str) -> Dict[str, Any]:
    """Audit material assertions against source notes and classify support."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.review_claims(state)
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/finalize", response_model=Dict[str, Any])
async def finalize_article_endpoint(
    workflow_run_id: str, req: Optional[FinalizeArticleRequest] = None
) -> Dict[str, Any]:
    """Create final canonical document artifact and mark workflow finalized."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = await service.finalize_article(
        state, final_content=req.final_content if req else None
    )
    if updated.error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=updated.error)
    return updated.model_dump()


@router.post("/workflows/{workflow_run_id}/edit", response_model=Dict[str, Any])
async def apply_manual_edit_endpoint(
    workflow_run_id: str, req: ManualEditRequest
) -> Dict[str, Any]:
    """Incorporate manual human edits into a specific stage."""
    service = get_writing_workflow_service()
    state = service.get_workflow(workflow_run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Writing workflow '{workflow_run_id}' not found.",
        )

    updated = service.apply_manual_edit(workflow_run_id, req.stage, req.content)
    return updated.model_dump()


@router.post("/workflows/full", response_model=Dict[str, Any])
async def run_full_writing_workflow_endpoint(req: CreateWorkflowRequest) -> Dict[str, Any]:
    """Execute end-to-end writing pipeline from notes to final document artifact."""
    service = get_writing_workflow_service()
    state = ArticleWorkflowState(
        project_id=req.project_id,
        title=req.title,
        source_notes=req.source_notes,
        audience=req.audience,
        objective=req.objective,
        desired_length=req.desired_length,
        style_guidance=req.style_guidance,
        factuality_requirement=req.factuality_requirement,
    )
    completed = await service.run_full_workflow(state)
    return completed.model_dump()
