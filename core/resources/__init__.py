"""core/resources/__init__.py

Canonical Host Resource and Telemetry Subsystem for Agent Engine.
Part of Milestone R3 Task R3.3 (Resource Manager).
"""

from core.resources.manager import (
    ResourceManager,
    get_resource_manager,
    reset_resource_manager,
)
from core.resources.models import (
    AcceleratorResources,
    AcceleratorType,
    CpuResources,
    MemoryResources,
    ProbeStatus,
    ResourceSnapshot,
)

__all__ = [
    "ResourceManager",
    "get_resource_manager",
    "reset_resource_manager",
    "ResourceSnapshot",
    "CpuResources",
    "MemoryResources",
    "AcceleratorResources",
    "AcceleratorType",
    "ProbeStatus",
]
