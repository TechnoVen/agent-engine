"""core/workflows/models.py

Domain models and graph definitions for Agent Engine Workflow Engine.
Part of Phase 7 (Task 7.1 - Milestone M5).

Adheres to:
- ADR-012: Layered Workflows (DSPy Modules for micro-steps + Graph Engine for macro-DAGs)
- ADR-013: Zero non-free dependencies, 100% open-source local-first execution.
- ADR-015: 90/9/1 Cost Optimization Discipline & Execution Routing.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class WorkflowNodeType(str, Enum):
    """Types of executable or structural nodes in a workflow graph."""

    PIPELINE = "pipeline"
    SKILL = "skill"
    AGENT = "agent"
    GATE = "gate"
    CONDITION = "condition"
    PARALLEL = "parallel"
    MERGE = "merge"


class WorkflowStatus(str, Enum):
    """Lifecycle status of a saved workflow definition."""

    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowRunStatus(str, Enum):
    """Lifecycle status of an active or historical workflow execution run."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowPosition(BaseModel):
    """2D coordinates for visual canvas node rendering."""

    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    """A discrete node within a workflow DAG."""

    id: str = Field(..., description="Unique node identifier within the workflow")
    type: WorkflowNodeType = Field(..., description="Executable or structural node type")
    name: str = Field(..., description="Human-readable node label")
    description: str = Field(default="", description="Detailed node description")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Node-specific configuration (e.g. pipeline_name, skill_id, model_tier, expr)",
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameter bindings mapping input keys to expressions or upstream outputs",
    )
    outputs: List[str] = Field(
        default_factory=list,
        description="Names of variables emitted by this node into the workflow state",
    )
    position: Optional[WorkflowPosition] = Field(
        default=None, description="Visual canvas layout position"
    )


class WorkflowEdge(BaseModel):
    """A directed transition between two nodes in the workflow DAG."""

    id: str = Field(..., description="Unique edge identifier")
    source: str = Field(..., description="Source node identifier")
    target: str = Field(..., description="Target node identifier")
    condition: Optional[str] = Field(
        default=None,
        description="Optional branch condition or label (e.g. 'true', 'false', 'approved')",
    )


class WorkflowDefinition(BaseModel):
    """Complete graph definition of a reusable agent workflow."""

    id: str = Field(..., description="Unique slug or UUID of the workflow")
    name: str = Field(..., description="Display name of the workflow")
    description: str = Field(default="", description="Overview and purpose of the workflow")
    version: str = Field(default="1.0.0", description="Semantic version string")
    status: WorkflowStatus = Field(
        default=WorkflowStatus.READY, description="Workflow lifecycle status"
    )
    nodes: List[WorkflowNode] = Field(default_factory=list, description="All graph nodes")
    edges: List[WorkflowEdge] = Field(default_factory=list, description="All directed graph edges")
    inputs_schema: Dict[str, Any] = Field(
        default_factory=dict, description="JSON schema or typing of required workflow inputs"
    )
    outputs_schema: Dict[str, Any] = Field(
        default_factory=dict, description="JSON schema or typing of workflow outputs"
    )
    tags: List[str] = Field(default_factory=list, description="Organizational and category tags")
    steps: List[str] = Field(
        default_factory=list, description="Ordered or unordered node IDs for legacy compatibility"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Custom metadata, author, and environment settings"
    )
    created_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    updated_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    @model_validator(mode="after")
    def populate_steps(self) -> "WorkflowDefinition":
        if not self.steps and self.nodes:
            self.steps = [n.id for n in self.nodes]
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialize workflow definition to plain dict."""
        return self.model_dump()


class StepResult(BaseModel):
    """Execution outcome of a single node in a workflow run."""

    node_id: str
    node_type: WorkflowNodeType
    status: str = "completed"
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    cost_usd: float = 0.0


class WorkflowRun(BaseModel):
    """Execution state and trace of a specific workflow instance."""

    run_id: str = Field(..., description="Unique run identifier")
    workflow_id: str = Field(..., description="Associated workflow definition identifier")
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.PENDING, description="Current run status"
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict, description="Input parameters passed to this execution run"
    )
    outputs: Dict[str, Any] = Field(
        default_factory=dict, description="Final aggregated outputs emitted by the run"
    )
    step_results: Dict[str, StepResult] = Field(
        default_factory=dict, description="Execution traces keyed by node ID"
    )
    current_node_id: Optional[str] = Field(default=None, description="Active or paused node ID")
    pending_gate: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata for active human-in-the-loop approval gate"
    )
    total_cost_usd: float = Field(default=0.0, description="Total LLM and execution cost accrued")
    created_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    completed_at: Optional[str] = Field(
        default=None, description="Timestamp when execution completed or failed"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize workflow run to plain dict."""
        return self.model_dump()
