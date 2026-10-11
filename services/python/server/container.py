"""services/python/server/container.py

Centralized dependency container and service lifecycle for Agent Engine server.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, List, Optional

from core.artifacts import ArtifactService
from core.execution import ExecutionCoordinator
from core.ledger import ExecutionLedgerService
from core.memory import AgentMemory, ObservationalMemory
from core.router import ModelRouter
from core.safety import get_policy_engine, PolicyEngine
from core.session.store import UnifiedSessionStore, get_session_store as _core_get_session_store
from core.storage import get_storage_backend as _core_get_storage_backend, StorageBackend
from core.telemetry.cost import get_cost_tracker, CostTracker
from core.workflows import SwarmCoordinator, WorkflowStorage

logger = logging.getLogger("agent_engine.container")

START_TIME = time.time()


@dataclass
class AppServices:
    """Canonical service container bundling core system dependencies."""

    storage: StorageBackend
    policy_engine: PolicyEngine
    model_router: ModelRouter
    cost_tracker: CostTracker
    memory: AgentMemory = field(default_factory=AgentMemory)
    observational_memory: ObservationalMemory = field(default_factory=ObservationalMemory)
    coordinator: Optional[ExecutionCoordinator] = None
    artifact_service: Optional[ArtifactService] = None
    ledger_service: Optional[ExecutionLedgerService] = None
    workflow_storage: Optional[WorkflowStorage] = None
    workflow_service: Optional[Any] = None
    swarm_coordinator: Optional[SwarmCoordinator] = None
    writing_service: Optional[Any] = None

    def get_workflow_service(self) -> Any:
        if self.workflow_service is None:
            from core.workflows.service import WorkflowService

            db_path = getattr(self.storage, "db_path", None)
            self.workflow_service = WorkflowService(storage=self.storage, db_path=db_path)
        return self.workflow_service

    def get_writing_workflow_service(self) -> Any:
        if self.writing_service is None:
            from core.writing.workflow import ArticleWorkflowService

            self.writing_service = ArticleWorkflowService(
                coordinator=self.get_coordinator(),
                artifact_service=self.get_artifact_service(),
                workflow_service=self.get_workflow_service(),
                storage=self.storage,
            )
        return self.writing_service

    def get_coordinator(self) -> ExecutionCoordinator:
        if self.coordinator is None:
            self.coordinator = ExecutionCoordinator(
                storage=self.storage,
                policy_engine=self.policy_engine,
                model_router=self.model_router,
                cost_tracker=self.cost_tracker,
                artifact_service=self.get_artifact_service(),
            )
        return self.coordinator

    def get_artifact_service(self) -> ArtifactService:
        if self.artifact_service is None:
            if self.coordinator and getattr(self.coordinator, "artifact_service", None):
                self.artifact_service = self.coordinator.artifact_service
            else:
                self.artifact_service = ArtifactService(storage=self.storage)
        return self.artifact_service

    def get_ledger_service(self) -> ExecutionLedgerService:
        if self.ledger_service is None:
            self.ledger_service = ExecutionLedgerService(
                storage=self.storage,
                artifact_service=self.get_artifact_service(),
            )
        return self.ledger_service

    def get_workflow_storage(self) -> WorkflowStorage:
        if self.workflow_storage is None:
            self.workflow_storage = WorkflowStorage()
        return self.workflow_storage

    def get_swarm_coordinator(self) -> SwarmCoordinator:
        if self.swarm_coordinator is None:
            self.swarm_coordinator = SwarmCoordinator()
        return self.swarm_coordinator


# Global container instance
_services_instance: Optional[AppServices] = None
_event_subscribers: List[asyncio.Queue] = []


def get_services() -> AppServices:
    """Obtain or lazily construct the canonical AppServices container."""
    global _services_instance
    if _services_instance is None:
        import sys

        storage = None
        api_mod = sys.modules.get("services.python.server.api")
        if (
            api_mod
            and hasattr(api_mod, "get_storage_backend")
            and api_mod.get_storage_backend is not get_storage_backend
        ):
            storage = api_mod.get_storage_backend()
        if storage is None:
            storage = _core_get_storage_backend()
        policy = get_policy_engine()
        router = ModelRouter()
        cost_tracker = get_cost_tracker()
        _services_instance = AppServices(
            storage=storage,
            policy_engine=policy,
            model_router=router,
            cost_tracker=cost_tracker,
        )
    return _services_instance


def set_services(services: AppServices) -> None:
    """Explicitly inject an AppServices container (primarily for tests)."""
    global _services_instance
    _services_instance = services


def get_storage_backend() -> StorageBackend:
    """Get active storage backend, checking for any monkeypatched api.get_storage_backend."""
    import sys

    api_mod = sys.modules.get("services.python.server.api")
    if (
        api_mod
        and hasattr(api_mod, "get_storage_backend")
        and api_mod.get_storage_backend is not get_storage_backend
    ):
        return api_mod.get_storage_backend()
    return get_services().storage


def get_session_store() -> UnifiedSessionStore:
    """Get active session store, checking for any monkeypatched api.get_session_store."""
    import sys

    api_mod = sys.modules.get("services.python.server.api")
    if (
        api_mod
        and hasattr(api_mod, "get_session_store")
        and api_mod.get_session_store is not get_session_store
    ):
        return api_mod.get_session_store()
    return _core_get_session_store()


def get_execution_coordinator() -> ExecutionCoordinator:
    return get_services().get_coordinator()


def set_execution_coordinator(coord: ExecutionCoordinator) -> None:
    services = get_services()
    services.coordinator = coord
    if getattr(coord, "artifact_service", None):
        services.artifact_service = coord.artifact_service


def get_artifact_service() -> ArtifactService:
    return get_services().get_artifact_service()


def set_artifact_service(service: ArtifactService) -> None:
    services = get_services()
    services.artifact_service = service
    if services.coordinator and hasattr(services.coordinator, "artifact_service"):
        services.coordinator.artifact_service = service


def get_ledger_service() -> ExecutionLedgerService:
    return get_services().get_ledger_service()


def set_ledger_service(service: ExecutionLedgerService) -> None:
    get_services().ledger_service = service


def get_memory() -> AgentMemory:
    return get_services().memory


def get_observational_memory() -> ObservationalMemory:
    return get_services().observational_memory


def get_model_router() -> ModelRouter:
    return get_services().model_router


def get_cost_tracker_service() -> CostTracker:
    return get_services().cost_tracker


# Convenience module-level aliases
memory_instance = get_services().memory
observational_memory_instance = get_services().observational_memory
router_instance = get_services().model_router
cost_tracker_instance = get_services().cost_tracker


def get_workflow_storage() -> WorkflowStorage:
    return get_services().get_workflow_storage()


def set_workflow_storage(storage: WorkflowStorage) -> None:
    get_services().workflow_storage = storage


def get_workflow_service() -> Any:
    return get_services().get_workflow_service()


def set_workflow_service(service: Any) -> None:
    get_services().workflow_service = service


def get_swarm_coordinator() -> SwarmCoordinator:
    return get_services().get_swarm_coordinator()


def set_swarm_coordinator(coord: SwarmCoordinator) -> None:
    get_services().swarm_coordinator = coord


def get_writing_workflow_service() -> Any:
    return get_services().get_writing_workflow_service()


def set_writing_workflow_service(service: Any) -> None:
    get_services().writing_service = service


def get_event_subscribers() -> List[asyncio.Queue]:
    return _event_subscribers


def broadcast_event(event_data: Dict[str, Any]) -> None:
    """Broadcast an event dictionary to all connected SSE clients."""
    for queue in list(_event_subscribers):
        try:
            queue.put_nowait(event_data)
        except Exception:
            pass
