"""services/python/server/routers/workflows.py

Workflows API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

# Core domain imports
from core.workflows import (
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowGateManager,
    WorkflowParser,
    WorkflowStatus,
)

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    get_workflow_storage,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.workflows")
router = APIRouter(tags=["workflows"])


@router.get("/workflows", response_model=List[WorkflowInfo])
async def list_workflows_endpoint(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
):
    """List registered graph workflows."""
    storage = get_workflow_storage()
    st = None
    if status:
        try:
            st = WorkflowStatus(status)
        except Exception:
            st = None
    wfs = storage.list_workflows(status=st, tag=tag)
    return [
        WorkflowInfo(
            id=w.id,
            name=w.name,
            description=w.description,
            steps=[n.id for n in w.nodes] or w.steps,
            version=w.version,
            status=w.status.value,
            nodes=[n.model_dump() for n in w.nodes],
            edges=[e.model_dump() for e in w.edges],
            tags=w.tags,
            metadata=w.metadata,
        )
        for w in wfs
    ]


@router.post("/workflows")
async def create_or_run_workflow(req: Dict[str, Any]):
    """Create a new workflow definition, or run a workflow if legacy workflow_id payload passed."""
    if "workflow_id" in req and "nodes" not in req:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={
                "error_code": "RUNTIME_NOT_AVAILABLE",
                "status": "deferred",
                "target_milestone": "R4",
                "message": "Workflow runtime execution is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Workflow authoring, validation, and storage are supported in R1.",
                "detail": "Workflow runtime execution is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Workflow authoring, validation, and storage are supported in R1.",
            },
        )

    try:
        wf = WorkflowDefinition.model_validate(req)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {e}",
        )

    is_valid, errors = WorkflowParser.validate(wf)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {'; '.join(errors)}",
        )

    storage = get_workflow_storage()
    saved = storage.save_workflow(wf)
    return saved.to_dict()


@router.post("/workflows/validate", response_model=WorkflowValidateResponse)
async def validate_workflow_endpoint(req: WorkflowValidateRequest):
    """Validate a YAML or JSON workflow definition without saving."""
    wf = None
    if req.definition_yaml:
        try:
            wf = WorkflowParser.parse_yaml(req.definition_yaml)
        except Exception as e:
            return WorkflowValidateResponse(valid=False, errors=[str(e)])
    elif req.definition_json:
        try:
            wf = WorkflowDefinition.model_validate(req.definition_json)
        except Exception as e:
            return WorkflowValidateResponse(valid=False, errors=[str(e)])
    else:
        return WorkflowValidateResponse(
            valid=False, errors=["Either definition_yaml or definition_json must be provided"]
        )

    is_valid, errors = WorkflowParser.validate(wf)
    return WorkflowValidateResponse(
        valid=is_valid,
        errors=errors,
        node_count=len(wf.nodes),
        edge_count=len(wf.edges),
    )


@router.get("/workflows/gates/pending")
async def list_pending_workflow_gates_endpoint():
    """List all active workflow runs waiting for human gate review."""
    storage = get_workflow_storage()
    gate_mgr = WorkflowGateManager(storage=storage)
    return gate_mgr.list_pending_gates()


@router.get("/workflows/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str):
    """Fetch workflow definition by ID."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return wf.to_dict()


@router.put("/workflows/{workflow_id}")
async def update_workflow_endpoint(workflow_id: str, req: Dict[str, Any]):
    """Update an existing workflow definition."""
    req["id"] = workflow_id
    try:
        wf = WorkflowDefinition.model_validate(req)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {e}",
        )

    is_valid, errors = WorkflowParser.validate(wf)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {'; '.join(errors)}",
        )

    storage = get_workflow_storage()
    saved = storage.save_workflow(wf)
    return saved.to_dict()


@router.delete("/workflows/{workflow_id}")
async def delete_workflow_endpoint(workflow_id: str):
    """Delete a workflow and all associated runs."""
    storage = get_workflow_storage()
    deleted = storage.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return {"deleted": True, "id": workflow_id}


@router.post("/workflows/{workflow_id}/dry-run")
async def dry_run_workflow_endpoint(
    workflow_id: str,
    req: Optional[WorkflowDryRunRequest] = None,
):
    """Simulate workflow execution DAG traversal without executing heavy external models."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )

    engine = WorkflowEngine(storage=storage)
    inputs = req.inputs if req else {}
    run = engine.run(wf, inputs=inputs, dry_run=True)
    return run.to_dict()


@router.post("/workflows/{workflow_id}/run")
async def run_workflow_endpoint(
    workflow_id: str,
    request: Request,
    req: Optional[WorkflowRunRequest] = None,
    canonical: bool = Query(default=False),
):
    """Execute a workflow instance. Dispatches to canonical WorkflowService if canonical=True or X-Canonical-Runtime header is set."""
    is_canonical = canonical or (
        request.headers.get("x-canonical-runtime", "").lower() in ("true", "1")
    )
    if is_canonical:
        from services.python.server.container import get_workflow_service

        wf_service = get_workflow_service()
        inputs = req.inputs if req else {}
        try:
            run = wf_service.start_run(workflow_id=workflow_id, inputs=inputs)
            return run.to_dict()
        except Exception:
            storage = get_workflow_storage()
            wf = storage.get_workflow(workflow_id)
            if not wf:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Workflow '{workflow_id}' not found",
                )
            try:
                wf_service.create_definition(wf)
                run = wf_service.start_run(workflow_id=workflow_id, inputs=inputs)
                return run.to_dict()
            except Exception as inner_err:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to start canonical workflow run: {inner_err}",
                )

    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )

    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": f"Workflow runtime execution for '{workflow_id}' is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Workflow authoring, validation, and storage are supported in R1.",
            "detail": f"Workflow runtime execution for '{workflow_id}' is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Workflow authoring, validation, and storage are supported in R1.",
        },
    )


@router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs_endpoint(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    """List execution runs for a workflow."""
    storage = get_workflow_storage()
    runs = storage.list_runs(workflow_id=workflow_id, limit=limit)
    return [r.to_dict() for r in runs]


@router.get("/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run_endpoint(workflow_id: str, run_id: str):
    """Get details and step results of a workflow run."""
    storage = get_workflow_storage()
    run = storage.get_run(run_id)
    if not run or run.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found for workflow '{workflow_id}'",
        )
    return run.to_dict()


@router.post("/workflows/{workflow_id}/runs/{run_id}/approve")
async def approve_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: Optional[WorkflowGateDecisionRequest] = None,
):
    """Approve a paused human review gate and resume DAG execution."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
            "detail": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
        },
    )


@router.post("/workflows/{workflow_id}/runs/{run_id}/reject")
async def reject_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: Optional[WorkflowGateDecisionRequest] = None,
):
    """Reject a paused human review gate and route to rejection path or cancel."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
            "detail": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
        },
    )


@router.post("/workflows/{workflow_id}/runs/{run_id}/redirect")
async def redirect_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: WorkflowRedirectRequest,
):
    """Redirect execution of a paused human review gate to an alternate target node."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error_code": "RUNTIME_NOT_AVAILABLE",
            "status": "deferred",
            "target_milestone": "R4",
            "message": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
            "detail": "Workflow gate execution resumption is deferred to Milestone R4 (Multi-Agent & Long-Horizon Workflows). Gate review metadata and pending gate listing are supported in R1.",
        },
    )
