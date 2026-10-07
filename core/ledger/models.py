"""Canonical Execution Ledger Models (Task R1.11).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/DATA_MODEL.md, docs/EXECUTION_MODEL.md, docs/ROADMAP.md (R1.11)
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.execution.models import ExecutionStatus, VerificationResult

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[-_]?key|auth|token|secret|password|credential|private[-_]?key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9_\-\.]{8,}|sk-[a-z0-9_\-]{14,}|ghp_[a-z0-9]{14,}|key-[a-z0-9]{14,}|password\s*[:=]\s*[^\s,;]+)"
)
_ABSOLUTE_PATH_PATTERN = re.compile(r"/(?:home|Users|root)/[a-zA-Z0-9_\.\-]+(/[a-zA-Z0-9_\.\-]+)*")


def sanitize_sensitive_data(val: Any) -> Any:
    """Recursively redact host absolute paths and credentials."""
    if isinstance(val, str):
        scrubbed = _SENSITIVE_VALUE_PATTERN.sub("[REDACTED_CREDENTIAL]", val)
        scrubbed = _ABSOLUTE_PATH_PATTERN.sub("[REDACTED_PATH]", scrubbed)
        return scrubbed
    elif isinstance(val, dict):
        res = {}
        for k, v in val.items():
            if _SENSITIVE_KEY_PATTERN.search(str(k)):
                res[k] = "[REDACTED]"
            else:
                res[k] = sanitize_sensitive_data(v)
        return res
    elif isinstance(val, list):
        return [sanitize_sensitive_data(item) for item in val]
    return val


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
    project_root_available: bool = False
    project_instructions_hash: Optional[str] = None
    session_turns_available: int = 0
    session_turns_retained: int = 0
    session_turns_dropped: int = 0
    history_truncated: bool = False
    prompt_tokens_estimated: int = 0
    instruction_tokens_estimated: int = 0
    context_tokens_estimated: int = 0
    pipeline_name: Optional[str] = None
    pipeline_version: Optional[str] = None
    pipeline_category: Optional[str] = None
    pipeline_author: Optional[str] = None
    skill_id: Optional[str] = None
    skill_version: Optional[str] = None
    skill_source: Optional[str] = None
    skill_implementation_hash: Optional[str] = None
    adapter_id: Optional[str] = None
    adapter_version: Optional[str] = None
    adapter_protocol: Optional[str] = None


class ModelCallRecord(BaseModel):
    """Auditable record of an individual language model invocation within the execution."""

    call_id: str
    provider_id: str
    model_id: str
    endpoint_class: Optional[str] = None
    routing_tier: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    cost_usd: float = 0.0
    cost_provenance: CostProvenance = CostProvenance.CALCULATED
    status: str = "completed"  # "started", "completed", "failed"
    is_fallback: bool = False
    fallback_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ToolInvocationRecord(BaseModel):
    """Auditable record of a tool/skill/adapter invocation within the execution."""

    invocation_id: str
    execution_id: Optional[str] = None
    tool_id: str
    version: Optional[str] = None
    arguments_digest: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "completed"  # "started", "completed", "failed"
    approval_id: Optional[str] = None
    requested_args_redacted: Optional[Dict[str, Any]] = None
    output: Optional[Any] = None
    result_summary: Optional[str] = None
    artifacts: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        """Return public dictionary representation with sensitive fields redacted."""
        return self.model_dump()


class ApprovalRecord(BaseModel):
    """Auditable record of an approval gate encountered during execution."""

    approval_id: str
    policy_id: Optional[str] = None
    tool_name: Optional[str] = None
    digest: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    status: str = "required"  # "required", "approved", "rejected", "consumed"
    decided_by: Optional[str] = None
    expires_at: Optional[str] = None
    consumed: bool = False
    timestamp: str

    def to_public_dict(self) -> Dict[str, Any]:
        """Return public dictionary representation with sensitive fields redacted."""
        return sanitize_sensitive_data(self.model_dump())


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
    model_calls: List[ModelCallRecord] = Field(default_factory=list)
    tools: List[ToolInvocationRecord] = Field(default_factory=list)
    approvals: List[ApprovalRecord] = Field(default_factory=list)
    artifacts: List[ArtifactSummaryRecord] = Field(default_factory=list)
    usage: UsageAndCostTrace = Field(default_factory=UsageAndCostTrace)
    verification: Optional[VerificationResult] = None
    events: List[ExecutionEventRecord] = Field(default_factory=list)

    @property
    def context_provenance(self) -> Dict[str, Any]:
        """Convenience property returning dict representation of context provenance."""
        return self.context.model_dump()

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_public_dict(self) -> Dict[str, Any]:
        """Project sanitized trace for public REST consumers.

        Redacts host filesystem paths (project_root), scrubs credentials, bearer tokens,
        and secrets from error messages and tool invocations.
        """
        data = self.model_dump()

        # Redact host filesystem path
        ctx = data.get("context") or {}
        if ctx.get("project_root"):
            ctx["project_root_available"] = True
            ctx["project_root"] = None
        else:
            ctx["project_root_available"] = ctx.get("project_root_available", False)
        data["context"] = ctx

        # Redact errors
        if data.get("error"):
            data["error"] = sanitize_sensitive_data(data["error"])

        # Redact tool records
        if data.get("tools"):
            for t in data["tools"]:
                if t.get("requested_args_redacted"):
                    t["requested_args_redacted"] = sanitize_sensitive_data(
                        t["requested_args_redacted"]
                    )
                if t.get("error"):
                    t["error"] = sanitize_sensitive_data(t["error"])
                if t.get("output"):
                    t["output"] = sanitize_sensitive_data(t["output"])
                if t.get("result_summary"):
                    t["result_summary"] = sanitize_sensitive_data(t["result_summary"])

        # Redact event payloads
        if data.get("events"):
            for ev in data["events"]:
                if ev.get("payload"):
                    ev["payload"] = sanitize_sensitive_data(ev["payload"])

        return data


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
