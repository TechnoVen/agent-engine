"""services/python/server/routers/privacy.py

Privacy and Data-Routing Policy API router for Agent Engine Sidecar Server.
Part of Milestone R3 Task R3.8 (Privacy classes and data-routing policy).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.privacy import (
    ApprovedCloudTarget,
    DataRoutingClass,
    DataRoutingPolicy,
    EffectiveRoutingPolicy,
    PrivacyPolicyEngine,
    get_system_routing_policy,
    set_system_routing_policy,
)
from services.python.server.container import get_storage_backend
from services.python.server.dependencies import verify_ipc_token

logger = logging.getLogger("agent_engine.api.privacy")
router = APIRouter(tags=["privacy"])


class ApprovedCloudTargetSchema(BaseModel):
    provider_id: str
    model_id: Optional[str] = None


class DataRoutingPolicyRequest(BaseModel):
    routing_class: DataRoutingClass
    approved_cloud_targets: List[ApprovedCloudTargetSchema] = Field(default_factory=list)
    allow_relaxation_by_task: bool = False
    allow_project_relaxation: bool = False


class ProjectPrivacyPolicyRequest(BaseModel):
    routing_class: DataRoutingClass
    approved_cloud_targets: List[ApprovedCloudTargetSchema] = Field(default_factory=list)
    allow_relaxation_by_task: bool = False


class EffectivePolicySummary(BaseModel):
    effective_class: str
    source: str
    approved_targets: List[Dict[str, Optional[str]]]
    relaxation_attempted: bool
    relaxation_denied: bool
    audit_reason: Optional[str] = None


class SystemPrivacyPolicyResponse(BaseModel):
    policy: Dict[str, Any]
    effective: EffectivePolicySummary


class ProjectPrivacyPolicyResponse(BaseModel):
    project_id: str
    project_policy: Optional[Dict[str, Any]] = None
    effective: EffectivePolicySummary


def _serialize_effective(effective: EffectiveRoutingPolicy) -> EffectivePolicySummary:
    return EffectivePolicySummary(
        effective_class=effective.effective_class.value,
        source=effective.source.value,
        approved_targets=[
            {"provider_id": t.provider_id, "model_id": t.model_id}
            for t in effective.approved_targets
        ],
        relaxation_attempted=effective.relaxation_attempted,
        relaxation_denied=effective.relaxation_denied,
        audit_reason=effective.audit_reason,
    )


@router.get("/privacy/policy", response_model=SystemPrivacyPolicyResponse)
async def get_system_privacy_policy():
    """Retrieve the current system/profile data routing policy and its effective state."""
    policy = get_system_routing_policy()
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=policy,
        is_trusted_authority=True,
    )
    return SystemPrivacyPolicyResponse(
        policy=policy.model_dump(),
        effective=_serialize_effective(effective),
    )


@router.put("/privacy/policy", response_model=SystemPrivacyPolicyResponse)
async def update_system_privacy_policy(
    req: DataRoutingPolicyRequest,
    request: Request,
):
    """Update the system/profile data routing policy.

    Protected by local IPC token authentication (verify_ipc_token).
    """
    verify_ipc_token(request)
    try:
        targets = [
            ApprovedCloudTarget(provider_id=t.provider_id, model_id=t.model_id)
            for t in req.approved_cloud_targets
        ]
        new_policy = DataRoutingPolicy(
            routing_class=req.routing_class,
            approved_cloud_targets=targets,
            allow_relaxation_by_task=req.allow_relaxation_by_task,
            allow_project_relaxation=req.allow_project_relaxation,
        )
        set_system_routing_policy(new_policy)
        effective = PrivacyPolicyEngine.resolve_effective_policy(
            profile_policy=new_policy,
            is_trusted_authority=True,
        )
        return SystemPrivacyPolicyResponse(
            policy=new_policy.model_dump(),
            effective=_serialize_effective(effective),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid privacy policy configuration: {e}",
        )


@router.get("/projects/{project_id}/privacy", response_model=ProjectPrivacyPolicyResponse)
async def get_project_privacy_policy(project_id: str):
    """Retrieve effective data routing policy for a canonical project."""
    backend = get_storage_backend()
    proj = backend.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    settings = proj.get("settings") or {}
    pol_data = settings.get("data_routing_policy") if isinstance(settings, dict) else None
    project_policy = DataRoutingPolicy.model_validate(pol_data) if pol_data else None

    profile_policy = get_system_routing_policy()
    effective = PrivacyPolicyEngine.resolve_effective_policy(
        profile_policy=profile_policy,
        project_policy=project_policy,
        is_trusted_authority=True,
    )

    return ProjectPrivacyPolicyResponse(
        project_id=project_id,
        project_policy=project_policy.model_dump() if project_policy else None,
        effective=_serialize_effective(effective),
    )


@router.put("/projects/{project_id}/privacy", response_model=ProjectPrivacyPolicyResponse)
async def update_project_privacy_policy(
    project_id: str,
    req: ProjectPrivacyPolicyRequest,
    request: Request,
):
    """Update data routing policy for a specific canonical project.

    Protected by local IPC token authentication (verify_ipc_token).
    """
    verify_ipc_token(request)
    backend = get_storage_backend()
    proj = backend.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    try:
        targets = [
            ApprovedCloudTarget(provider_id=t.provider_id, model_id=t.model_id)
            for t in req.approved_cloud_targets
        ]
        new_project_policy = DataRoutingPolicy(
            routing_class=req.routing_class,
            approved_cloud_targets=targets,
            allow_relaxation_by_task=req.allow_relaxation_by_task,
            allow_project_relaxation=False,
        )

        settings = dict(proj.get("settings") or {})
        settings["data_routing_policy"] = new_project_policy.model_dump()
        backend.update_project(project_id, {"settings": settings})

        profile_policy = get_system_routing_policy()
        effective = PrivacyPolicyEngine.resolve_effective_policy(
            profile_policy=profile_policy,
            project_policy=new_project_policy,
            is_trusted_authority=True,
        )

        return ProjectPrivacyPolicyResponse(
            project_id=project_id,
            project_policy=new_project_policy.model_dump(),
            effective=_serialize_effective(effective),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid privacy policy configuration: {e}",
        )
