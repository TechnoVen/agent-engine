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

    def compute_definition_hash(self) -> str:
        """Compute deterministic SHA-256 digest of canonical definition JSON."""
        import hashlib
        import json

        dumped = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


class NodeRunStatus(str, Enum):
    """Lifecycle status of a single node run within a workflow run."""

    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


def generate_workflow_id() -> str:
    """Generate canonical workflow ID with 'wf_' prefix."""
    import uuid

    return f"wf_{uuid.uuid4().hex[:12]}"


def generate_workflow_run_id() -> str:
    """Generate canonical workflow run ID with 'wfr_' prefix."""
    import uuid

    return f"wfr_{uuid.uuid4().hex[:12]}"


def generate_node_run_id() -> str:
    """Generate canonical workflow node run ID with 'wfnr_' prefix."""
    import uuid

    return f"wfnr_{uuid.uuid4().hex[:12]}"


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


class WorkflowNodeRun(BaseModel):
    """Traceable execution record for a single node inside a WorkflowRun."""

    node_run_id: str = Field(default_factory=generate_node_run_id)
    workflow_run_id: str = Field(..., description="Parent workflow run identifier")
    node_id: str = Field(..., description="Node ID within workflow definition")
    node_type: WorkflowNodeType = Field(..., description="Node classification")
    job_id: Optional[str] = Field(None, description="Associated canonical Job ID")
    status: NodeRunStatus = Field(default=NodeRunStatus.PENDING)
    approval_id: Optional[str] = Field(None, description="Pending approval ID for HITL gates")
    operation_digest: Optional[str] = Field(
        None, description="Canonical operation digest for exact gate approval"
    )
    suspended_at: Optional[str] = Field(
        None, description="Timestamp when gate entered WAITING_APPROVAL"
    )
    resolved_at: Optional[str] = Field(
        None, description="Timestamp when gate was resolved (approved/rejected)"
    )
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class WorkflowRun(BaseModel):
    """Execution state and trace of a specific workflow instance."""

    run_id: str = Field(
        default_factory=generate_workflow_run_id, description="Unique run identifier"
    )
    workflow_id: str = Field(..., description="Associated workflow definition identifier")
    definition_hash: str = Field(
        default="", description="Immutable SHA-256 digest of the executed workflow definition"
    )
    definition_snapshot: Dict[str, Any] = Field(
        default_factory=dict, description="Immutable snapshot of definition at run time"
    )
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.PENDING, description="Current run status"
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict, description="Input parameters passed to this execution run"
    )
    outputs: Dict[str, Any] = Field(
        default_factory=dict, description="Final aggregated outputs emitted by the run"
    )
    node_runs: Dict[str, WorkflowNodeRun] = Field(
        default_factory=dict, description="Per-node execution records keyed by node ID"
    )
    error: Optional[str] = Field(None, description="Terminal failure or error message")
    step_results: Dict[str, StepResult] = Field(
        default_factory=dict, description="Legacy execution traces keyed by node ID"
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

    @property
    def workflow_run_id(self) -> str:
        """Alias for canonical workflow_run_id."""
        return self.run_id

    def to_dict(self) -> Dict[str, Any]:
        """Serialize workflow run to plain dict."""
        return self.model_dump()
