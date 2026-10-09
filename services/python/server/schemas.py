"""Pydantic Request and Response Schemas matching packages/shared-schema/openapi.yaml."""

from __future__ import annotations
import datetime
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.projects import ProjectSettings

# Pydantic Schemas matching packages/shared-schema/openapi.yaml
# ---------------------------------------------------------------------------


class SidecarHealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "0.1.0"
    engine: str = "Agent Engine"
    uptime_seconds: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class ScheduledTaskResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    cron: str
    cron_human: str = ""
    agent_persona: str = "Senior Engineer"
    model: str = "instant"
    status: str = "active"
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    cost_per_run: float = 0.0012
    monthly_estimate: float = 0.036
    is_off_peak: bool = True
    notification_channel: str = "slack"
    prompt: str
    created_at: str


class ScheduledTaskListResponse(BaseModel):
    tasks: List[ScheduledTaskResponse]


class ScheduledTaskCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    cron: str
    cron_human: Optional[str] = ""
    agent_persona: Optional[str] = "Senior Engineer"
    model: Optional[str] = "instant"
    is_off_peak: Optional[bool] = True
    notification_channel: Optional[str] = "slack"
    prompt: str


class ScheduledTaskToggleRequest(BaseModel):
    status: str


class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True
    skill_id: Optional[str] = None
    project_id: Optional[str] = None
    routing_objective: Optional[str] = None
    privacy_boundary: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    cost_usd: float = 0.0
    execution_id: Optional[str] = None
    status: str = "completed"
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    routing_tier: Optional[str] = None


class AgentInfo(BaseModel):
    id: str
    name: str
    status: str
    project: str = "default"
    current_task: Optional[str] = None


class SkillInfo(BaseModel):
    id: str
    name: str
    category: str = "general"
    description: str = ""
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    format: Optional[str] = None
    file_path: Optional[str] = None
    content: Optional[str] = None
    is_readonly: bool = False


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    skill_id: Optional[str] = None
    source: str = "agent-engine"
    author: str = "local"
    version: str = "1.0.0"
    category: str = "General"
    tags: List[str] = Field(default_factory=list)
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    format: str = "markdown"


class UpdateSkillRequest(BaseModel):
    content: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    category: Optional[str] = None


class ValidateSkillRequest(BaseModel):
    content: str
    format: str = "markdown"


class ValidateSkillResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    parsed_metadata: Optional[Dict[str, Any]] = None


class SkillCollectionInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CreateSkillCollectionRequest(BaseModel):
    name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list)
    collection_id: Optional[str] = None


class UpdateSkillCollectionRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class AddSkillToCollectionRequest(BaseModel):
    skill_id: str


class SkillSearchResult(BaseModel):
    skill: SkillInfo
    score: float


