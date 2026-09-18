"""Canonical Execution Domain Models (Task R1.1).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(str, Enum):
    """Lifecycle statuses for the execution state machine."""

    CREATED = "created"
    CONTEXT_BUILDING = "context_building"
    ROUTING = "routing"
    POLICY_CHECK = "policy_check"
    BUDGET_CHECK = "budget_check"
    PLANNING = "planning"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class RoutingTier(str, Enum):
    """Execution tiers defined by the 90/9/1 cost optimization framework."""

    CODE = "code"
    CACHE = "cache"
    LOCAL = "local"
    MID = "mid"
    FRONTIER = "frontier"
    HUMAN = "human"


class ExecutionEventType(str, Enum):
    """Canonical event types emitted during execution lifecycle."""

    STATE_CHANGE = "state_change"
    ROUTING_RESOLVED = "routing_resolved"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    TOKEN_DELTA = "token_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    OUTPUT_CHUNK = "output_chunk"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ERROR = "error"


def generate_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex[:16]}"


def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:16]}"


def current_timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionRequest(BaseModel):
    """Immutable specification of an execution request."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=generate_request_id)
    project_id: str
    session_id: Optional[str] = None
    task_type: str = "chat"  # "chat", "dspy", "skill", "workflow_step", "agent_task"
    prompt: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    model_preference: Optional[str] = None
    target_tier: Optional[RoutingTier] = None
    isolation_mode: str = "standard"  # "standard", "worktree", "read_only"
    parent_execution_id: Optional[str] = None
    token_budget: int = 8000
    created_at: str = Field(default_factory=current_timestamp_iso)


class ExecutionContext(BaseModel):
    """Assembled operational context passed to dispatch."""

    execution_id: str
    project_id: str
    project_root: str
    project_instructions: str = ""
    active_skills: List[str] = Field(default_factory=list)
    retrieved_passages: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    token_budget: int = 8000
    security_policy_id: str = "default"
    created_at: str = Field(default_factory=current_timestamp_iso)


class VerificationResult(BaseModel):
    """Verification outcome required before transitioning to COMPLETED."""

    passed: bool
    strategy: str = "default"  # "schema", "assertion", "eval", "text_validation"
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = Field(default_factory=current_timestamp_iso)


class ExecutionResult(BaseModel):
    """Consolidated outcome of an execution."""

    execution_id: str
    status: ExecutionStatus
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: float = 0.0
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    routing_tier: Optional[RoutingTier] = None
    cache_hit: bool = False
    is_cost_estimated: bool = False
    artifacts_created: List[str] = Field(default_factory=list)
    verification: Optional[VerificationResult] = None


class ExecutionEvent(BaseModel):
    """Append-only event emitted during an execution."""

    id: str = Field(default_factory=generate_event_id)
    execution_id: str
    sequence_num: int
    timestamp: str = Field(default_factory=current_timestamp_iso)
    event_type: ExecutionEventType
    payload: Dict[str, Any] = Field(default_factory=dict)


class Execution(BaseModel):
    """Authoritative execution entity tracked in storage and state machine."""

    id: str = Field(default_factory=generate_execution_id)
    project_id: str
    session_id: Optional[str] = None
    request: ExecutionRequest
    status: ExecutionStatus = ExecutionStatus.CREATED
    provider: Optional[str] = None
    model: Optional[str] = None
    routing_tier: Optional[RoutingTier] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    is_cost_estimated: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    created_at: str = Field(default_factory=current_timestamp_iso)
