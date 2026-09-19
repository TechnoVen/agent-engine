"""Canonical Projects Package (Task R1.6)."""

from core.projects.models import (
    DEFAULT_PROJECT_ID,
    Project,
    ProjectSettings,
    generate_project_id,
)

__all__ = [
    "DEFAULT_PROJECT_ID",
    "Project",
    "ProjectSettings",
    "generate_project_id",
]
