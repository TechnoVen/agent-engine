"""Canonical Project Domain Models (Task R1.6).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md, docs/ROADMAP.md
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from core.privacy.models import DataRoutingPolicy


def generate_project_id() -> str:
    return f"proj_{uuid.uuid4().hex[:12]}"


def current_timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectSettings(BaseModel):
    """Configuration settings scoped to a project."""

    model_preference: Optional[str] = None
    routing_tier: Optional[str] = None
    budget_ceiling_usd: float = 100.0
    isolation_mode: str = "standard"  # "standard", "worktree", "read_only"
    custom_rules: Dict[str, Any] = Field(default_factory=dict)
    data_routing_policy: Optional[DataRoutingPolicy] = None
    routing_objective: Optional[str] = "balanced"


class Project(BaseModel):
    """Canonical Project representation representing an isolated workspace boundary."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=generate_project_id)
    name: str
    description: Optional[str] = None
    root_path: str
    instructions: str = ""
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    is_default: bool = False
    created_at: str = Field(default_factory=current_timestamp_iso)
    updated_at: str = Field(default_factory=current_timestamp_iso)
