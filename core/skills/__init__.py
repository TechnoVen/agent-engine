"""core/skills package.

Unified Multi-Tool Skill Management for Agent Engine (Phase 6 - Milestone M4).
"""

from core.skills.boundary import (
    CapabilityBoundary,
    check_permission,
    validate_project_path,
)
from core.skills.collections import SkillCollectionManager
from core.skills.discovery import MultiToolSkillDiscovery
from core.skills.editor import SkillEditor, SkillValidationResult
from core.skills.models import (
    Skill,
    SkillCollection,
    SkillFormat,
    SkillMetadata,
    SkillPermission,
    SkillSource,
)
from core.skills.path import (
    ResolvedWorkspacePath,
    WorkspacePathResolver,
    WorkspacePathViolation,
    compute_effective_workspace_scopes,
)
from core.skills.registry import (
    SkillRegistryClient,
    SkillRegistryPackage,
    scan_content_safety,
)
from core.skills.remote import RemoteSkillDiscoveryClient

SkillDiscovery = MultiToolSkillDiscovery

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillPermission",
    "SkillSource",
    "SkillFormat",
    "SkillCollection",
    "CapabilityBoundary",
    "check_permission",
    "validate_project_path",
    "ResolvedWorkspacePath",
    "WorkspacePathResolver",
    "WorkspacePathViolation",
    "compute_effective_workspace_scopes",
    "MultiToolSkillDiscovery",
    "SkillDiscovery",
    "SkillEditor",
    "SkillValidationResult",
    "SkillCollectionManager",
    "SkillRegistryClient",
    "SkillRegistryPackage",
    "scan_content_safety",
    "RemoteSkillDiscoveryClient",
]