class SkillRegistryPackageInfo(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Agent Engine Core"
    tags: List[str] = Field(default_factory=list)
    category: str = "General"
    sha256: str = ""
    verified: bool = True
    installs: int = 0
    is_installed: bool = False
    installed_path: Optional[str] = None


class InstallSkillPackageRequest(BaseModel):
    package_id: str
    force: bool = False


class UninstallSkillPackageRequest(BaseModel):
    package_id: str


class RemoteSkillDiscoverRequest(BaseModel):
    endpoint_url: str
    api_token: Optional[str] = None


class RemoteSkillImportRequest(BaseModel):
    endpoint_url: str
    skill_id: str
    api_token: Optional[str] = None
    target_tool: Optional[str] = "agent-engine"
    force: bool = False


class ExecuteSkillRequest(BaseModel):
    skill_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ExecuteSkillResponse(BaseModel):
    skill_id: str
    results: Dict[str, Any]


class WorkflowInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    steps: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    status: str = "active"
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunWorkflowRequest(BaseModel):
    workflow_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResponse(BaseModel):
    execution_id: str
    status: str


class WorkflowValidateRequest(BaseModel):
    definition_yaml: Optional[str] = None
    definition_json: Optional[Dict[str, Any]] = None


class WorkflowValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0


class WorkflowDryRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class WorkflowGateDecisionRequest(BaseModel):
    reviewer: str = "operator"
    reason: Optional[str] = None
    input_overrides: Optional[Dict[str, Any]] = None


class WorkflowRedirectRequest(BaseModel):
    target_node_id: str
    reviewer: str = "operator"
    input_overrides: Optional[Dict[str, Any]] = None


class SwarmEstimateRequest(BaseModel):
    agents: Optional[List[Dict[str, Any]]] = None
    case_id: Optional[str] = None
    model_tier: str = "instant"


class SwarmRunApiRequest(BaseModel):
    prompt: str
    case_id: Optional[str] = None
    agents: Optional[List[Dict[str, Any]]] = None
    model_tier: str = "instant"


class MemoryQueryResponse(BaseModel):
    query: str
    passages: List[str]


class IngestMemoryRequest(BaseModel):
    content: str
    source: str = "local_doc"


class IngestMemoryResponse(BaseModel):
    document_id: str
    count: int


class ObservationRecordRequest(BaseModel):
    content: str
    category: str = "general"
    importance: float = 5.0
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ObservationRecordResponse(BaseModel):
    id: str
    content: str
    category: str
    importance: float
    created_at: float
    session_id: Optional[str] = None


class ScoredObservationItem(BaseModel):
    id: str
    content: str
    category: str
    importance: float
    created_at: float
    session_id: Optional[str] = None
    relevance_score: float
    importance_score: float
    recency_score: float
    final_score: float


class ObservationQueryResponse(BaseModel):
    query: str
    observations: List[ScoredObservationItem]


class PatchInfo(BaseModel):
    id: int
    file_path: str
    patch_type: str
    risk_level: str
    report: str
    status: str
    timestamp: str


class ActionResult(BaseModel):
    success: bool
    message: str


class TelemetryResponse(BaseModel):
    cpu_usage_percent: float
    ram_used_percent: float
    ram_total_gb: float
    ram_available_gb: float
    primary_provider: str
    active_model: str
    ollama_active: bool
    llamacpp_active: bool
    indexed_memory_documents: int
    gpu_detected: Optional[bool] = False
    gpu_model: Optional[str] = "Unknown"
    gpu_vendor: Optional[str] = "generic"
    vram_used_percent: Optional[float] = 0.0
    vram_used_gb: Optional[float] = 0.0
    vram_total_gb: Optional[float] = 0.0
    vram_free_gb: Optional[float] = 0.0
    vram_warning: Optional[bool] = False
    tokens_per_second: Optional[float] = 0.0
    local_runtime_active: Optional[bool] = False


class HardwareTelemetryResponse(BaseModel):
    cpu_usage_percent: float
    cpu_cores_logical: int
    cpu_cores_physical: int
    ram_used_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_available_gb: float
    gpu_detected: bool
    gpu_model: str
    gpu_vendor: str
    vram_used_percent: float
    vram_used_gb: float
    vram_total_gb: float
    vram_free_gb: float
    vram_warning: bool
    vram_warning_threshold: float = 95.0
    tokens_per_second: float = 0.0
    recent_inference_runtime: Optional[str] = None
    recent_inference_model: Optional[str] = None
    ollama_active: bool = False
    llamacpp_active: bool = False
    local_runtime_active: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())


class SpeedRecordRequest(BaseModel):
    tokens: int
    elapsed_seconds: float
    model: Optional[str] = "qwen2.5-coder:7b"
    runtime: Optional[str] = "ollama"


class TierSplitInfo(BaseModel):
    deterministic_cache_local_pct: float = 90.0
    mid_tier_pct: float = 9.0
    frontier_pct: float = 1.0
    code_cache_calls: int = 0
    mid_tier_calls: int = 0
    frontier_calls: int = 0


