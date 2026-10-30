"""services/python/server/routers/__init__.py

Domain APIRouters for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

from services.python.server.routers import (
    adapters,
    artifacts,
    chat,
    collaboration,
    credentials,
    executions,
    ledger,
    memory,
    models,
    packs,
    patches,
    pipelines,
    policies,
    projects,
    skills,
    swarm,
    system,
    tasks,
    telemetry,
    workflows,
    writing,
)

__all__ = [
    "adapters",
    "artifacts",
    "chat",
    "collaboration",
    "credentials",
    "executions",
    "ledger",
    "memory",
    "models",
    "packs",
    "patches",
    "pipelines",
    "policies",
    "projects",
    "skills",
    "swarm",
    "system",
    "tasks",
    "telemetry",
    "workflows",
    "writing",
]
