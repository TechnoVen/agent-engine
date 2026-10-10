"""core/projects/service.py

Canonical Project Domain Service for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).

Governing Invariant:
Exposes canonical project workspace boundary, metadata, and instructions
backed by the authoritative StorageBackend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.projects.models import Project, ProjectSettings, generate_project_id
from core.storage import StorageBackend, get_storage_backend

logger = logging.getLogger("agent_engine.projects.service")


class ProjectService:
    """Canonical service managing workspace projects, root paths, and instructions."""

    def __init__(self, storage: Optional[StorageBackend] = None):
        self._storage = storage

    @property
    def storage(self) -> StorageBackend:
        if self._storage is None:
            self._storage = get_storage_backend()
        return self._storage

    def get_project(self, project_id: str) -> Optional[Project]:
        """Retrieve project by ID, returning canonical Project model."""
        data = self.storage.get_project(project_id)
        if not data:
            return None
        return Project.model_validate(data)

    def get_default_project(self) -> Optional[Project]:
        """Retrieve the default canonical workspace project."""
        data = self.storage.get_default_project()
        if not data:
            return None
        return Project.model_validate(data)

    def list_projects(self, limit: int = 50, offset: int = 0) -> List[Project]:
        """List canonical workspace projects with pagination."""
        raw_list = self.storage.list_projects(limit=limit, offset=offset)
        projects: List[Project] = []
        for item in raw_list:
            try:
                projects.append(Project.model_validate(item))
            except Exception as e:
                logger.warning("Failed to validate project row %s: %s", item.get("id"), e)
        return projects

    def create_project(
        self,
        name: str,
        root_path: str,
        description: Optional[str] = None,
        instructions: str = "",
        settings: Optional[ProjectSettings] = None,
        is_default: bool = False,
        project_id: Optional[str] = None,
    ) -> Project:
        """Create and persist a new canonical workspace project."""
        pid = project_id or generate_project_id()
        proj = Project(
            id=pid,
            name=name,
            description=description,
            root_path=root_path,
            instructions=instructions,
            settings=settings or ProjectSettings(),
            is_default=is_default,
        )
        self.storage.create_project(proj.model_dump())
        return proj

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[Project]:
        """Update an existing workspace project."""
        updated = self.storage.update_project(project_id, updates)
        if not updated:
            return None
        return Project.model_validate(updated)

    def delete_project(self, project_id: str) -> bool:
        """Delete project by primary key."""
        return self.storage.delete_project(project_id)

    def get_project_context(self, project_id: str) -> Dict[str, Any]:
        """Assemble structured context representation for execution inference."""
        proj = self.get_project(project_id)
        if not proj:
            return {}
        return {
            "project_id": proj.id,
            "name": proj.name,
            "root_path": proj.root_path,
            "instructions": proj.instructions,
            "settings": proj.settings.model_dump(),
        }


_global_project_service: Optional[ProjectService] = None


def get_project_service(storage: Optional[StorageBackend] = None) -> ProjectService:
    """Retrieve or initialize the singleton ProjectService."""
    global _global_project_service
    if _global_project_service is None or storage is not None:
        _global_project_service = ProjectService(storage=storage)
    return _global_project_service
