"""Canonical Execution Ledger Models (Task R1.11).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md, docs/EXECUTION_MODEL.md, docs/ROADMAP.md (R1.11)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.execution.models import ExecutionStatus, VerificationResult


class CostProvenance(str, Enum):
    """Provenance tracking for execution cost and token usage."""

    PROVIDER_REPORTED = "provider_reported"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class ModelRoutingTrace(BaseModel):
    """Trace of model selection and routing resolutions."""

    requested_tier: Optional[str] = None
    resolved_tier: Optional[str] = None
    requested_model: Optional[str] = None
    resolved_model: Optional[str] = None
    actual_model: Optional[str] = None
    actual_provider: Optional[str] = None
    is_fallback: bool = False
    fallback_chain: List[str] = Field(default_factory=list)
    fallback_history: List[Dict[str, Any]] = Field(default_factory=list)


class ContextProvenance(BaseModel):
    """Cryptographic and volumetric provenance of operational context."""

    project_root: Optional[str] = None
    project_instructions_hash: Optional[str] = None
    session_turns_available: int = 0
    session_turns_retained: int = 0
    session_turns_dropped: int = 0
    history_truncated: bool = False
    prompt_tokens_estimated: int = 0
    instruction_tokens_estimated: int = 0
    context_tokens_estimated: int = 0


class ToolInvocationRecord(BaseModel):
    """Auditable record of a tool invocation within the execution."""

    invocation_id: str
    tool_id: str
    status: str = "completed"  # "started", "completed", "failed"
    duration_ms: Optional[float] = None
    approval_id: Optional[str] = None
    requested_args_redacted: Optional[Dict[str, Any]] = None
    output: Optional[Any] = None
    error: Optional[str] = None


class ApprovalRecord(BaseModel):
    """Auditable record of an approval gate encountered during execution."""

    approval_id: str
    policy_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    status: str = "required"  # "required", "approved", "rejected"
    decided_by: Optional[str] = None
    timestamp: str


class ArtifactSummaryRecord(BaseModel):
    """Summary reference to an artifact produced by this execution."""

    id: str
    name: str
    type: str
    size_bytes: int
    sha256_hash: str
    status: str
    mime_type: Optional[str] = None


class UsageAndCostTrace(BaseModel):
    """Truthful usage and cost accounting for the execution."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    is_cost_estimated: bool = False
    cost_provenance: CostProvenance = CostProvenance.UNAVAILABLE


class ExecutionEventRecord(BaseModel):
    """Durable append-only event projection."""

    id: str
    sequence_num: int
    timestamp: str
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(BaseModel):
    """Authoritative historical projection of an execution."""

    execution_id: str
    project_id: str
    session_id: Optional[str] = None
    actor: Optional[str] = None
    status: ExecutionStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None

    routing: ModelRoutingTrace = Field(default_factory=ModelRoutingTrace)
    context: ContextProvenance = Field(default_factory=ContextProvenance)
    tools: List[ToolInvocationRecord] = Field(default_factory=list)
    approvals: List[ApprovalRecord] = Field(default_factory=list)
    artifacts: List[ArtifactSummaryRecord] = Field(default_factory=list)
    usage: UsageAndCostTrace = Field(default_factory=UsageAndCostTrace)
    verification: Optional[VerificationResult] = None
    events: List[ExecutionEventRecord] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class ExecutionSummary(BaseModel):
    """Authoritative compact summary for project execution listings."""

    execution_id: str
    project_id: str
    session_id: Optional[str] = None
    status: ExecutionStatus
    model: Optional[str] = None
    provider: Optional[str] = None
    routing_tier: Optional[str] = None
    duration_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    created_at: str
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    artifacts_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
