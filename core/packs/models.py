"""core/packs/models.py

Canonical Capability Pack Data Models and Manifest Schemas for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PackPermissionScope(str, Enum):
    """Standard permission scopes defined in docs/CAPABILITY_PACKS.md."""

    FS_READ = "fs:read"
    FS_WRITE = "fs:write"
    STORAGE_SQLITE = "storage:sqlite"
    NET_OUTBOUND = "net:outbound"
    NET_HTTP = "net:http"
    SHELL_EXEC = "shell:exec"
    CRON_SCHEDULE = "cron:schedule"
    GIT_WORKTREE = "git:worktree"


class PackPermission(BaseModel):
    """Explicit permission grant declared by a Capability Pack."""

    scope: str
    paths: Optional[List[str]] = None
    description: Optional[str] = None


class PackCapability(BaseModel):
    """A named capability packaged within a Capability Pack."""

    id: str
    name: str
    description: str
    canonical_binding: str
    requires_approval: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PackSkill(BaseModel):
    """A packaged skill reference within a Capability Pack."""

    id: str
    path: str
    description: Optional[str] = None


class PackWorkflow(BaseModel):
    """A declarative workflow packaged within a Capability Pack."""

    id: str
    path: str
    description: Optional[str] = None


class PackEvaluation(BaseModel):
    """Evaluation suite and acceptance criteria for pack verification."""

    test_suite: str
    min_pass_rate: float = 1.0


class PackManifest(BaseModel):
    """Canonical manifest schema for Agent Engine Capability Packs."""

    schema_version: str = "1.0.0"
    id: str
    name: str
    version: str
    description: str
    category: str
    author: str
    permissions: List[PackPermission] = Field(default_factory=list)
    capabilities: List[PackCapability] = Field(default_factory=list)
    skills: List[PackSkill] = Field(default_factory=list)
    workflows: List[PackWorkflow] = Field(default_factory=list)
    evaluations: Optional[PackEvaluation] = None
    enabled: bool = True