class DistillationCandidate(BaseModel):
    candidate_id: str
    task_name: str
    teacher_model: str
    student_model: str
    monthly_calls: int
    current_cost_usd: float
    distilled_cost_usd: float
    monthly_savings_usd: float
    accuracy_score: float
    status: str = "ready"


class DistillTriggerRequest(BaseModel):
    candidate_id: str
    target_student_model: Optional[str] = "qwen2.5-coder"


class CostMetricsResponse(BaseModel):
    total_cost_usd: float
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    month_spend_usd: float = 0.0
    day_spend_usd: float = 0.0
    cache_hit_rate: float = 0.0
    tier_split: Optional[TierSplitInfo] = None
    cost_per_task: List[Dict[str, Any]] = []
    breakdown: List[Dict[str, Any]]
    alerts: List[Dict[str, Any]] = []


class CostRecordRequest(BaseModel):
    agent_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Optional[float] = None
    task_id: Optional[str] = None
    success: bool = True
    project: str = "default"


class BudgetConfigRequest(BaseModel):
    monthly_budget_usd: float
    daily_budget_usd: float
    warning_threshold_pct: float = 80.0
    critical_threshold_pct: float = 100.0
    project: str = "default"


class BudgetConfigResponse(BaseModel):
    monthly_budget_usd: float
    daily_budget_usd: float
    warning_threshold_pct: float
    critical_threshold_pct: float
    project: str
    alerts: List[Dict[str, Any]] = []


class AuthSession(BaseModel):
    user_id: str
    email: Optional[str] = None
    role: str
    tenant_id: Optional[str] = None


