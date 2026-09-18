"""core/workflows package.

Workflow Engine Subsystem for Agent Engine (Phase 7 - Milestone M5).
"""

from core.workflows.engine import WorkflowEngine
from core.workflows.models import (
    StepResult,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowPosition,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)
from core.workflows.gates import WorkflowGateManager
from core.workflows.parser import WorkflowParser
from core.workflows.storage import WorkflowStorage
from core.workflows.swarm import (
    FEATURED_SWARM_CASES,
    SwarmAgentProgress,
    SwarmAgentSpec,
    SwarmCase,
    SwarmCoordinator,
    SwarmRunResult,
)

__all__ = [
    "WorkflowNodeType",
    "WorkflowStatus",
    "WorkflowRunStatus",
    "WorkflowPosition",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowDefinition",
    "StepResult",
    "WorkflowRun",
    "WorkflowParser",
    "WorkflowEngine",
    "WorkflowStorage",
    "WorkflowGateManager",
    "SwarmAgentSpec",
    "SwarmCase",
    "SwarmAgentProgress",
    "SwarmRunResult",
    "SwarmCoordinator",
    "FEATURED_SWARM_CASES",
]
