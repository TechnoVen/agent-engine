"""Canonical Projects Package (Task R1.6)."""

from core.projects.models import (
    Project,
    ProjectSettings,
    generate_project_id,
)
from core.projects.service import (
    ProjectService,
    get_project_service,
)

__all__ = [
    "Project",
    "ProjectSettings",
    "generate_project_id",
    "ProjectService",
    "get_project_service",
]