class ToolCallInfo(BaseModel):
    call_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    status: str = "success"
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class ParticipantInfo(BaseModel):
    agent_id: str
    agent_name: str
    role: str = "assistant"
    model: Optional[str] = None
    joined_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnifiedMessageInfo(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    sender_id: str
    sender_name: Optional[str] = None
    agent_id: Optional[str] = None
    model: Optional[str] = None
    timestamp: str
    tokens: Optional[Dict[str, int]] = None
    cost_usd: Optional[float] = None
    tool_calls: List[ToolCallInfo] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnifiedSessionInfo(BaseModel):
    session_id: str
    title: str
    user_id: str
    tenant_id: str
    channel: str
    status: str
    parent_session_id: Optional[str] = None
    fork_point_message_id: Optional[str] = None
    created_at: str
    updated_at: str
    summary: Optional[str] = None
    participants: List[ParticipantInfo] = Field(default_factory=list)
    messages: List[UnifiedMessageInfo] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    total_messages: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: str = "Untitled Session"
    user_id: str = "default_user"
    tenant_id: str = "default"
    channel: str = "web"
    status: str = "active"
    metadata: Optional[Dict[str, Any]] = None
    participants: Optional[List[ParticipantInfo]] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AppendMessageRequest(BaseModel):
    role: str = "user"
    content: str = ""
    sender_id: str = "user"
    sender_name: Optional[str] = None
    agent_id: Optional[str] = None
    model: Optional[str] = None
    tokens: Optional[Dict[str, int]] = None
    cost_usd: Optional[float] = None
    tool_calls: Optional[List[ToolCallInfo]] = None
    metadata: Optional[Dict[str, Any]] = None


class ForkSessionRequest(BaseModel):
    fork_point_message_id: Optional[str] = None
    new_title: Optional[str] = None
    user_id: Optional[str] = None
    new_session_id: Optional[str] = None


class SessionExportResponse(BaseModel):
    session_id: str
    format: str
    content: str


class SessionImportRequest(BaseModel):
    format: str = "json"
    payload: Any


class SessionSearchResult(BaseModel):
    session_id: str
    title: str
    channel: str
    matched_snippets: List[Dict[str, Any]] = Field(default_factory=list)
    total_messages: int
    updated_at: str


class CacheLookupRequest(BaseModel):
    query: str
    namespace: Optional[str] = "default"
    task_type: Optional[str] = None
    min_similarity: Optional[float] = 0.95


class CacheLookupResponse(BaseModel):
    hit: bool
    similarity: float
    match_type: str
    latency_ms: float
    query: str
    cached_response: Optional[Any] = None
    entry_id: Optional[str] = None
    task_type: Optional[str] = None
    created_at: Optional[float] = None
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0


class CacheStoreRequest(BaseModel):
    query: str
    response: Any
    task_type: Optional[str] = "qa"
    ttl_seconds: Optional[int] = None
    namespace: Optional[str] = "default"
    tokens_saved: Optional[int] = 0
    cost_saved_usd: Optional[float] = 0.0
    metadata: Optional[Dict[str, Any]] = None


class CacheStoreResponse(BaseModel):
    entry_id: str
    stored: bool
    ttl_seconds: int
    task_type: str
    namespace: str


class CacheStatsResponse(BaseModel):
    total_lookups: int
    hits: int
    misses: int
    hit_rate: float
    total_entries: int
    tokens_saved: int
    cost_saved_usd: float


class CacheClearRequest(BaseModel):
    namespace: Optional[str] = None
    prune_only: Optional[bool] = False


class CacheClearResponse(BaseModel):
    cleared: bool
    pruned_entries: int = 0
    message: str = ""


class ContextBuildRequest(BaseModel):
    required_fields: List[str]
    available_data: Dict[str, Any]
    optional_fields: Optional[List[str]] = Field(default_factory=list)
    max_tokens: Optional[int] = 4000
    hard_ceiling_tokens: Optional[int] = 32000
    allow_retrieval: Optional[bool] = False
    retrieval_budget_tokens: Optional[int] = 2000
    truncation_strategy: Optional[str] = "priority"
    field_priorities: Optional[Dict[str, int]] = Field(default_factory=dict)
    system_prompt: Optional[str] = None
    strict_required: Optional[bool] = True


class ContextBuildResponse(BaseModel):
    data: Dict[str, Any]
    estimated_tokens: int
    original_tokens: int
    was_truncated: bool
    truncated_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EvalRunRequest(BaseModel):
    model_names: List[str]
    task_type: Optional[str] = "classification"
    custom_samples: Optional[List[Dict[str, Any]]] = None
    record_benchmark: Optional[bool] = True


class EvalRunResponse(BaseModel):
    task_type: str
    reports: List[Dict[str, Any]]
    ranking: Dict[str, Any]


class EvalRankingResponse(BaseModel):
    task_type: str
    ranked_models: List[Dict[str, Any]]
    recommended_model: Optional[str] = None
    frontier_baseline: Optional[str] = None
    savings_pct_vs_frontier: float = 0.0


class EvalBenchmarksResponse(BaseModel):
    benchmarks: List[Dict[str, Any]]
    total_count: int


class StepProfileSchema(BaseModel):
    step_name: str
    is_deterministic: Optional[bool] = False
    is_cacheable: Optional[bool] = False
    requires_judgment: Optional[bool] = False
    complexity: Optional[str] = "low"
    is_high_stakes: Optional[bool] = False
    fallback_tier: Optional[str] = "mid_model"
    description: Optional[str] = ""
    task_type: Optional[str] = None
    cache_namespace: Optional[str] = "default"


class RouteStepRequest(BaseModel):
    step: StepProfileSchema
    inputs: Optional[Dict[str, Any]] = Field(default_factory=dict)


class RouteStepResponse(BaseModel):
    step_name: str
    tier: str
    resolved_model: Optional[str] = None
    rationale: str
    is_free_tier: bool


class AuditPipelineRequest(BaseModel):
    steps: List[StepProfileSchema]


class AuditPipelineResponse(BaseModel):
    total_steps: int
    deterministic_or_small_count: int
    mid_tier_count: int
    frontier_count: int
    human_count: int
    deterministic_or_small_pct: float
    mid_tier_pct: float
    frontier_pct: float
    complies_with_law_1: bool
    violations: List[str] = Field(default_factory=list)


class RouterTiersResponse(BaseModel):
    tiers: Dict[str, List[str]]
    law_1_guidelines: Dict[str, str]


class RegistryPackage(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    author: str = "Agent Engine"


class FeatureFlagsResponse(BaseModel):
    flags: Dict[str, Any]


class FlagOverrideRequest(BaseModel):
    value: Any


class PipelineInfo(BaseModel):
    name: str
    description: str
    inputs: List[str]
    outputs: List[str]
    tools: List[str] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)
    category: str = "general"
    version: str = "1.0.0"
    author: str = "Agent Engine"


class PipelineRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[str] = None
    session_id: Optional[str] = None


class PipelineRunResponse(BaseModel):
    pipeline: str
    outputs: Dict[str, Any]
    execution_id: Optional[str] = None


class SafetyEvaluationRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    allow_high_risk: bool = False
    auto_apply: bool = False


class SafetyPolicyRuleInfo(BaseModel):
    id: str
    name: str
    description: str
    match_type: str
    pattern: str
    action: str
    risk_level: str
    reason: Optional[str] = None
    suggestion: Optional[str] = None


class SafetyEvaluationResponse(BaseModel):
    decision: str
    risk_score: float
    risk_level: str
    violating_rules: List[SafetyPolicyRuleInfo] = Field(default_factory=list)
    suggestion: Optional[str] = None
    reason: Optional[str] = None
    audit_id: Optional[int] = None
    operation_id: Optional[str] = None


class PendingOperationInfo(BaseModel):
    operation_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    args_hash: str
    risk_level: str
    risk_score: float
    status: str
    created_at: float
    expires_at: float
    session_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    diff: Optional[Dict[str, Any]] = None
    approval_token: Optional[str] = None
    actor: Optional[str] = None
    decision_reason: Optional[str] = None


class RegisterOperationRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]
    risk_level: Optional[str] = "high"
    risk_score: Optional[float] = 0.85
    session_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    diff: Optional[Dict[str, Any]] = None
    ttl_seconds: Optional[float] = 60.0


