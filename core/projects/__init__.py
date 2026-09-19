"""Canonical Projects Package (Task R1.6)."""

from core.projects.models import (
    Project,
    ProjectSettings,
    generate_project_id,
)

__all__ = [
    "Project",
    "ProjectSettings",
    "generate_project_id",
]