class ApproveOperationRequest(BaseModel):
    actor: Optional[str] = "operator"
    modified_args: Optional[Dict[str, Any]] = None


class RejectOperationRequest(BaseModel):
    actor: Optional[str] = "operator"
    reason: Optional[str] = "Rejected by operator"


class BatchOperationRequest(BaseModel):
    operation_ids: List[str]
    action: str = Field(..., description="approve | reject")
    actor: Optional[str] = "operator"
    reason: Optional[str] = None


class VerifyExecutionRequest(BaseModel):
    approval_token: str
    tool_name: str
    tool_args: Dict[str, Any]


class VerifyExecutionResponse(BaseModel):
    authorized: bool
    operation_id: str
    tool_name: str
    actor: str
    message: str


class AuditLogInfo(BaseModel):
    id: int
    timestamp: str
    tool_name: str
    tool_args: Dict[str, Any]
    decision: str
    risk_level: str
    risk_score: float
    policy_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    session_id: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]
    decision: str = Field(..., description="approve | reject | edit")
    risk_level: str = "medium"
    risk_score: float = 0.5
    reason: Optional[str] = None
    modified_args: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    operator: Optional[str] = "local-operator"


class PolicyYamlResponse(BaseModel):
    yaml_content: str
    rules_count: int


class PolicyYamlUpdateRequest(BaseModel):
    yaml_content: str


class DryRunRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class PaginatedAuditLogsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AuditLogInfo]


class SetCredentialRequest(BaseModel):
    service: str = Field(
        default="agent-engine", description="Credential service namespace (e.g. agent-engine, llm)"
    )
    key: str = Field(..., description="Credential or API key identifier")
    value: str = Field(..., description="Secret plaintext value to store securely")


class CredentialInfo(BaseModel):
    service: str
    key: str
    masked_value: str
    backend: str
    updated_at: Optional[float] = None


class GetCredentialResponse(BaseModel):
    service: str
    key: str
    masked_value: str
    backend: str
    value: Optional[str] = None
    revealed: bool = False
    updated_at: Optional[float] = None


class TestCredentialRequest(BaseModel):
    provider: str = Field(
        ...,
        description="Provider name (e.g. openai, anthropic, gemini, ollama, vllm, deepseek, groq, kimi, custom)",
    )
    api_key: Optional[str] = Field(
        default=None, description="Optional API key to test directly; if omitted, uses stored key"
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional base URL for local/custom providers (e.g. http://localhost:11434)",
    )


class TestCredentialResponse(BaseModel):
    provider: str
    valid: bool
    latency_ms: float
    error: Optional[str] = None


class UpdateStatusResponse(BaseModel):
    current_version: str
    channel: str
    auto_check: bool
    last_checked_at: Optional[float] = None
    feed_url: str


class SetChannelRequest(BaseModel):
    channel: str = Field(..., description="Target update channel: stable, beta, or nightly")


class UpdateCheckRequest(BaseModel):
    channel: Optional[str] = Field(default=None, description="Optional channel override for check")


class UpdateCheckResponse(BaseModel):
    update_available: bool
    current_version: str
    latest_version: str
    channel: str
    release_notes: str = ""
    pub_date: Optional[str] = None
    download_url: Optional[str] = None
    signature: Optional[str] = None
    sha256: Optional[str] = None


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    root_path: Optional[str] = None
    instructions: Optional[str] = ""
    settings: Optional[ProjectSettings] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    root_path: Optional[str] = None
    instructions: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class CreateRoomRequest(BaseModel):
    project_id: str
    name: str
    description: str = ""
    topic: str = ""
    policy_id: Optional[str] = None
    active_adapters: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateRoomRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    topic: Optional[str] = None
    status: Optional[str] = None
    policy_id: Optional[str] = None
    active_adapters: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class AddRoomParticipantRequest(BaseModel):
    participant_id: str
    name: Optional[str] = None
    role: str = "member"
    participant_type: str = "human"
    adapter_type: Optional[str] = None
    permissions: Optional[List[str]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateRoomTaskRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    assigned_to: Optional[str] = None
    assigned_adapter: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    created_by: str = "human"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateRoomTaskRequest(BaseModel):
    status: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    updated_by: Optional[str] = None


class ClaimRoomTaskRequest(BaseModel):
    participant_id: str
    adapter_type: Optional[str] = None


class CancelExecutionRequest(BaseModel):
    reason: Optional[str] = "user_request"
    actor: Optional[str] = "user"


class FeaturedCaseInfo(BaseModel):
    id: str
    title: str
    category: str
    description: str
    mode: str
    icon_name: str = "sparkles"
    est_cost: str = "$0.0010"
    tags: List[str] = Field(default_factory=list)
    prompt: str
    expected_tools: List[str] = Field(default_factory=list)
    sample_output: str


class ModeCasesInfo(BaseModel):
    mode: str
    title: str
    tagline: str
    badge: str
    pipeline: str
    categories: List[str] = Field(default_factory=list)
    cases: List[FeaturedCaseInfo] = Field(default_factory=list)


class AdapterRunPayload(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout_seconds: float = 60.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VerifyProviderRequest(BaseModel):
    """Request payload for verifying a provider connection."""

    model_id: Optional[str] = None
    timeout: float = 5.0


class ProviderConnectionVerificationResponse(BaseModel):
    """Standardized sanitized response for provider connection verification (Task R3.11)."""

    provider_id: str
    model_identity: Optional[Dict[str, Any]] = None
    status: str
    last_verified_at: float
    latency_ms: float
    failure_class: Optional[str] = None
    sanitized_error: Optional[str] = None
    verification_version: str = "v1"
    verification_method_version: str = "v1_canary"
    probe_type: str = "real_completion_canary"
    is_fresh: bool = False
    display_state: str = "Not configured"
    details: Dict[str, Any] = Field(default_factory=dict)
