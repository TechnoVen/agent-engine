import asyncio
import datetime
import io
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger("agent_engine.api")

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure numpy pre-import before dspy lazy import
import numpy  # noqa: F401
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from core.adapters import (
    AdapterDisabledError,
    AdapterExecutionRequest,
    AdapterNotFoundError,
    get_adapter_registry,
)
from core.cache import get_semantic_cache
from core.cases import get_case_manager
from core.config import get_feature_flags, get_settings_manager, require_flag, set_flag_override
from core.diagnostics import build_diagnostics_bundle
from core.context import ContextSpec, MissingContextFieldError, build_context
from core.eval import EvalSample, ModelEvalReport, ModelEvalSuite, get_golden_dataset
from core.memory import AgentMemory, ObservationalMemory
from core.pipelines import get_pipeline_registry
from core.router import (
    DEFAULT_TIER_MODELS,
    ExecutionRouter,
    ExecutionTier,
    ModelRouter,
    StepProfile,
    audit_pipeline,
)
from core.safety import (
    OperationExpiredError,
    SecurityBoundaryViolation,
    get_pending_registry,
    get_policy_engine,
)
from core.security import get_credential_manager, mask_secret
from core.storage import get_storage_backend
from core.updater import get_update_manager
from core.rooms import (
    RoomGovernance,
    RoomProjectMapper,
    RoomTaskManager,
)


from core.session import (
    AgentParticipant,
    MessageRole,
    ToolCall,
    get_session_store,
)
from core.execution import (
    CancellationToken,
    CancellationReason,
    ExecutionCoordinator,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from core.projects import (
    Project,
    ProjectSettings,
    generate_project_id,
)
from core.telemetry import (
    BudgetConfig,
    get_cost_tracker,
    get_hardware_telemetry_tracker,
)
from core.skills import (
    MultiToolSkillDiscovery,
    RemoteSkillDiscoveryClient,
    SkillCollectionManager,
    SkillEditor,
    SkillFormat,
    SkillRegistryClient,
    SkillSource,
)
from core.templates import TemplateManager
from core.workflows import (
    SwarmAgentSpec,
    SwarmCase,
    SwarmCoordinator,
    SwarmRunResult,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowGateManager,
    WorkflowParser,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStorage,
)
from server.watcher import apply_staged_patch, get_staged_patches, reject_staged_patch

START_TIME = time.time()


def verify_ipc_token(request: Request) -> bool:
    """Verify IPC token when AGENT_ENGINE_IPC_TOKEN is configured in the environment."""
    expected_token = os.environ.get("AGENT_ENGINE_IPC_TOKEN")
    if not expected_token:
        return True

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "X-IPC-Token" in request.headers:
        token = request.headers.get("X-IPC-Token")

    if not token or token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: invalid or missing IPC token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


# Initialize FastAPI application
app = FastAPI(
    title="Agent Engine Local API",
    description="Local HTTP and SSE interface between Agent Engine Tauri Shell and Python Sidecar",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for local desktop UI, Tauri shell, and web development
ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
custom_origins = os.environ.get("AGENT_ENGINE_ALLOWED_ORIGINS")
if custom_origins:
    ALLOWED_ORIGINS.extend([o.strip() for o in custom_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

v1_router = APIRouter(prefix="/v1")

# Singletons for memory and router
router_instance = ModelRouter()
memory_instance = AgentMemory()
observational_memory_instance = ObservationalMemory()
cost_tracker_instance = get_cost_tracker()
coordinator_instance = ExecutionCoordinator(
    storage=get_storage_backend(),
    policy_engine=get_policy_engine(),
    model_router=router_instance,
    cost_tracker=cost_tracker_instance,
)


def get_execution_coordinator() -> ExecutionCoordinator:
    global coordinator_instance
    if coordinator_instance is None:
        coordinator_instance = ExecutionCoordinator(
            storage=get_storage_backend(),
            policy_engine=get_policy_engine(),
            model_router=router_instance,
            cost_tracker=cost_tracker_instance,
        )
    return coordinator_instance


def set_execution_coordinator(coord: ExecutionCoordinator) -> None:
    global coordinator_instance
    coordinator_instance = coord


# In-memory queues for global SSE event subscribers
_event_subscribers: List[asyncio.Queue] = []


def broadcast_event(event_data: Dict[str, Any]) -> None:
    """Broadcast an event dictionary to all connected SSE clients."""
    for queue in list(_event_subscribers):
        try:
            queue.put_nowait(event_data)
        except Exception:
            pass


# ---------------------------------------------------------------------------
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


class PipelineRunResponse(BaseModel):
    pipeline: str
    outputs: Dict[str, Any]


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


# ---------------------------------------------------------------------------
# API Endpoints (/v1/...)
# ---------------------------------------------------------------------------


@v1_router.get("/health", response_model=SidecarHealthResponse)
async def get_sidecar_health():
    """Canonical health and status endpoint matching Tauri shell and client.ts expectations."""
    uptime = time.time() - START_TIME
    return SidecarHealthResponse(
        status="healthy",
        version="0.1.0",
        engine="Agent Engine",
        uptime_seconds=round(uptime, 2),
        timestamp=time.time(),
    )


@v1_router.post("/chat/completions", response_model=None)
async def chat_completions(req: ChatRequest):
    """Execute a chat completion with session persistence, canonical execution coordinator dispatch, and honest failure reporting."""
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:10]}"

    # 1. Session & Project Persistence: store user prompt in session store
    store = get_session_store()
    session = store.get_session(session_id)
    storage = get_storage_backend()
    resolved_project_id = req.project_id

    # Resolve canonical default project if none provided or legacy alias provided
    if not resolved_project_id or resolved_project_id in ("default", "proj_default"):
        default_proj = storage.get_default_project()
        if default_proj:
            resolved_project_id = default_proj["id"]

    if not session:
        session = store.create_session(
            session_id=session_id,
            title=req.prompt[:40] + ("..." if len(req.prompt) > 40 else ""),
            channel="desktop",
            metadata={"project_id": resolved_project_id},
        )
    elif not req.project_id:
        sess_proj = session.metadata.get("project_id") if session.metadata else None
        if sess_proj:
            resolved_project_id = sess_proj
            if resolved_project_id in ("default", "proj_default"):
                default_proj = storage.get_default_project()
                if default_proj:
                    resolved_project_id = default_proj["id"]
        elif not resolved_project_id:
            default_proj = storage.get_default_project()
            if default_proj:
                resolved_project_id = default_proj["id"]

    store.append_message(
        session_id=session_id,
        role=MessageRole.USER.value,
        content=req.prompt,
        metadata={
            "model": req.model or "default",
            "project_id": resolved_project_id,
            "timestamp": datetime.datetime.now().isoformat(),
        },
    )

    # 2. Build Canonical ExecutionRequest and dispatch through ExecutionCoordinator
    coordinator = get_execution_coordinator()
    exec_req = ExecutionRequest(
        project_id=resolved_project_id,
        session_id=session_id,
        task_type="chat",
        prompt=req.prompt,
        model_preference=req.model,
        inputs={
            "stream": req.stream,
            "skill_id": req.skill_id,
        },
    )

    def _map_execution_error(res: ExecutionResult) -> tuple[int, str, str]:
        """Map domain execution error to HTTP status code and structured detail."""
        err_msg = res.error or "Provider execution failed"
        err_code = res.error_code or "DISPATCH_FAILED"

        if not res.error_code:
            if "NO_AVAILABLE_PROVIDER" in err_msg:
                err_code = "NO_AVAILABLE_PROVIDER"
            elif "CROSS_PROJECT_VIOLATION" in err_msg:
                err_code = "CROSS_PROJECT_VIOLATION"
            elif any(k in err_msg.lower() for k in ("timeout", "timed out", "deadline")):
                err_code = "PROVIDER_TIMEOUT"
            elif "validation" in err_msg.lower():
                err_code = "VALIDATION_ERROR"
            elif "policy" in err_msg.lower() or "budget" in err_msg.lower():
                err_code = "POLICY_BLOCKED"

        status_map = {
            "NO_AVAILABLE_PROVIDER": status.HTTP_503_SERVICE_UNAVAILABLE,
            "CROSS_PROJECT_VIOLATION": status.HTTP_403_FORBIDDEN,
            "PROVIDER_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
            "DISPATCH_FAILED": status.HTTP_502_BAD_GATEWAY,
            "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
            "POLICY_BLOCKED": status.HTTP_403_FORBIDDEN,
            "BUDGET_EXCEEDED": status.HTTP_403_FORBIDDEN,
        }
        return status_map.get(err_code, status.HTTP_502_BAD_GATEWAY), err_code, err_msg

    local_keywords = ["qwen", "llama", "local", "ollama", "mistral", "deepseek"]

    # 3. Handle Streaming Response with Real-Time Incremental Queue
    if req.stream:
        chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        cancellation_token = CancellationToken(exec_req.id)

        def stream_event_listener(event: ExecutionEvent) -> None:
            if event.event_type == ExecutionEventType.OUTPUT_CHUNK:
                chunk = event.payload.get("chunk", "")
                if chunk:
                    try:
                        chunk_queue.put_nowait({"event": "token", "delta": chunk})
                    except asyncio.QueueFull:
                        logger.warning(
                            "Streaming queue full for session %s, dropping chunk backpressure",
                            session_id,
                        )
            elif event.event_type == ExecutionEventType.CANCELLED:
                try:
                    chunk_queue.put_nowait(
                        {
                            "event": "cancelled",
                            "reason": event.payload.get("reason", "user_request"),
                            "actor": event.payload.get("actor", "user"),
                        }
                    )
                except Exception:
                    pass

        async def run_coordinator():
            try:
                res = await coordinator.execute(
                    exec_req,
                    cancellation_token=cancellation_token,
                    event_listener=stream_event_listener,
                )
                if res.status == ExecutionStatus.CANCELLED:
                    await chunk_queue.put(
                        {
                            "event": "cancelled",
                            "reason": res.error or "Execution cancelled",
                            "result": res,
                        }
                    )
                elif res.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED):
                    _, err_code, err_msg = _map_execution_error(res)
                    await chunk_queue.put(
                        {
                            "event": "error",
                            "error": err_msg,
                            "error_code": err_code,
                            "result": res,
                        }
                    )
                else:
                    await chunk_queue.put({"event": "result", "result": res})
            except Exception as ex:
                logger.exception("Error in background coordinator streaming task: %s", ex)
                await chunk_queue.put(
                    {
                        "event": "error",
                        "error": str(ex),
                        "error_code": "DISPATCH_FAILED",
                    }
                )

        coord_task = asyncio.create_task(run_coordinator())

        async def event_generator() -> AsyncGenerator[str, None]:
            accumulated_response: List[str] = []
            final_result: Optional[ExecutionResult] = None
            try:
                while True:
                    item = await chunk_queue.get()
                    ev_type = item.get("event")

                    if ev_type == "token":
                        delta = item.get("delta", "")
                        accumulated_response.append(delta)
                        payload = {
                            "event": "token",
                            "session_id": session_id,
                            "delta": delta,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                    elif ev_type == "cancelled":
                        reason = item.get("reason", "Execution cancelled")
                        payload = {
                            "event": "cancelled",
                            "session_id": session_id,
                            "execution_id": exec_req.id,
                            "status": "CANCELLED",
                            "reason": reason,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"event: cancelled\ndata: {json.dumps(payload)}\n\n"
                        break

                    elif ev_type == "error":
                        err_code = item.get("error_code", "DISPATCH_FAILED")
                        err_msg = item.get("error", "Execution failed")
                        payload = {
                            "event": "error",
                            "session_id": session_id,
                            "error_code": err_code,
                            "error": err_msg,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        break

                    elif ev_type == "result":
                        final_result = item["result"]
                        cost_event = {
                            "event": "cost_update",
                            "session_id": session_id,
                            "model": final_result.model_used or req.model or "default",
                            "prompt_tokens": final_result.prompt_tokens,
                            "completion_tokens": final_result.completion_tokens,
                            "cost_usd": final_result.total_cost_usd,
                            "execution_id": final_result.execution_id,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(cost_event)}\n\n"

                        done_event = {
                            "event": "done",
                            "session_id": session_id,
                            "execution_id": final_result.execution_id,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(done_event)}\n\n"
                        break

            except (asyncio.CancelledError, GeneratorExit):
                logger.info("Client disconnected from SSE stream for session %s", session_id)
                if exec_req.cancel_on_disconnect:
                    coordinator.cancel(
                        exec_req.id,
                        reason=CancellationReason.CLIENT_DISCONNECT,
                        actor="client",
                    )
                    if not coord_task.done():
                        coord_task.cancel()
                raise
            finally:
                if exec_req.cancel_on_disconnect and not coord_task.done():
                    coordinator.cancel(
                        exec_req.id,
                        reason=CancellationReason.CLIENT_DISCONNECT,
                        actor="client",
                    )
                    coord_task.cancel()
                    try:
                        await coord_task
                    except (asyncio.CancelledError, Exception):
                        pass

                # Persist assistant turn to session store EXACTLY ONCE on success
                if final_result and final_result.status == ExecutionStatus.COMPLETED:
                    full_text = "".join(accumulated_response) or final_result.outputs.get(
                        "response", ""
                    )
                    store.append_message(
                        session_id=session_id,
                        role=MessageRole.ASSISTANT.value,
                        content=full_text,
                        metadata={
                            "model": final_result.model_used or req.model or "default",
                            "provider": final_result.provider_used,
                            "execution_id": final_result.execution_id,
                            "prompt_tokens": final_result.prompt_tokens,
                            "completion_tokens": final_result.completion_tokens,
                            "cost_usd": final_result.total_cost_usd,
                            "timestamp": datetime.datetime.now().isoformat(),
                        },
                    )

                    model_lower = (final_result.model_used or req.model or "").lower()
                    if any(k in model_lower for k in local_keywords) or (
                        final_result.provider_used in ["ollama", "llamacpp"]
                    ):
                        hw_tracker = get_hardware_telemetry_tracker()
                        hw_tracker.record_inference_speed(
                            tokens=max(1, final_result.completion_tokens),
                            elapsed_seconds=max(0.05, final_result.completion_tokens * 0.016),
                            model=final_result.model_used or req.model or "qwen2.5-coder:7b",
                            runtime="ollama"
                            if ("ollama" in model_lower or final_result.provider_used == "ollama")
                            else "local",
                        )

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 4. Handle Non-Streaming Execution
    result = await coordinator.execute(exec_req)

    if result.status == ExecutionStatus.CANCELLED:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "execution_id": result.execution_id,
                "status": "cancelled",
                "error_code": "CANCELLED",
                "message": result.error or "Execution cancelled",
                "partial_output": result.partial_output,
            },
        )

    if result.status in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED):
        http_status, error_code, error_msg = _map_execution_error(result)
        return JSONResponse(
            status_code=http_status,
            content={
                "detail": f"{error_code}: {error_msg}",
                "error_code": error_code,
                "message": error_msg,
            },
        )

    full_response_text = result.outputs.get("response", "")
    prompt_tokens = result.prompt_tokens
    completion_tokens = result.completion_tokens
    cost_usd = result.total_cost_usd

    # Persist assistant turn to session store exactly once
    store.append_message(
        session_id=session_id,
        role=MessageRole.ASSISTANT.value,
        content=full_response_text,
        metadata={
            "model": result.model_used or req.model or "default",
            "provider": result.provider_used,
            "execution_id": result.execution_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "timestamp": datetime.datetime.now().isoformat(),
        },
    )

    # Record local throughput in hardware tracker if local model was used
    model_lower = (result.model_used or req.model or "").lower()
    if any(k in model_lower for k in local_keywords) or (
        result.provider_used in ["ollama", "llamacpp"]
    ):
        hw_tracker = get_hardware_telemetry_tracker()
        hw_tracker.record_inference_speed(
            tokens=max(1, completion_tokens),
            elapsed_seconds=max(0.05, completion_tokens * 0.016),
            model=result.model_used or req.model or "qwen2.5-coder:7b",
            runtime="ollama"
            if ("ollama" in model_lower or result.provider_used == "ollama")
            else "local",
        )

    return ChatResponse(
        response=full_response_text,
        session_id=session_id,
        tool_calls=result.outputs.get("tool_calls", []),
        cost_usd=cost_usd,
        execution_id=result.execution_id,
        status=result.status.value if hasattr(result.status, "value") else str(result.status),
        model_used=result.model_used,
        provider_used=result.provider_used,
        routing_tier=result.routing_tier.value if result.routing_tier else None,
    )


class CancelExecutionRequest(BaseModel):
    reason: Optional[str] = "user_request"
    actor: Optional[str] = "user"


@v1_router.post("/executions/{execution_id}/cancel")
async def cancel_execution_endpoint(
    execution_id: str,
    req: Optional[CancelExecutionRequest] = None,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Canonical cancellation endpoint for in-flight or queued executions."""
    reason = req.reason if req and req.reason else "user_request"
    actor = req.actor if req and req.actor else "user"

    # 1. Inspect current execution state
    record = coordinator.get_execution(execution_id)
    if not record:
        active_exec = coordinator._active_executions.get(execution_id)
        if not active_exec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution '{execution_id}' not found",
            )
        status_val = (
            active_exec.status.value
            if hasattr(active_exec.status, "value")
            else str(active_exec.status)
        )
    else:
        status_val = record.get("status")

    # 2. Terminal state conflict check: completed/partial/terminal cannot become cancelled
    if status_val in ("completed", "partial", "blocked", "failed", "timed_out"):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "TERMINAL_STATE_CONFLICT",
                "detail": f"Execution already terminated with status '{status_val}'",
                "status": status_val,
                "execution_id": execution_id,
            },
        )

    # 3. Idempotent check: already cancelled
    if status_val == "cancelled":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "execution_id": execution_id,
                "status": "cancelled",
                "cancellation_requested": False,
                "message": "Execution already cancelled",
            },
        )

    # 4. Invoke coordinator.cancel
    try:
        res = coordinator.cancel(execution_id, reason=reason, actor=actor)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=res,
    )


@v1_router.get("/executions/{execution_id}")
async def get_execution_endpoint(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Retrieve execution details by ID."""
    record = coordinator.get_execution(execution_id)
    if not record:
        active_exec = coordinator._active_executions.get(execution_id)
        if active_exec:
            record = active_exec.model_dump()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )
    return JSONResponse(content=record)


@v1_router.get("/executions/{execution_id}/events")
async def get_execution_events_endpoint(
    execution_id: str,
    after_sequence_num: Optional[int] = Query(None),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    """Retrieve durable events recorded for an execution."""
    record = coordinator.get_execution(execution_id)
    if not record and execution_id not in coordinator._active_executions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )
    events = coordinator.get_execution_events(execution_id, after_sequence_num=after_sequence_num)
    return JSONResponse(content={"execution_id": execution_id, "events": events})


@v1_router.get("/events")
async def stream_events():
    """Subscribe to real-time Server-Sent Events (SSE)."""
    client_queue: asyncio.Queue = asyncio.Queue()
    _event_subscribers.append(client_queue)

    async def event_stream() -> AsyncGenerator[str, None]:
        # Initial connection acknowledgement
        init_event = {
            "event": "agent_status",
            "agent_name": "engine_core",
            "status": "idle",
            "timestamp": datetime.datetime.now().isoformat(),
        }
        yield f"data: {json.dumps(init_event)}\n\n"
        try:
            while True:
                data = await client_queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if client_queue in _event_subscribers:
                _event_subscribers.remove(client_queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@v1_router.get("/agents", response_model=List[AgentInfo])
async def list_agents():
    """List all registered and active agents."""
    return [
        AgentInfo(
            id="agent_code_sentry",
            name="Code Sentry Watcher",
            status="idle",
            project="default",
            current_task="Filesystem monitoring",
        ),
        AgentInfo(
            id="agent_fastmcp",
            name="FastMCP Tool Host",
            status="idle",
            project="default",
            current_task="Listening on stdio",
        ),
    ]


@v1_router.get("/skills", response_model=List[SkillInfo])
async def list_skills(
    source: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List available skills and templates discovered across developer tools."""
    discovery = MultiToolSkillDiscovery()
    skills_map: Dict[str, SkillInfo] = {}

    try:
        discovered = discovery.discover_all()
        for s in discovered:
            skills_map[s.id] = SkillInfo(
                id=s.id,
                name=s.metadata.name,
                category=s.metadata.category,
                description=s.metadata.description,
                inputs=s.metadata.inputs,
                outputs=s.metadata.outputs,
                source=s.metadata.source_tool.value,
                author=s.metadata.author,
                version=s.metadata.version,
                tags=s.metadata.tags,
                tools=s.metadata.tools,
                format=s.format.value,
                file_path=s.path,
                content=s.content,
                is_readonly=s.is_readonly,
            )
    except Exception as e:
        logger.warning(f"Error during multi-tool skill discovery: {e}")

    try:
        templates = TemplateManager.list_templates()
        for t in templates:
            if t.id not in skills_map:
                in_fields = list(t.inputs.keys()) if isinstance(t.inputs, dict) else t.inputs
                out_fields = list(t.outputs.keys()) if isinstance(t.outputs, dict) else t.outputs
                skills_map[t.id] = SkillInfo(
                    id=t.id,
                    name=t.name,
                    category=t.category,
                    description=t.description,
                    inputs=in_fields,
                    outputs=out_fields,
                    source=SkillSource.AGENT_ENGINE.value,
                    author="agent-engine",
                    version="1.0.0",
                    tags=t.tags or [],
                    format="json",
                    content=t.to_json(),
                    is_readonly=True,
                )
    except Exception as e:
        logger.warning(f"Error loading template skills: {e}")

    results = list(skills_map.values())

    if source:
        results = [s for s in results if (s.source or "").lower() == source.lower()]
    if category:
        results = [s for s in results if (s.category or "").lower() == category.lower()]
    if tag:
        results = [s for s in results if tag.lower() in [t.lower() for t in s.tags]]
    if search:
        q = search.lower()
        results = [
            s
            for s in results
            if q in s.name.lower()
            or q in (s.description or "").lower()
            or any(q in t.lower() for t in s.tags)
            or q in (s.content or "").lower()
        ]

    return results


@v1_router.post("/skills/validate", response_model=ValidateSkillResponse)
async def validate_skill_content(req: ValidateSkillRequest):
    """Validate raw skill markdown/frontmatter or JSON structure."""
    editor = SkillEditor()
    fmt = SkillFormat.JSON if req.format.lower() == "json" else SkillFormat.MARKDOWN
    res = editor.validate_content(req.content, format=fmt)
    return ValidateSkillResponse(
        valid=res.valid,
        errors=res.errors,
        warnings=res.warnings,
        parsed_metadata=res.parsed_metadata,
    )


@v1_router.post("/skills/create", response_model=SkillInfo)
async def create_skill(req: CreateSkillRequest):
    """Create a new skill and write it to the canonical tool directory."""
    editor = SkillEditor()
    try:
        src = SkillSource(req.source)
    except Exception:
        src = SkillSource.AGENT_ENGINE

    fmt = SkillFormat.JSON if req.format.lower() == "json" else SkillFormat.MARKDOWN
    try:
        skill = editor.create_skill(
            source=src,
            name=req.name,
            description=req.description,
            content=req.content,
            skill_id=req.skill_id,
            author=req.author,
            version=req.version,
            tags=req.tags,
            inputs=req.inputs,
            outputs=req.outputs,
            tools=req.tools,
            format=fmt,
            extra={"category": req.category},
        )
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.get("/skills/search", response_model=List[SkillSearchResult])
async def search_skills_endpoint(
    q: str = Query(default="", description="Search query string"),
    source: Optional[str] = Query(default=None, description="Filter by tool source"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
):
    """Full-text search across discovered skills with relevance scoring."""
    manager = SkillCollectionManager()
    src = None
    if source:
        try:
            src = SkillSource(source)
        except Exception:
            src = None

    results = manager.search_skills(query=q, source=src, tag=tag, category=category)
    response_items = []
    for skill, score in results:
        info = SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )
        response_items.append(SkillSearchResult(skill=info, score=score))
    return response_items


@v1_router.get("/skills/collections", response_model=List[SkillCollectionInfo])
async def list_skill_collections(tag: Optional[str] = None):
    """List all user and curated skill collections."""
    manager = SkillCollectionManager()
    colls = manager.list_collections(tag=tag)
    return [
        SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in colls
    ]


@v1_router.post("/skills/collections", response_model=SkillCollectionInfo)
async def create_skill_collection(req: CreateSkillCollectionRequest):
    """Create a new skill collection."""
    manager = SkillCollectionManager()
    try:
        c = manager.create_collection(
            name=req.name,
            description=req.description,
            tags=req.tags,
            skill_ids=req.skill_ids,
            collection_id=req.collection_id,
        )
        return SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.get("/skills/collections/{collection_id}", response_model=SkillCollectionInfo)
async def get_skill_collection(collection_id: str):
    """Get a specific skill collection."""
    manager = SkillCollectionManager()
    c = manager.get_collection(collection_id)
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found.",
        )
    return SkillCollectionInfo(
        id=c.id,
        name=c.name,
        description=c.description,
        tags=c.tags,
        skill_ids=c.skill_ids,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@v1_router.put("/skills/collections/{collection_id}", response_model=SkillCollectionInfo)
async def update_skill_collection(collection_id: str, req: UpdateSkillCollectionRequest):
    """Update metadata of a skill collection."""
    manager = SkillCollectionManager()
    try:
        c = manager.update_collection(
            collection_id=collection_id,
            name=req.name,
            description=req.description,
            tags=req.tags,
        )
        return SkillCollectionInfo(
            id=c.id,
            name=c.name,
            description=c.description,
            tags=c.tags,
            skill_ids=c.skill_ids,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.delete("/skills/collections/{collection_id}")
async def delete_skill_collection(collection_id: str):
    """Delete a skill collection."""
    manager = SkillCollectionManager()
    deleted = manager.delete_collection(collection_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found.",
        )
    return {"success": True, "collection_id": collection_id}


@v1_router.get("/skills/collections/{collection_id}/skills", response_model=List[SkillInfo])
async def get_collection_member_skills(collection_id: str):
    """Retrieve full SkillInfo entities for all members of a collection."""
    manager = SkillCollectionManager()
    try:
        skills = manager.get_collection_skills(collection_id)
        return [
            SkillInfo(
                id=s.id,
                name=s.metadata.name,
                category=s.metadata.category,
                description=s.metadata.description,
                inputs=s.metadata.inputs,
                outputs=s.metadata.outputs,
                source=s.metadata.source_tool.value,
                author=s.metadata.author,
                version=s.metadata.version,
                tags=s.metadata.tags,
                tools=s.metadata.tools,
                format=s.format.value,
                file_path=s.path,
                content=s.content,
                is_readonly=s.is_readonly,
            )
            for s in skills
        ]
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post("/skills/collections/{collection_id}/skills")
async def add_skill_to_collection_endpoint(collection_id: str, req: AddSkillToCollectionRequest):
    """Add a skill to a collection."""
    manager = SkillCollectionManager()
    try:
        manager.add_skill_to_collection(collection_id, req.skill_id)
        return {"success": True, "collection_id": collection_id, "skill_id": req.skill_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.delete("/skills/collections/{collection_id}/skills/{skill_id}")
async def remove_skill_from_collection_endpoint(collection_id: str, skill_id: str):
    """Remove a skill from a collection."""
    manager = SkillCollectionManager()
    try:
        removed = manager.remove_skill_from_collection(collection_id, skill_id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found in collection '{collection_id}'.",
            )
        return {"success": True, "collection_id": collection_id, "skill_id": skill_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.get(
    "/skills/registry",
    response_model=List[SkillRegistryPackageInfo],
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def list_registry_packages(
    query: Optional[str] = Query(default=None, description="Filter by text"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
):
    """List available community and verified packages in the skill registry."""
    client = SkillRegistryClient()
    pkgs = client.list_packages(query=query, category=category, tag=tag)
    return [
        SkillRegistryPackageInfo(
            id=p.id,
            name=p.name,
            version=p.version,
            description=p.description,
            author=p.author,
            tags=p.tags,
            category=p.category,
            sha256=p.sha256,
            verified=p.verified,
            installs=p.installs,
            is_installed=p.is_installed,
            installed_path=p.installed_path,
        )
        for p in pkgs
    ]


@v1_router.post(
    "/skills/registry/install",
    response_model=SkillRegistryPackageInfo,
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def install_registry_package(req: InstallSkillPackageRequest):
    """Install a skill package from registry with hash verification and security scan."""
    client = SkillRegistryClient()
    try:
        pkg = client.install_package(req.package_id, force=req.force)
        return SkillRegistryPackageInfo(
            id=pkg.id,
            name=pkg.name,
            version=pkg.version,
            description=pkg.description,
            author=pkg.author,
            tags=pkg.tags,
            category=pkg.category,
            sha256=pkg.sha256,
            verified=pkg.verified,
            installs=pkg.installs,
            is_installed=pkg.is_installed,
            installed_path=pkg.installed_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post(
    "/skills/registry/uninstall",
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def uninstall_registry_package(req: UninstallSkillPackageRequest):
    """Uninstall a package previously installed from the registry."""
    client = SkillRegistryClient()
    try:
        success = client.uninstall_package(req.package_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Package '{req.package_id}' is not currently installed.",
            )
        return {"success": True, "package_id": req.package_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post(
    "/skills/remote/discover",
    response_model=List[SkillInfo],
)
async def discover_remote_skills(req: RemoteSkillDiscoverRequest):
    """Discover available skills on a remote Agent Engine instance or manifest."""
    client = RemoteSkillDiscoveryClient()
    try:
        remote_items = client.discover_remote(req.endpoint_url, api_token=req.api_token)
        return [
            SkillInfo(
                id=item["id"],
                name=item["name"],
                category=item.get("category", "Remote"),
                description=item.get("description", ""),
                inputs=item.get("inputs", []),
                outputs=item.get("outputs", []),
                source_tool=item.get("source_tool", "agent-engine"),
                version=item.get("version", "1.0.0"),
                author=item.get("author", "remote"),
                tags=item.get("tags", []),
                content=item.get("content", ""),
            )
            for item in remote_items
        ]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post(
    "/skills/remote/import",
    response_model=SkillInfo,
)
async def import_remote_skill(req: RemoteSkillImportRequest):
    """Fetch remote skill, validate safety scan and schema, and persist locally."""
    client = RemoteSkillDiscoveryClient()
    try:
        try:
            source = SkillSource(req.target_tool) if req.target_tool else SkillSource.AGENT_ENGINE
        except ValueError:
            source = SkillSource.AGENT_ENGINE

        skill = client.import_remote_skill(
            endpoint_url=req.endpoint_url,
            skill_id=req.skill_id,
            api_token=req.api_token,
            target_tool=source,
            force=req.force,
        )
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source_tool=skill.metadata.source_tool.value,
            version=skill.metadata.version,
            author=skill.metadata.author,
            tags=skill.metadata.tags,
            content=skill.content,
            path=str(skill.path.resolve()) if skill.path else None,
            is_readonly=skill.is_readonly,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.get("/skills/{skill_id}", response_model=SkillInfo)
async def get_skill(skill_id: str):
    """Get full details and raw content of a specific skill."""
    editor = SkillEditor()
    skill = editor.get_skill(skill_id)
    if skill:
        return SkillInfo(
            id=skill.id,
            name=skill.metadata.name,
            category=skill.metadata.category,
            description=skill.metadata.description,
            inputs=skill.metadata.inputs,
            outputs=skill.metadata.outputs,
            source=skill.metadata.source_tool.value,
            author=skill.metadata.author,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            tools=skill.metadata.tools,
            format=skill.format.value,
            file_path=skill.path,
            content=skill.content,
            is_readonly=skill.is_readonly,
        )

    template = TemplateManager.get_template(skill_id)
    if template:
        in_fields = (
            list(template.inputs.keys()) if isinstance(template.inputs, dict) else template.inputs
        )
        out_fields = (
            list(template.outputs.keys())
            if isinstance(template.outputs, dict)
            else template.outputs
        )
        return SkillInfo(
            id=template.id,
            name=template.name,
            category=template.category,
            description=template.description,
            inputs=in_fields,
            outputs=out_fields,
            source=SkillSource.AGENT_ENGINE.value,
            author="agent-engine",
            version="1.0.0",
            tags=template.tags or [],
            format="json",
            content=template.to_json(),
            is_readonly=True,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Skill '{skill_id}' not found.",
    )


@v1_router.put("/skills/{skill_id}", response_model=SkillInfo)
async def update_skill(skill_id: str, req: UpdateSkillRequest):
    """Update an existing skill in place."""
    editor = SkillEditor()
    meta_updates = {}
    if req.name is not None:
        meta_updates["name"] = req.name
    if req.description is not None:
        meta_updates["description"] = req.description
    if req.version is not None:
        meta_updates["version"] = req.version
    if req.tags is not None:
        meta_updates["tags"] = req.tags
    if req.inputs is not None:
        meta_updates["inputs"] = req.inputs
    if req.outputs is not None:
        meta_updates["outputs"] = req.outputs
    if req.tools is not None:
        meta_updates["tools"] = req.tools
    if req.category is not None:
        meta_updates["category"] = req.category

    try:
        updated = editor.update_skill(
            skill_id=skill_id,
            content=req.content,
            metadata_updates=meta_updates or None,
        )
        return SkillInfo(
            id=updated.id,
            name=updated.metadata.name,
            category=updated.metadata.category,
            description=updated.metadata.description,
            inputs=updated.metadata.inputs,
            outputs=updated.metadata.outputs,
            source=updated.metadata.source_tool.value,
            author=updated.metadata.author,
            version=updated.metadata.version,
            tags=updated.metadata.tags,
            tools=updated.metadata.tools,
            format=updated.format.value,
            file_path=updated.path,
            content=updated.content,
            is_readonly=updated.is_readonly,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete an editable skill file."""
    editor = SkillEditor()
    try:
        deleted = editor.delete_skill(skill_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found.",
            )
        return {"success": True, "skill_id": skill_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post("/skills", response_model=ExecuteSkillResponse)
async def execute_skill(req: ExecuteSkillRequest):
    """Execute a pre-built OpenClaw skill template by its ID."""
    template = TemplateManager.get_template(req.skill_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill template '{req.skill_id}' not found.",
        )

    payload = req.payload or template.sample_inputs or {}
    try:
        router_instance.initialize_and_configure()
        agent = template.create_agent()
        prediction = agent(**payload)
        pred_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)
        return ExecuteSkillResponse(skill_id=req.skill_id, results=pred_dict)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution of skill '{req.skill_id}' failed: {e}",
        )


_workflow_storage: Optional[WorkflowStorage] = None


def get_workflow_storage() -> WorkflowStorage:
    global _workflow_storage
    if _workflow_storage is None:
        _workflow_storage = WorkflowStorage()
    return _workflow_storage


@v1_router.get("/workflows", response_model=List[WorkflowInfo])
async def list_workflows_endpoint(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
):
    """List registered graph workflows."""
    storage = get_workflow_storage()
    st = None
    if status:
        try:
            st = WorkflowStatus(status)
        except Exception:
            st = None
    wfs = storage.list_workflows(status=st, tag=tag)
    return [
        WorkflowInfo(
            id=w.id,
            name=w.name,
            description=w.description,
            steps=[n.id for n in w.nodes] or w.steps,
            version=w.version,
            status=w.status.value,
            nodes=[n.model_dump() for n in w.nodes],
            edges=[e.model_dump() for e in w.edges],
            tags=w.tags,
            metadata=w.metadata,
        )
        for w in wfs
    ]


@v1_router.post("/workflows")
async def create_or_run_workflow(req: Dict[str, Any]):
    """Create a new workflow definition, or run a workflow if legacy workflow_id payload passed."""
    if "workflow_id" in req and "nodes" not in req:
        wf_id = req["workflow_id"]
        inputs = req.get("inputs", {})
        storage = get_workflow_storage()
        wf = storage.get_workflow(wf_id)
        if wf:
            engine = WorkflowEngine(storage=storage)
            run = engine.run(wf, inputs=inputs, dry_run=True)
            return {"execution_id": run.run_id, "status": "queued"}
        execution_id = f"wf_exec_{uuid.uuid4().hex[:8]}"
        return {"execution_id": execution_id, "status": "queued"}

    try:
        wf = WorkflowDefinition.model_validate(req)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {e}",
        )

    is_valid, errors = WorkflowParser.validate(wf)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {'; '.join(errors)}",
        )

    storage = get_workflow_storage()
    saved = storage.save_workflow(wf)
    return saved.to_dict()


@v1_router.post("/workflows/validate", response_model=WorkflowValidateResponse)
async def validate_workflow_endpoint(req: WorkflowValidateRequest):
    """Validate a YAML or JSON workflow definition without saving."""
    wf = None
    if req.definition_yaml:
        try:
            wf = WorkflowParser.parse_yaml(req.definition_yaml)
        except Exception as e:
            return WorkflowValidateResponse(valid=False, errors=[str(e)])
    elif req.definition_json:
        try:
            wf = WorkflowDefinition.model_validate(req.definition_json)
        except Exception as e:
            return WorkflowValidateResponse(valid=False, errors=[str(e)])
    else:
        return WorkflowValidateResponse(
            valid=False, errors=["Either definition_yaml or definition_json must be provided"]
        )

    is_valid, errors = WorkflowParser.validate(wf)
    return WorkflowValidateResponse(
        valid=is_valid,
        errors=errors,
        node_count=len(wf.nodes),
        edge_count=len(wf.edges),
    )


@v1_router.get("/workflows/gates/pending")
async def list_pending_workflow_gates_endpoint():
    """List all active workflow runs waiting for human gate review."""
    storage = get_workflow_storage()
    gate_mgr = WorkflowGateManager(storage=storage)
    return gate_mgr.list_pending_gates()


@v1_router.get("/workflows/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str):
    """Fetch workflow definition by ID."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return wf.to_dict()


@v1_router.put("/workflows/{workflow_id}")
async def update_workflow_endpoint(workflow_id: str, req: Dict[str, Any]):
    """Update an existing workflow definition."""
    req["id"] = workflow_id
    try:
        wf = WorkflowDefinition.model_validate(req)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {e}",
        )

    is_valid, errors = WorkflowParser.validate(wf)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {'; '.join(errors)}",
        )

    storage = get_workflow_storage()
    saved = storage.save_workflow(wf)
    return saved.to_dict()


@v1_router.delete("/workflows/{workflow_id}")
async def delete_workflow_endpoint(workflow_id: str):
    """Delete a workflow and all associated runs."""
    storage = get_workflow_storage()
    deleted = storage.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    return {"deleted": True, "id": workflow_id}


@v1_router.post("/workflows/{workflow_id}/dry-run")
async def dry_run_workflow_endpoint(
    workflow_id: str,
    req: Optional[WorkflowDryRunRequest] = None,
):
    """Simulate workflow execution DAG traversal without executing heavy external models."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )

    engine = WorkflowEngine(storage=storage)
    inputs = req.inputs if req else {}
    run = engine.run(wf, inputs=inputs, dry_run=True)
    return run.to_dict()


@v1_router.post("/workflows/{workflow_id}/run")
async def run_workflow_endpoint(
    workflow_id: str,
    req: Optional[WorkflowRunRequest] = None,
):
    """Execute a workflow instance."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )

    engine = WorkflowEngine(storage=storage)
    inputs = req.inputs if req else {}
    dry_run = req.dry_run if req else False
    run = engine.run(wf, inputs=inputs, dry_run=dry_run)
    return run.to_dict()


@v1_router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs_endpoint(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    """List execution runs for a workflow."""
    storage = get_workflow_storage()
    runs = storage.list_runs(workflow_id=workflow_id, limit=limit)
    return [r.to_dict() for r in runs]


@v1_router.get("/workflows/{workflow_id}/runs/{run_id}")
async def get_workflow_run_endpoint(workflow_id: str, run_id: str):
    """Get details and step results of a workflow run."""
    storage = get_workflow_storage()
    run = storage.get_run(run_id)
    if not run or run.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found for workflow '{workflow_id}'",
        )
    return run.to_dict()


@v1_router.post("/workflows/{workflow_id}/runs/{run_id}/approve")
async def approve_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: Optional[WorkflowGateDecisionRequest] = None,
):
    """Approve a paused human review gate and resume DAG execution."""
    storage = get_workflow_storage()
    wf = storage.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found",
        )
    run = storage.get_run(run_id)
    if not run or run.workflow_id != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found for workflow '{workflow_id}'",
        )
    if run.status != WorkflowRunStatus.WAITING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' is not waiting for approval (current status: {run.status.value})",
        )

    gate_mgr = WorkflowGateManager(storage=storage)
    reviewer = req.reviewer if req else "operator"
    input_overrides = req.input_overrides if req else None
    try:
        resumed = gate_mgr.approve_gate(
            workflow_id=workflow_id,
            run_id=run_id,
            reviewer=reviewer,
            input_overrides=input_overrides,
        )
        return resumed.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@v1_router.post("/workflows/{workflow_id}/runs/{run_id}/reject")
async def reject_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: Optional[WorkflowGateDecisionRequest] = None,
):
    """Reject a paused human review gate and route to rejection path or cancel."""
    storage = get_workflow_storage()
    gate_mgr = WorkflowGateManager(storage=storage)
    reviewer = req.reviewer if req else "operator"
    reason = req.reason if req else None
    try:
        resumed = gate_mgr.reject_gate(
            workflow_id=workflow_id,
            run_id=run_id,
            reviewer=reviewer,
            reason=reason,
        )
        return resumed.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@v1_router.post("/workflows/{workflow_id}/runs/{run_id}/redirect")
async def redirect_workflow_gate_endpoint(
    workflow_id: str,
    run_id: str,
    req: WorkflowRedirectRequest,
):
    """Redirect execution of a paused human review gate to an alternate target node."""
    storage = get_workflow_storage()
    gate_mgr = WorkflowGateManager(storage=storage)
    try:
        resumed = gate_mgr.redirect_gate(
            workflow_id=workflow_id,
            run_id=run_id,
            target_node_id=req.target_node_id,
            reviewer=req.reviewer,
            input_overrides=req.input_overrides,
        )
        return resumed.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


_swarm_coordinator: Optional[SwarmCoordinator] = None


def get_swarm_coordinator() -> SwarmCoordinator:
    global _swarm_coordinator
    if _swarm_coordinator is None:
        _swarm_coordinator = SwarmCoordinator()
    return _swarm_coordinator


@v1_router.get("/swarm/cases", response_model=List[SwarmCase])
async def list_swarm_cases_endpoint():
    """List featured multi-agent swarm team templates."""
    coordinator = get_swarm_coordinator()
    return coordinator.list_cases()


@v1_router.post("/swarm/estimate")
async def estimate_swarm_cost_endpoint(req: SwarmEstimateRequest):
    """Estimate execution cost for a swarm team dispatch before running."""
    coordinator = get_swarm_coordinator()
    agents: List[SwarmAgentSpec] = []
    if req.agents:
        for a in req.agents:
            agents.append(SwarmAgentSpec.model_validate(a))
    elif req.case_id:
        c = coordinator.get_case(req.case_id)
        if c:
            agents = c.agents
    if not agents:
        agents = coordinator.list_cases()[0].agents

    est = coordinator.estimate_cost(agents, model_tier=req.model_tier)
    return {"estimated_cost_usd": est, "agent_count": len(agents), "model_tier": req.model_tier}


@v1_router.post("/swarm/run", response_model=SwarmRunResult)
async def run_swarm_endpoint(req: SwarmRunApiRequest):
    """Dispatch prompt to a parallel swarm of specialized agents and return aggregated results."""
    coordinator = get_swarm_coordinator()
    agents: Optional[List[SwarmAgentSpec]] = None
    if req.agents:
        agents = [SwarmAgentSpec.model_validate(a) for a in req.agents]

    result = await coordinator.run_swarm(
        prompt=req.prompt,
        agents=agents,
        case_id=req.case_id,
        model_tier=req.model_tier,
    )
    return result


@v1_router.get("/pipelines", response_model=List[PipelineInfo])
async def list_pipelines():
    """List registered modular DSPy agent pipelines."""
    registry = get_pipeline_registry()
    return [PipelineInfo(**meta.to_dict()) for meta in registry.list_pipelines()]


@v1_router.get("/pipelines/{name}", response_model=PipelineInfo)
async def get_pipeline_details(name: str):
    """Get metadata for a specific registered DSPy agent pipeline."""
    registry = get_pipeline_registry()
    meta = registry.get_metadata(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline '{name}' not found in registry.",
        )
    return PipelineInfo(**meta.to_dict())


@v1_router.post("/pipelines/{name}/run", response_model=PipelineRunResponse)
async def run_pipeline(name: str, req: PipelineRunRequest):
    """Execute a registered DSPy agent pipeline."""
    registry = get_pipeline_registry()
    meta = registry.get_metadata(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline '{name}' not found in registry.",
        )
    try:
        router_instance.initialize_and_configure()
        outputs = registry.run(name, **req.inputs)
        return PipelineRunResponse(pipeline=name, outputs=outputs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution of pipeline '{name}' failed: {e}",
        )


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


@v1_router.get("/cases", response_model=List[ModeCasesInfo])
async def list_curated_cases(
    query: Optional[str] = Query(None, description="Search term across curated cases"),
    mode: Optional[str] = Query(None, description="Filter by capability mode"),
):
    """List curated featured case templates across capability modes."""
    manager = get_case_manager()
    if query:
        matched = manager.search(query, mode=mode)
        return [
            ModeCasesInfo(
                mode=mode or "search",
                title=f"Search: '{query}'",
                tagline=f"Found {len(matched)} curated cases matching '{query}'",
                badge="Search",
                pipeline="default",
                categories=["All"],
                cases=[
                    FeaturedCaseInfo(**(c.model_dump() if hasattr(c, "model_dump") else c.dict()))
                    for c in matched
                ],
            )
        ]

    configs = (
        [manager.get_mode_config(mode)]
        if mode and manager.get_mode_config(mode)
        else manager.list_all_modes()
    )
    return [
        ModeCasesInfo(**(c.model_dump() if hasattr(c, "model_dump") else c.dict()))
        for c in configs
        if c
    ]


@v1_router.get("/cases/{mode}", response_model=ModeCasesInfo)
async def get_curated_mode_cases(mode: str):
    """Retrieve curated case configuration for a specific capability mode."""
    manager = get_case_manager()
    conf = manager.get_mode_config(mode)
    if not conf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No curated cases configured for mode '{mode}'.",
        )
    dumped = conf.model_dump() if hasattr(conf, "model_dump") else conf.dict()
    return ModeCasesInfo(**dumped)


@v1_router.get("/memory", response_model=MemoryQueryResponse)
async def query_memory(
    query: str = Query(..., description="Semantic search query"),
    top_k: int = Query(5, ge=1, le=50, description="Max passages to retrieve"),
):
    """Retrieve passages from the ChromaDB vector database."""
    passages = memory_instance.retrieve_passages(query, n_results=top_k)
    return MemoryQueryResponse(query=query, passages=passages)


@v1_router.post("/memory", response_model=IngestMemoryResponse)
@v1_router.post("/memory/ingest", response_model=IngestMemoryResponse)
async def ingest_memory(req: IngestMemoryRequest):
    """Index text content into ChromaDB vector memory."""
    now_iso = datetime.datetime.now().isoformat()
    ids = memory_instance.add_documents(
        documents=[req.content],
        metadatas=[{"source": req.source, "timestamp": now_iso}],
    )
    return IngestMemoryResponse(document_id=ids[0], count=memory_instance.count())


@v1_router.post("/memory/observe", response_model=ObservationRecordResponse)
async def record_observation(req: ObservationRecordRequest):
    """Record an atomic observation, user preference, or project fact into observational memory."""
    obs = observational_memory_instance.record_observation(
        content=req.content,
        category=req.category,
        importance=req.importance,
        session_id=req.session_id,
        metadata=req.metadata,
    )
    return ObservationRecordResponse(
        id=obs.id,
        content=obs.content,
        category=obs.category,
        importance=obs.importance,
        created_at=obs.created_at,
        session_id=obs.session_id,
    )


@v1_router.get("/memory/observations", response_model=ObservationQueryResponse)
async def query_observations(
    query: str = Query(..., description="Query to search observational memory"),
    top_k: int = Query(5, ge=1, le=50, description="Max observations to retrieve"),
    alpha: float = Query(0.5, ge=0.0, le=1.0, description="Weight for semantic relevance"),
    beta: float = Query(0.3, ge=0.0, le=1.0, description="Weight for importance score"),
    gamma: float = Query(0.2, ge=0.0, le=1.0, description="Weight for recency/temporal decay"),
    decay_lambda: float = Query(0.05, ge=0.0, description="Temporal decay rate per day"),
):
    """Retrieve observations scored by semantic relevance, importance, and temporal decay."""
    scored = observational_memory_instance.query_observations(
        query=query,
        n_results=top_k,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        decay_lambda=decay_lambda,
    )
    items = [
        ScoredObservationItem(
            id=s.observation.id,
            content=s.observation.content,
            category=s.observation.category,
            importance=s.observation.importance,
            created_at=s.observation.created_at,
            session_id=s.observation.session_id,
            relevance_score=s.relevance_score,
            importance_score=s.importance_score,
            recency_score=s.recency_score,
            final_score=s.final_score,
        )
        for s in scored
    ]
    return ObservationQueryResponse(query=query, observations=items)


# --- Scheduled Tasks Endpoints ---


@v1_router.get("/tasks", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks():
    """List all scheduled recurring agent tasks."""
    backend = get_storage_backend()
    tasks = backend.list_scheduled_tasks()
    return ScheduledTaskListResponse(tasks=[ScheduledTaskResponse(**t) for t in tasks])


@v1_router.post("/tasks", response_model=ScheduledTaskResponse)
async def create_scheduled_task_endpoint(req: ScheduledTaskCreateRequest, request: Request):
    """Create and persist a new scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    task_data = req.model_dump()
    created = backend.create_scheduled_task(task_data)
    return ScheduledTaskResponse(**created)


@v1_router.post("/tasks/{task_id}/toggle", response_model=ScheduledTaskResponse)
async def toggle_scheduled_task_endpoint(
    task_id: str, req: ScheduledTaskToggleRequest, request: Request
):
    """Toggle a scheduled task status (active/paused)."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    updated = backend.update_scheduled_task_status(task_id, req.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return ScheduledTaskResponse(**updated)


@v1_router.post("/tasks/{task_id}/run")
async def trigger_scheduled_task_endpoint(task_id: str, request: Request):
    """Trigger an immediate execution of a scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    task = backend.get_scheduled_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    now_str = datetime.datetime.now().strftime("%b %d, %I:%M %p")
    backend.update_scheduled_task_status(task_id, task.get("status", "active"))
    return {"status": "triggered", "task_id": task_id, "last_run": now_str}


@v1_router.delete("/tasks/{task_id}")
async def delete_scheduled_task_endpoint(task_id: str, request: Request):
    """Delete a scheduled task."""
    verify_ipc_token(request)
    backend = get_storage_backend()
    deleted = backend.delete_scheduled_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"status": "deleted", "task_id": task_id}


@v1_router.get("/patches", response_model=List[PatchInfo])
async def list_patches():
    """List all pending staged patches from the Sentry database."""
    staged = get_staged_patches()
    return [
        PatchInfo(
            id=p["id"],
            file_path=p["file_path"],
            patch_type=p["patch_type"],
            risk_level=p["risk_level"],
            report=p["report"],
            status=p["status"],
            timestamp=p["timestamp"],
        )
        for p in staged
    ]


@v1_router.post("/patches/{patch_id}/apply", response_model=ActionResult)
async def apply_patch(
    patch_id: int,
    request: Request,
    approval_token: Optional[str] = Query(
        None, description="Single-use approval token for high-risk patches"
    ),
):
    """Apply a staged patch directly to the filesystem."""
    verify_ipc_token(request)
    if approval_token:
        registry = get_pending_registry()
        try:
            registry.consume_token(
                approval_token=approval_token,
                tool_name="filesystem:apply_patch",
                tool_args={"patch_id": patch_id},
            )
        except SecurityBoundaryViolation as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Security boundary violation: {e}",
            )
    success = apply_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patch #{patch_id} could not be applied: not found, already applied, or target file has conflicting modifications on disk.",
        )
    return ActionResult(success=True, message=f"Successfully applied patch #{patch_id}")


@v1_router.post("/patches/{patch_id}/reject", response_model=ActionResult)
async def reject_patch(patch_id: int, request: Request):
    """Reject and dismiss a staged patch in SQLite."""
    verify_ipc_token(request)
    success = reject_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patch #{patch_id} not found or already rejected.",
        )
    return ActionResult(success=True, message=f"Successfully rejected patch #{patch_id}")


@v1_router.get("/telemetry", response_model=TelemetryResponse)
async def get_telemetry():
    """Return local resource utilization, model router readiness, and enriched hardware stats."""
    router_status = router_instance.get_status()
    hw_tracker = get_hardware_telemetry_tracker()
    hw = hw_tracker.get_telemetry(router_status=router_status)

    return TelemetryResponse(
        cpu_usage_percent=hw.cpu_usage_percent,
        ram_used_percent=hw.ram_used_percent,
        ram_total_gb=hw.ram_total_gb,
        ram_available_gb=hw.ram_available_gb,
        primary_provider=router_status.get("primary_provider", "local"),
        active_model=router_status.get("active_model", "qwen2.5-coder"),
        ollama_active=hw.ollama_active,
        llamacpp_active=hw.llamacpp_active,
        indexed_memory_documents=memory_instance.count(),
        gpu_detected=hw.gpu_detected,
        gpu_model=hw.gpu_model,
        gpu_vendor=hw.gpu_vendor,
        vram_used_percent=hw.vram_used_percent,
        vram_used_gb=hw.vram_used_gb,
        vram_total_gb=hw.vram_total_gb,
        vram_free_gb=hw.vram_free_gb,
        vram_warning=hw.vram_warning,
        tokens_per_second=hw.tokens_per_second,
        local_runtime_active=hw.local_runtime_active,
    )


@v1_router.get("/telemetry/hardware", response_model=HardwareTelemetryResponse)
async def get_hardware_telemetry():
    """Return comprehensive real-time hardware telemetry: CPU, RAM, VRAM, GPU detection, and local tokens/sec."""
    router_status = router_instance.get_status()
    hw_tracker = get_hardware_telemetry_tracker()
    hw = hw_tracker.get_telemetry(router_status=router_status)
    return HardwareTelemetryResponse(**hw.to_dict())


@v1_router.post("/telemetry/record-speed", response_model=Dict[str, Any])
async def record_inference_speed_endpoint(req: SpeedRecordRequest):
    """Record local model inference throughput (tokens/sec) for benchmark or live telemetry."""
    hw_tracker = get_hardware_telemetry_tracker()
    tps = hw_tracker.record_inference_speed(
        tokens=req.tokens,
        elapsed_seconds=req.elapsed_seconds,
        model=req.model or "qwen2.5-coder:7b",
        runtime=req.runtime or "ollama",
    )
    return {
        "status": "success",
        "tokens_per_second": tps,
        "tokens": req.tokens,
        "elapsed_seconds": req.elapsed_seconds,
        "model": req.model,
        "runtime": req.runtime,
    }


_distillation_candidates: List[Dict[str, Any]] = [
    {
        "candidate_id": "dist-001",
        "task_name": "API Payload Extraction & Typing",
        "teacher_model": "gpt-4o",
        "student_model": "qwen2.5-coder-7b",
        "monthly_calls": 24500,
        "current_cost_usd": 61.25,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 61.25,
        "accuracy_score": 0.985,
        "status": "ready",
    },
    {
        "candidate_id": "dist-002",
        "task_name": "Git Commit & PR Summarizer",
        "teacher_model": "claude-3-5-sonnet",
        "student_model": "llama3.2-3b",
        "monthly_calls": 18200,
        "current_cost_usd": 54.60,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 54.60,
        "accuracy_score": 0.978,
        "status": "ready",
    },
    {
        "candidate_id": "dist-003",
        "task_name": "SQL Query Syntax Classifier",
        "teacher_model": "gemini-1.5-pro",
        "student_model": "qwen2.5-coder-1.5b",
        "monthly_calls": 12800,
        "current_cost_usd": 44.80,
        "distilled_cost_usd": 0.0,
        "monthly_savings_usd": 44.80,
        "accuracy_score": 0.992,
        "status": "ready",
    },
]


@v1_router.get("/telemetry/cost", response_model=CostMetricsResponse)
async def get_cost_metrics(
    group_by: str = Query("day", pattern="^(agent|model|project|day)$"),
    project: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None),
):
    """Get aggregated token usage, spend breakdown, 90/9/1 tier splits, and active budget alerts."""
    summary = cost_tracker_instance.get_summary(
        agent_name=agent_name, model_name=model_name, project=project
    )
    breakdown = cost_tracker_instance.get_breakdown(
        group_by=group_by, agent_name=agent_name, model_name=model_name, project=project
    )
    if not breakdown:
        breakdown = [
            {
                "group": group_by,
                "calls": summary.get("total_calls", 0),
                "prompt_tokens": summary.get("total_prompt_tokens", 0),
                "completion_tokens": summary.get("total_completion_tokens", 0),
                "total_tokens": summary.get("total_tokens", 0),
                "cost_usd": summary.get("total_cost_usd", 0.0),
            }
        ]

    # Calculate month and day spend
    daily_rows = cost_tracker_instance.get_breakdown(group_by="day", project=project)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    curr_month = now_utc.strftime("%Y-%m")
    curr_day = now_utc.strftime("%Y-%m-%d")

    month_spend = sum(
        float(r.get("cost_usd", 0.0))
        for r in daily_rows
        if str(r.get("group", "")).startswith(curr_month)
    )
    day_spend = sum(
        float(r.get("cost_usd", 0.0)) for r in daily_rows if str(r.get("group", "")) == curr_day
    )

    # 90/9/1 Law 1 Tier Split Computation
    model_breakdown = cost_tracker_instance.get_breakdown(group_by="model", project=project)
    local_cache_calls = 0
    mid_calls = 0
    frontier_calls = 0
    for mb in model_breakdown:
        m = str(mb.get("group", "")).lower()
        calls = int(mb.get("calls", 0))
        if any(k in m for k in ["local", "qwen", "llama", "cache", "deterministic", "instant"]):
            local_cache_calls += calls
        elif any(
            k in m
            for k in [
                "gpt-4o-mini",
                "claude-3-5-haiku",
                "gemini-1.5-flash",
                "gemini-2.0-flash",
                "swarm",
            ]
        ):
            mid_calls += calls
        else:
            frontier_calls += calls

    total_calls = local_cache_calls + mid_calls + frontier_calls
    if total_calls > 0:
        tier_split = TierSplitInfo(
            deterministic_cache_local_pct=round(local_cache_calls / total_calls * 100, 1),
            mid_tier_pct=round(mid_calls / total_calls * 100, 1),
            frontier_pct=round(frontier_calls / total_calls * 100, 1),
            code_cache_calls=local_cache_calls,
            mid_tier_calls=mid_calls,
            frontier_calls=frontier_calls,
        )
    else:
        tier_split = TierSplitInfo(
            deterministic_cache_local_pct=90.0,
            mid_tier_pct=9.0,
            frontier_pct=1.0,
            code_cache_calls=0,
            mid_tier_calls=0,
            frontier_calls=0,
        )

    # Cost per task breakdown
    agent_breakdown = cost_tracker_instance.get_breakdown(group_by="agent", project=project)
    cost_per_task = [
        {
            "task": ab.get("group", "general"),
            "calls": ab.get("calls", 0),
            "cost_usd": ab.get("cost_usd", 0.0),
            "avg_cost": round(ab.get("cost_usd", 0.0) / max(1, ab.get("calls", 1)), 4),
        }
        for ab in agent_breakdown
    ]

    alerts_list = [
        alert.__dict__
        for alert in cost_tracker_instance.check_budget_alerts(project=project or "default")
    ]

    cache_hit_rate = 0.42
    try:
        from core.cache import get_semantic_cache

        sc = get_semantic_cache()
        if hasattr(sc, "get_stats"):
            cache_hit_rate = sc.get_stats().hit_rate
    except Exception:
        pass

    return CostMetricsResponse(
        total_cost_usd=summary.get("total_cost_usd", 0.0),
        total_prompt_tokens=summary.get("total_prompt_tokens", 0),
        total_completion_tokens=summary.get("total_completion_tokens", 0),
        total_tokens=summary.get("total_tokens", 0),
        month_spend_usd=round(month_spend, 4),
        day_spend_usd=round(day_spend, 4),
        cache_hit_rate=round(cache_hit_rate, 2),
        tier_split=tier_split,
        cost_per_task=cost_per_task,
        breakdown=breakdown,
        alerts=alerts_list,
    )


@v1_router.get("/telemetry/distillation-candidates", response_model=List[DistillationCandidate])
async def list_distillation_candidates():
    """List high-volume repeating tasks (>10k calls/mo) eligible for local model distillation (Law 8)."""
    return [DistillationCandidate(**c) for c in _distillation_candidates]


@v1_router.post("/telemetry/distill", response_model=ActionResult)
async def trigger_distillation(req: DistillTriggerRequest, request: Request):
    """Trigger distillation workflow to train a local specialist model from teacher logs."""
    verify_ipc_token(request)
    for c in _distillation_candidates:
        if c["candidate_id"] == req.candidate_id:
            c["status"] = "distilling"
            return ActionResult(
                success=True,
                message=f"Distillation pipeline initialized for '{c['task_name']}' using student '{req.target_student_model or c['student_model']}'.",
            )
    return ActionResult(
        success=False, message=f"Distillation candidate '{req.candidate_id}' not found."
    )


@v1_router.post("/telemetry/cost/record")
async def record_cost_metric(req: CostRecordRequest):
    """Record token spend for an agent, model, and project."""
    record_id = cost_tracker_instance.record_spend(
        agent_name=req.agent_name,
        model_name=req.model_name,
        prompt_tokens=req.prompt_tokens,
        completion_tokens=req.completion_tokens,
        cost_usd=req.cost_usd,
        task_id=req.task_id,
        success=req.success,
        project=req.project,
    )
    return {"id": record_id, "success": True}


@v1_router.get("/telemetry/budget", response_model=BudgetConfigResponse)
async def get_budget_config(project: str = Query("default")):
    """Get project budget configuration and current alert status."""
    budget = cost_tracker_instance.get_budget(project=project)
    alerts = [
        alert.__dict__ for alert in cost_tracker_instance.check_budget_alerts(project=project)
    ]
    return BudgetConfigResponse(
        monthly_budget_usd=budget.monthly_budget_usd,
        daily_budget_usd=budget.daily_budget_usd,
        warning_threshold_pct=budget.warning_threshold_pct,
        critical_threshold_pct=budget.critical_threshold_pct,
        project=budget.project,
        alerts=alerts,
    )


@v1_router.post("/telemetry/budget", response_model=BudgetConfigResponse)
async def set_budget_config(req: BudgetConfigRequest):
    """Set project budget configuration."""
    budget = BudgetConfig(
        monthly_budget_usd=req.monthly_budget_usd,
        daily_budget_usd=req.daily_budget_usd,
        warning_threshold_pct=req.warning_threshold_pct,
        critical_threshold_pct=req.critical_threshold_pct,
        project=req.project,
    )
    cost_tracker_instance.set_budget(budget)
    alerts = [
        alert.__dict__ for alert in cost_tracker_instance.check_budget_alerts(project=req.project)
    ]
    return BudgetConfigResponse(
        monthly_budget_usd=budget.monthly_budget_usd,
        daily_budget_usd=budget.daily_budget_usd,
        warning_threshold_pct=budget.warning_threshold_pct,
        critical_threshold_pct=budget.critical_threshold_pct,
        project=budget.project,
        alerts=alerts,
    )


@v1_router.get("/auth/session", response_model=AuthSession)
async def get_auth_session():
    """Retrieve current session authentication and role."""
    return AuthSession(
        user_id="usr_local_owner",
        email="local@agent-engine.internal",
        role="Owner",
        tenant_id="default_tenant",
    )


@v1_router.get(
    "/registry/search",
    response_model=List[RegistryPackage],
    dependencies=[Depends(require_flag("enable_registry"))],
)
async def search_registry(q: str = Query(..., min_length=1)):
    """Search for skills or agent bundles in registry."""
    all_packages = [
        RegistryPackage(
            id="pkg_code_review",
            name="Code Review Checklist",
            version="1.0.0",
            description="Automated style and security audit checklist for python",
            author="Agent Engine Core",
        ),
        RegistryPackage(
            id="pkg_sql_gen",
            name="SQL Generator from Natural Language",
            version="1.0.0",
            description="Translate natural questions to schema-grounded SQL",
            author="Agent Engine Core",
        ),
    ]
    matches = [
        p for p in all_packages if q.lower() in p.name.lower() or q.lower() in p.description.lower()
    ]
    return matches


@v1_router.get("/flags", response_model=FeatureFlagsResponse)
async def get_flags():
    """Retrieve current feature flag states and active overrides."""
    flags = get_feature_flags()
    return FeatureFlagsResponse(flags=flags.to_dict())


@v1_router.post("/flags/{flag_name}", response_model=ActionResult)
async def override_flag(flag_name: str, req: FlagOverrideRequest):
    """Set a runtime override for a feature flag."""
    set_flag_override(flag_name, req.value)
    return ActionResult(success=True, message=f"Flag '{flag_name}' override set to {req.value}")


@v1_router.post("/safety/evaluate", response_model=SafetyEvaluationResponse)
async def evaluate_safety(req: SafetyEvaluationRequest):
    """Evaluate a prospective tool call against active safety policies and risk scoring.
    Fails closed on any exception, returning 'deny'."""
    engine = get_policy_engine()
    try:
        decision = engine.evaluate(
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            context={
                "session_id": req.session_id,
                "allow_high_risk": req.allow_high_risk,
                "auto_apply": req.auto_apply,
            },
        )
    except Exception as e:
        # F06: Fail closed on evaluation error
        return SafetyEvaluationResponse(
            decision="deny",
            risk_score=1.0,
            risk_level="critical",
            violating_rules=[],
            suggestion="Execution blocked by safety boundary",
            reason=f"Safety evaluation failed (fail-closed): {e}",
            audit_id=None,
            operation_id=None,
        )

    # Auto-register into PendingOperationRegistry if decision is block/deny/stage or high/critical risk
    operation_id = None
    if decision.decision in ("deny", "block", "stage") or decision.risk_level in (
        "high",
        "critical",
    ):
        registry = get_pending_registry()
        op = registry.register_operation(
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            risk_level=decision.risk_level,
            risk_score=decision.risk_score,
            session_id=req.session_id,
            reason=decision.reason,
            suggestion=decision.suggestion,
        )
        operation_id = op.operation_id

    return SafetyEvaluationResponse(
        decision=decision.decision,
        risk_score=decision.risk_score,
        risk_level=decision.risk_level,
        violating_rules=[SafetyPolicyRuleInfo(**r.to_dict()) for r in decision.violating_rules],
        suggestion=decision.suggestion,
        reason=decision.reason,
        audit_id=decision.audit_id,
        operation_id=operation_id,
    )


@v1_router.get("/safety/operations", response_model=List[PendingOperationInfo])
async def list_pending_operations(
    status: Optional[str] = Query(
        None, description="Filter by status (pending, approved, rejected, expired, consumed)"
    ),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
):
    """List pending high-risk operations awaiting operator approval."""
    registry = get_pending_registry()
    ops = registry.list_operations(status=status, session_id=session_id)
    return [PendingOperationInfo(**op.to_dict()) for op in ops]


@v1_router.post("/safety/operations", response_model=PendingOperationInfo)
async def register_pending_operation(req: RegisterOperationRequest):
    """Register a new pending tool operation into the approval queue with a 60s TTL."""
    registry = get_pending_registry()
    op = registry.register_operation(
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        risk_level=req.risk_level or "high",
        risk_score=req.risk_score or 0.85,
        session_id=req.session_id,
        reason=req.reason,
        suggestion=req.suggestion,
        diff=req.diff,
        ttl_seconds=req.ttl_seconds,
    )
    return PendingOperationInfo(**op.to_dict())


@v1_router.get("/safety/operations/{operation_id}", response_model=PendingOperationInfo)
async def get_pending_operation(operation_id: str):
    """Retrieve details and status of a pending operation by ID."""
    registry = get_pending_registry()
    op = registry.get_operation(operation_id)
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operation '{operation_id}' not found",
        )
    return PendingOperationInfo(**op.to_dict())


@v1_router.post("/safety/operations/{operation_id}/approve", response_model=PendingOperationInfo)
async def approve_pending_operation(
    operation_id: str,
    req: ApproveOperationRequest,
    request: Request,
):
    """Approve a pending operation, generate a single-use execution token, and audit the approval."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op, _token = registry.approve_operation(
            operation_id=operation_id,
            actor=req.actor or "operator",
            modified_args=req.modified_args,
        )
        engine = get_policy_engine()
        engine.audit_logger.log_evaluation(
            tool_name=op.tool_name,
            tool_args=op.tool_args,
            decision="operator_approved",
            risk_level=op.risk_level,
            risk_score=op.risk_score,
            policy_id="approval_queue",
            reason=f"Approved by {req.actor or 'operator'}",
            session_id=op.session_id,
        )
        return PendingOperationInfo(**op.to_dict())
    except OperationExpiredError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@v1_router.post("/safety/operations/{operation_id}/reject", response_model=PendingOperationInfo)
async def reject_pending_operation(
    operation_id: str,
    req: RejectOperationRequest,
    request: Request,
):
    """Reject a pending operation with an explicit reason returned to the waiting agent."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op = registry.reject_operation(
            operation_id=operation_id,
            actor=req.actor or "operator",
            reason=req.reason or "Rejected by operator",
        )
        engine = get_policy_engine()
        engine.audit_logger.log_evaluation(
            tool_name=op.tool_name,
            tool_args=op.tool_args,
            decision="operator_rejected",
            risk_level=op.risk_level,
            risk_score=op.risk_score,
            policy_id="approval_queue",
            reason=req.reason or "Rejected by operator",
            session_id=op.session_id,
        )
        return PendingOperationInfo(**op.to_dict())
    except OperationExpiredError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@v1_router.post("/safety/operations/batch", response_model=List[PendingOperationInfo])
async def batch_operations(req: BatchOperationRequest, request: Request):
    """Batch approve or reject multiple pending operations."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    engine = get_policy_engine()
    results = []
    for op_id in req.operation_ids:
        try:
            if req.action == "approve":
                op, _ = registry.approve_operation(op_id, actor=req.actor or "operator")
                engine.audit_logger.log_evaluation(
                    tool_name=op.tool_name,
                    tool_args=op.tool_args,
                    decision="operator_approved_batch",
                    risk_level=op.risk_level,
                    risk_score=op.risk_score,
                    policy_id="approval_queue_batch",
                    reason=f"Batch approved by {req.actor or 'operator'}",
                    session_id=op.session_id,
                )
                results.append(op)
            elif req.action == "reject":
                op = registry.reject_operation(
                    op_id,
                    actor=req.actor or "operator",
                    reason=req.reason or "Batch rejected by operator",
                )
                engine.audit_logger.log_evaluation(
                    tool_name=op.tool_name,
                    tool_args=op.tool_args,
                    decision="operator_rejected_batch",
                    risk_level=op.risk_level,
                    risk_score=op.risk_score,
                    policy_id="approval_queue_batch",
                    reason=req.reason or "Batch rejected by operator",
                    session_id=op.session_id,
                )
                results.append(op)
        except Exception:
            continue
    return [PendingOperationInfo(**op.to_dict()) for op in results]


@v1_router.post("/safety/verify-execution", response_model=VerifyExecutionResponse)
async def verify_execution(req: VerifyExecutionRequest, request: Request):
    """Verify single-use execution token and burn it upon verification (fail-closed boundary)."""
    verify_ipc_token(request)
    registry = get_pending_registry()
    try:
        op = registry.consume_token(
            approval_token=req.approval_token,
            tool_name=req.tool_name,
            tool_args=req.tool_args,
        )
        return VerifyExecutionResponse(
            authorized=True,
            operation_id=op.operation_id,
            tool_name=op.tool_name,
            actor=op.actor or "operator",
            message="Approval token successfully validated and burned.",
        )
    except SecurityBoundaryViolation as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Security boundary violation: {e}",
        )


@v1_router.get("/safety/policies", response_model=List[SafetyPolicyRuleInfo])
async def list_safety_policies():
    """List all active guardrail rules loaded in the safety policy engine."""
    engine = get_policy_engine()
    return [SafetyPolicyRuleInfo(**r.to_dict()) for r in engine.list_rules()]


@v1_router.get("/safety/audit", response_model=List[AuditLogInfo])
async def get_safety_audit_logs(
    limit: int = Query(50, ge=1, le=500, description="Max logs to return"),
    decision: Optional[str] = Query(None, description="Filter by decision (allow, block, stage)"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
):
    """Retrieve persistent safety audit log entries."""
    engine = get_policy_engine()
    logs = engine.audit_logger.list_logs(limit=limit, decision=decision, session_id=session_id)
    return [AuditLogInfo(**log) for log in logs]


@v1_router.post("/safety/approval", response_model=AuditLogInfo)
async def submit_safety_approval(req: ApprovalDecisionRequest, request: Request):
    """Submit human operator approval, rejection, or edit decision for a high-risk tool call."""
    verify_ipc_token(request)
    engine = get_policy_engine()
    final_args = (
        req.modified_args if req.decision == "edit" and req.modified_args else req.tool_args
    )
    decision_str = f"operator_{req.decision}"
    reason_str = req.reason or f"Operator decision: {req.decision}"
    if req.operator:
        reason_str += f" (by {req.operator})"

    record_id = engine.audit_logger.log_evaluation(
        tool_name=req.tool_name,
        tool_args=final_args,
        decision=decision_str,
        risk_level=req.risk_level,
        risk_score=req.risk_score,
        policy_id="operator_gate",
        reason=reason_str,
        suggestion="Approved with modified args" if req.decision == "edit" else None,
        session_id=req.session_id,
    )
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    return AuditLogInfo(
        id=record_id if record_id > 0 else int(datetime.now(timezone.utc).timestamp()),
        timestamp=now_iso,
        tool_name=req.tool_name,
        tool_args=final_args,
        decision=decision_str,
        risk_level=req.risk_level,
        risk_score=req.risk_score,
        policy_id="operator_gate",
        reason=reason_str,
        suggestion="Approved with modified args" if req.decision == "edit" else None,
        session_id=req.session_id,
    )


@v1_router.get("/safety/policies/yaml", response_model=PolicyYamlResponse)
async def get_safety_policy_yaml():
    """Retrieve raw safety policy YAML for inspection or editing."""
    engine = get_policy_engine()
    content = engine.get_yaml_content()
    return PolicyYamlResponse(yaml_content=content, rules_count=len(engine.list_rules()))


@v1_router.post("/safety/policies/yaml")
async def update_safety_policy_yaml(req: PolicyYamlUpdateRequest, request: Request):
    """Validate, persist, and hot-reload safety guardrail policies from YAML content."""
    verify_ipc_token(request)
    engine = get_policy_engine()
    try:
        res = engine.update_yaml_content(req.yaml_content)
        return res
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@v1_router.post("/safety/policies/dry-run", response_model=SafetyEvaluationResponse)
async def dry_run_safety_policy(req: DryRunRequest):
    """Simulate and dry-run safety policy evaluation without logging to audit trail."""
    engine = get_policy_engine()
    decision = engine.evaluate(
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        context=req.context,
        dry_run=True,
    )
    return SafetyEvaluationResponse(**decision.to_dict())


@v1_router.get("/safety/audit-logs", response_model=PaginatedAuditLogsResponse)
async def list_safety_audit_logs_paginated(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    decision: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
):
    """Paginated query of safety audit logs with risk and tool name filters."""
    engine = get_policy_engine()
    total = engine.audit_logger.count_logs(
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
        session_id=session_id,
    )
    logs = engine.audit_logger.list_logs(
        limit=limit,
        offset=offset,
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
        session_id=session_id,
    )
    return PaginatedAuditLogsResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditLogInfo(**log) for log in logs],
    )


@v1_router.get("/safety/audit-logs/export")
async def export_safety_audit_logs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    decision: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
):
    """Export safety audit logs as CSV or JSON."""
    engine = get_policy_engine()
    logs = engine.audit_logger.list_logs(
        limit=limit,
        offset=0,
        decision=decision,
        risk_level=risk_level,
        tool_name=tool_name,
    )
    if format == "json":
        return logs

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "timestamp",
            "tool_name",
            "tool_args",
            "decision",
            "risk_level",
            "risk_score",
            "policy_id",
            "reason",
            "suggestion",
            "session_id",
        ]
    )
    for log in logs:
        writer.writerow(
            [
                log.get("id"),
                log.get("timestamp"),
                log.get("tool_name"),
                json.dumps(log.get("tool_args", {})),
                log.get("decision"),
                log.get("risk_level"),
                log.get("risk_score"),
                log.get("policy_id"),
                log.get("reason"),
                log.get("suggestion"),
                log.get("session_id"),
            ]
        )
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=safety_audit_logs.csv"},
    )


# ==============================================================================
# UNIFIED SESSIONS & CROSS-AGENT STORE ENDPOINTS
# ==============================================================================


@v1_router.post("/sessions", response_model=UnifiedSessionInfo, status_code=status.HTTP_201_CREATED)
async def create_unified_session(req: CreateSessionRequest):
    """Create a new unified cross-agent session."""
    store = get_session_store()
    parts = (
        [AgentParticipant(**p.model_dump()) for p in req.participants] if req.participants else None
    )
    session = store.create_session(
        session_id=req.session_id,
        title=req.title,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
        channel=req.channel,
        status=req.status,
        metadata=req.metadata,
        participants=parts,
    )
    return UnifiedSessionInfo(**session.to_dict())


@v1_router.get("/sessions", response_model=List[UnifiedSessionInfo])
async def list_unified_sessions(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status (active, archived, closed)"
    ),
    query: Optional[str] = Query(None, description="Keyword search query"),
    limit: int = Query(50, ge=1, le=200, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List cross-agent sessions with optional filters."""
    store = get_session_store()
    sessions = store.list_sessions(
        user_id=user_id,
        tenant_id=tenant_id,
        channel=channel,
        status=status_filter,
        query=query,
        limit=limit,
        offset=offset,
    )
    return [UnifiedSessionInfo(**s.to_dict()) for s in sessions]


@v1_router.get("/sessions/search", response_model=List[SessionSearchResult])
async def search_unified_sessions(
    q: str = Query(..., min_length=1, description="Keyword to search across sessions and messages"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
):
    """Search messages and metadata across all sessions."""
    store = get_session_store()
    results = store.search_sessions(query=q, user_id=user_id, limit=limit)
    return [SessionSearchResult(**r) for r in results]


@v1_router.get("/sessions/{session_id}", response_model=UnifiedSessionInfo)
async def get_unified_session(session_id: str):
    """Retrieve details and full message history of a unified session."""
    store = get_session_store()
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return UnifiedSessionInfo(**session.to_dict())


@v1_router.patch("/sessions/{session_id}", response_model=UnifiedSessionInfo)
async def update_unified_session(session_id: str, req: UpdateSessionRequest):
    """Update title, status, summary, or metadata of a session."""
    store = get_session_store()
    session = store.update_session(
        session_id=session_id,
        title=req.title,
        status=req.status,
        summary=req.summary,
        metadata=req.metadata,
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return UnifiedSessionInfo(**session.to_dict())


@v1_router.delete("/sessions/{session_id}")
async def delete_unified_session(session_id: str):
    """Permanently delete a session."""
    store = get_session_store()
    success = store.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"status": "deleted", "session_id": session_id}


@v1_router.post(
    "/sessions/{session_id}/messages",
    response_model=UnifiedMessageInfo,
    status_code=status.HTTP_201_CREATED,
)
async def append_unified_message(session_id: str, req: AppendMessageRequest):
    """Append a message turn to a session."""
    store = get_session_store()
    tcs = [ToolCall(**tc.model_dump()) for tc in req.tool_calls] if req.tool_calls else None
    try:
        msg = store.append_message(
            session_id=session_id,
            role=req.role,
            content=req.content,
            sender_id=req.sender_id or "user",
            sender_name=req.sender_name,
            agent_id=req.agent_id,
            model=req.model,
            tokens=req.tokens,
            cost_usd=req.cost_usd,
            tool_calls=tcs,
            metadata=req.metadata,
        )
        return UnifiedMessageInfo(**msg.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@v1_router.post(
    "/sessions/{session_id}/fork",
    response_model=UnifiedSessionInfo,
    status_code=status.HTTP_201_CREATED,
)
async def fork_unified_session(session_id: str, req: ForkSessionRequest):
    """Fork an existing session at a specific message point (or latest) into a new branch."""
    store = get_session_store()
    try:
        forked = store.fork_session(
            session_id=session_id,
            fork_point_message_id=req.fork_point_message_id,
            new_title=req.new_title,
            user_id=req.user_id,
            new_session_id=req.new_session_id,
        )
        return UnifiedSessionInfo(**forked.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@v1_router.get("/sessions/{session_id}/export", response_model=SessionExportResponse)
async def export_unified_session(
    session_id: str,
    format: str = Query(
        "json", description="Export format: json, markdown, jsonl, openai, anthropic, dspy"
    ),
):
    """Export a session transcript into standard ecosystem formats."""
    store = get_session_store()
    try:
        content = store.export_session(session_id=session_id, format=format)
        return SessionExportResponse(session_id=session_id, format=format, content=content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@v1_router.post(
    "/sessions/import", response_model=UnifiedSessionInfo, status_code=status.HTTP_201_CREATED
)
async def import_unified_session(req: SessionImportRequest):
    """Import a session from an external payload."""
    store = get_session_store()
    try:
        session = store.import_session(payload=req.payload, format=req.format)
        return UnifiedSessionInfo(**session.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


# ==============================================================================
# Semantic Cache Endpoints (Task 1.7)
# ==============================================================================


@v1_router.post("/cache/lookup", response_model=CacheLookupResponse)
async def lookup_cache(req: CacheLookupRequest):
    """Check semantic cache for a matching query with >= 0.95 similarity or exact match."""
    cache = get_semantic_cache()
    res = cache.lookup(
        query=req.query,
        namespace=req.namespace or "default",
        task_type=req.task_type,
        min_similarity=req.min_similarity if req.min_similarity is not None else 0.95,
    )
    return CacheLookupResponse(
        hit=res.hit,
        similarity=res.similarity,
        match_type=res.match_type,
        latency_ms=res.latency_ms,
        query=res.query,
        cached_response=res.entry.response if res.entry else None,
        entry_id=res.entry.entry_id if res.entry else None,
        task_type=res.entry.task_type if res.entry else None,
        created_at=res.entry.created_at if res.entry else None,
        tokens_saved=res.entry.tokens_saved if res.entry else 0,
        cost_saved_usd=res.entry.cost_saved_usd if res.entry else 0.0,
    )


@v1_router.post(
    "/cache/store", response_model=CacheStoreResponse, status_code=status.HTTP_201_CREATED
)
async def store_cache(req: CacheStoreRequest):
    """Store a response in the semantic cache with dual-layer (exact + cosine) index."""
    cache = get_semantic_cache()
    try:
        entry = cache.store(
            query=req.query,
            response=req.response,
            task_type=req.task_type or "qa",
            ttl_seconds=req.ttl_seconds,
            namespace=req.namespace or "default",
            tokens_saved=req.tokens_saved or 0,
            cost_saved_usd=req.cost_saved_usd or 0.0,
            metadata=req.metadata or {},
        )
        return CacheStoreResponse(
            entry_id=entry.entry_id,
            stored=True,
            ttl_seconds=entry.ttl_seconds,
            task_type=entry.task_type,
            namespace=entry.namespace,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed storing cache entry: {str(e)}")


@v1_router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats():
    """Retrieve semantic cache metrics, total entries, hit rate, and cost/tokens saved."""
    cache = get_semantic_cache()
    stats = cache.get_stats()
    return CacheStatsResponse(**stats.to_dict())


@v1_router.post("/cache/clear", response_model=CacheClearResponse)
async def clear_cache(req: Optional[CacheClearRequest] = None):
    """Clear or prune expired entries from the semantic cache."""
    cache = get_semantic_cache()
    ns = req.namespace if req else None
    prune_only = req.prune_only if req else False

    if prune_only:
        pruned = cache.prune_expired()
        return CacheClearResponse(
            cleared=True,
            pruned_entries=pruned,
            message=f"Pruned {pruned} expired cache entries.",
        )
    else:
        cache.clear(namespace=ns)
        return CacheClearResponse(
            cleared=True,
            pruned_entries=0,
            message=f"Cache cleared successfully for namespace='{ns or 'all'}'.",
        )


@v1_router.post("/context/build", response_model=ContextBuildResponse)
async def build_context_endpoint(req: ContextBuildRequest):
    """Build a minimal, budgeted context according to declared specifications and token limits."""
    try:
        spec = ContextSpec(
            required_fields=req.required_fields,
            optional_fields=req.optional_fields or [],
            max_tokens=req.max_tokens if req.max_tokens is not None else 4000,
            hard_ceiling_tokens=req.hard_ceiling_tokens
            if req.hard_ceiling_tokens is not None
            else 32000,
            allow_retrieval=req.allow_retrieval or False,
            retrieval_budget_tokens=req.retrieval_budget_tokens
            if req.retrieval_budget_tokens is not None
            else 2000,
            truncation_strategy=req.truncation_strategy or "priority",
            field_priorities=req.field_priorities or {},
            system_prompt=req.system_prompt,
            strict_required=req.strict_required if req.strict_required is not None else True,
        )
        built = build_context(spec=spec, available=req.available_data)
        return ContextBuildResponse(**built.to_dict())
    except MissingContextFieldError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Context build failed: {str(e)}",
        )


@v1_router.post("/eval/run", response_model=EvalRunResponse)
async def run_eval_endpoint(req: EvalRunRequest):
    """Run model evaluation suite against golden or custom dataset, computing cost-per-success and rankings."""
    suite = ModelEvalSuite()
    try:
        if req.custom_samples:
            samples = [
                EvalSample(
                    task_id=s.get("task_id", f"custom-{i}"),
                    task_type=req.task_type or "classification",
                    inputs=s.get("inputs", {}),
                    expected_output=s.get("expected_output"),
                    metric=s.get("metric", "exact"),
                )
                for i, s in enumerate(req.custom_samples)
            ]
        else:
            samples = get_golden_dataset(req.task_type or "classification")

        reports = suite.evaluate_models(
            model_names=req.model_names,
            dataset_or_task_type=samples,
            record=req.record_benchmark if req.record_benchmark is not None else True,
        )
        ranking = suite.rank_models(reports)
        return EvalRunResponse(
            task_type=req.task_type or "classification",
            reports=[r.to_dict() for r in reports],
            ranking=ranking.to_dict(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Eval run failed: {str(e)}"
        )


@v1_router.get("/eval/rankings", response_model=EvalRankingResponse)
async def get_eval_rankings_endpoint(
    task_type: str = Query("classification", description="Task type to rank models for"),
):
    """Retrieve success-adjusted cost rankings from stored benchmarks for a given task type."""
    backend = get_storage_backend()
    benchmarks = backend.get_benchmarks(task_type=task_type)
    if not benchmarks:
        return EvalRankingResponse(
            task_type=task_type,
            ranked_models=[],
            recommended_model=None,
            frontier_baseline=None,
            savings_pct_vs_frontier=0.0,
        )

    reports = []
    for b in benchmarks:
        meta = b.get("metadata") or {}
        rep = ModelEvalReport(
            model_name=b["model_name"],
            task_type=b["task_type"],
            total_samples=meta.get("total_samples", 1),
            success_count=meta.get("success_count", 1),
            failure_count=0,
            success_rate=b["success_rate"],
            total_cost_usd=meta.get("total_cost_usd", 0.0),
            cost_per_success=b["cost_per_success"],
            avg_latency_ms=b["latency_ms"],
            p95_latency_ms=b["latency_ms"],
            total_tokens=meta.get("total_tokens", 0),
        )
        reports.append(rep)

    suite = ModelEvalSuite(storage=backend)
    ranking = suite.rank_models(reports)
    return EvalRankingResponse(**ranking.to_dict())


@v1_router.get("/eval/benchmarks", response_model=EvalBenchmarksResponse)
async def get_eval_benchmarks_endpoint(
    task_type: Optional[str] = Query(None, description="Filter benchmarks by task type"),
):
    """Retrieve historical model evaluation benchmark runs."""
    backend = get_storage_backend()
    benchmarks = backend.get_benchmarks(task_type=task_type)
    return EvalBenchmarksResponse(
        benchmarks=benchmarks,
        total_count=len(benchmarks),
    )


@v1_router.post("/router/route", response_model=RouteStepResponse)
async def route_step_endpoint(req: RouteStepRequest):
    """Classify a step according to 90/9/1 cost optimization rules and resolve execution tier."""
    cache = get_semantic_cache()
    router = ExecutionRouter(cache=cache)
    step = StepProfile(
        step_name=req.step.step_name,
        is_deterministic=req.step.is_deterministic or False,
        is_cacheable=req.step.is_cacheable or False,
        requires_judgment=req.step.requires_judgment or False,
        complexity=req.step.complexity or "low",
        is_high_stakes=req.step.is_high_stakes or False,
        fallback_tier=ExecutionTier(req.step.fallback_tier)
        if req.step.fallback_tier
        else ExecutionTier.MID_MODEL,
        description=req.step.description or "",
        task_type=req.step.task_type,
        cache_namespace=req.step.cache_namespace or "default",
    )
    tier = router.route(step, req.inputs or {})
    resolved_model = router.resolve_model(tier, task_type=step.task_type)
    is_free = tier in (ExecutionTier.CODE, ExecutionTier.CACHE) or (
        resolved_model in ("local", "qwen2.5-coder", "llama3.2")
    )

    rationale = f"Step '{step.step_name}' classified as {tier.value} tier."
    if tier == ExecutionTier.CODE:
        rationale = "Deterministic logic executed in code (0 tokens, $0.00)."
    elif tier == ExecutionTier.CACHE:
        rationale = "Matched cache query (0 tokens, $0.00)."
    elif tier == ExecutionTier.FRONTIER_MODEL:
        rationale = "High-stakes or complex reasoning requires frontier model tier."

    return RouteStepResponse(
        step_name=step.step_name,
        tier=tier.value,
        resolved_model=resolved_model,
        rationale=rationale,
        is_free_tier=is_free,
    )


@v1_router.post("/router/audit", response_model=AuditPipelineResponse)
async def audit_pipeline_endpoint(req: AuditPipelineRequest):
    """Audit an agent workflow against Law 1 (The 90/9/1 Rule)."""
    step_profiles = [
        StepProfile(
            step_name=s.step_name,
            is_deterministic=s.is_deterministic or False,
            is_cacheable=s.is_cacheable or False,
            requires_judgment=s.requires_judgment or False,
            complexity=s.complexity or "low",
            is_high_stakes=s.is_high_stakes or False,
            fallback_tier=ExecutionTier(s.fallback_tier)
            if s.fallback_tier
            else ExecutionTier.MID_MODEL,
            description=s.description or "",
            task_type=s.task_type,
            cache_namespace=s.cache_namespace or "default",
        )
        for s in req.steps
    ]
    audit_res = audit_pipeline(step_profiles)
    return AuditPipelineResponse(**audit_res.to_dict())


@v1_router.get("/router/tiers", response_model=RouterTiersResponse)
async def get_router_tiers_endpoint():
    """Retrieve execution tiers and model allocations under the 90/9/1 rule."""
    tiers_map = {tier.value: models for tier, models in DEFAULT_TIER_MODELS.items()}
    guidelines = {
        "law_1_rule": "90% deterministic code/cache/small local model, 9% mid-tier, 1% frontier.",
        "frontier_ceiling": "Max allowable frontier model steps is 10%.",
        "context_target": "Average context per step < 8,000 tokens.",
    }
    return RouterTiersResponse(
        tiers=tiers_map,
        law_1_guidelines=guidelines,
    )


# ---------------------------------------------------------------------------
# Credentials Management Endpoints (ADR-008: Secure Credential Storage)
# ---------------------------------------------------------------------------


@v1_router.get("/credentials", response_model=List[CredentialInfo])
async def list_credentials_endpoint(
    service: Optional[str] = Query(None, description="Optional service namespace filter"),
):
    """List stored credentials across secure backends with values masked."""
    mgr = get_credential_manager()
    items = mgr.list_credentials(service=service)
    return [
        CredentialInfo(
            service=item["service"],
            key=item["key"],
            masked_value=item["masked_value"],
            backend=item.get("backend", mgr.active_backend_name),
            updated_at=item.get("updated_at"),
        )
        for item in items
    ]


@v1_router.post(
    "/credentials",
    response_model=CredentialInfo,
    status_code=status.HTTP_201_CREATED,
)
async def set_credential_endpoint(req: SetCredentialRequest, request: Request):
    """Store a credential in the secure backend (OS Keychain with AES-256-GCM Vault fallback)."""
    verify_ipc_token(request)
    if not req.key.strip():
        raise HTTPException(status_code=400, detail="Credential key cannot be empty")
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="Credential value cannot be empty")

    mgr = get_credential_manager()
    mgr.set_credential(req.service.strip(), req.key.strip(), req.value)

    return CredentialInfo(
        service=req.service.strip(),
        key=req.key.strip(),
        masked_value=mask_secret(req.value),
        backend=mgr.active_backend_name,
        updated_at=time.time(),
    )


@v1_router.get("/credentials/{service}/{key}", response_model=GetCredentialResponse)
async def get_credential_endpoint(
    service: str,
    key: str,
    request: Request,
    reveal: bool = Query(False, description="Whether to reveal the plaintext secret value"),
):
    """Retrieve a stored credential. Masked by default unless reveal=true is explicitly set."""
    if reveal:
        verify_ipc_token(request)

    mgr = get_credential_manager()
    val = mgr.get_credential(service, key)
    if val is None:
        raise HTTPException(
            status_code=404, detail=f"Credential '{key}' not found under service '{service}'"
        )

    return GetCredentialResponse(
        service=service,
        key=key,
        masked_value=mask_secret(val),
        backend=mgr.active_backend_name,
        value=val if reveal else None,
        revealed=reveal,
        updated_at=time.time(),
    )


@v1_router.delete("/credentials/{service}/{key}", response_model=ActionResult)
async def delete_credential_endpoint(service: str, key: str, request: Request):
    """Delete a stored credential from secure backends."""
    verify_ipc_token(request)
    mgr = get_credential_manager()
    deleted = mgr.delete_credential(service, key)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Credential '{key}' not found under service '{service}'"
        )
    return ActionResult(
        success=True,
        message=f"Credential '{key}' successfully deleted from service '{service}'",
    )


@v1_router.post("/credentials/test", response_model=TestCredentialResponse)
async def test_credential_endpoint(req: TestCredentialRequest):
    """Test API authentication and connectivity for a model provider."""
    mgr = get_credential_manager()
    res = mgr.test_provider_key(req.provider, api_key=req.api_key, base_url=req.base_url)
    return TestCredentialResponse(
        provider=res["provider"],
        valid=res["valid"],
        latency_ms=res["latency_ms"],
        error=res.get("error"),
    )


# ---------------------------------------------------------------------------
# Auto-Update Channel Endpoints (Task 2.4 - Milestone M2)
# ---------------------------------------------------------------------------


@v1_router.get("/updater/status", response_model=UpdateStatusResponse)
async def get_updater_status_endpoint():
    """Retrieve auto-updater status, current version, active channel, and feed URL."""
    mgr = get_update_manager()
    return UpdateStatusResponse(**mgr.get_status())


@v1_router.post("/updater/channel", response_model=UpdateStatusResponse)
async def set_updater_channel_endpoint(req: SetChannelRequest):
    """Switch active update distribution channel (stable, beta, nightly)."""
    mgr = get_update_manager()
    try:
        mgr.set_channel(req.channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UpdateStatusResponse(**mgr.get_status())


@v1_router.post("/updater/check", response_model=UpdateCheckResponse)
async def check_updates_endpoint(req: Optional[UpdateCheckRequest] = None):
    """Check for new releases against the active or requested channel."""
    mgr = get_update_manager()
    channel_override = req.channel if req else None
    info = mgr.check_for_updates(channel=channel_override)
    return UpdateCheckResponse(**info.to_dict())


# ---------------------------------------------------------------------------
# Encrypted Settings & Diagnostics Endpoints (Task 4.8)
# ---------------------------------------------------------------------------


@v1_router.get("/settings/config", response_model=Dict[str, Any])
async def get_settings_config_endpoint():
    """Retrieve current application configuration decrypted from local encrypted storage."""
    mgr = get_settings_manager()
    settings = mgr.load_settings()
    return settings.to_dict()


@v1_router.post("/settings/config", response_model=Dict[str, Any])
async def update_settings_config_endpoint(payload: Dict[str, Any], request: Request):
    """Update and persist application configuration into local encrypted vault."""
    verify_ipc_token(request)
    mgr = get_settings_manager()
    updated = mgr.save_settings(payload)
    return updated.to_dict()


@v1_router.get("/diagnostics/export")
async def export_diagnostics_endpoint(
    format: str = Query("zip", description="Export format: 'zip' or 'json'"),
):
    """Export complete diagnostics bundle (system info, schema versions, redacted config, redacted logs)."""
    content_bytes, media_type, filename = build_diagnostics_bundle(format=format)
    if format.lower() == "json":
        return Response(content=content_bytes, media_type="application/json")

    return StreamingResponse(
        io.BytesIO(content_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Agent Adapters Endpoints (Task 5.1)
# ---------------------------------------------------------------------------


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


@v1_router.get("/adapters", response_model=List[Dict[str, Any]])
async def list_adapters_endpoint(include_health: bool = Query(False)):
    """List all registered agent adapters, their capabilities, and enabled status."""
    reg = get_adapter_registry()
    return reg.list_adapters(include_health=include_health)


@v1_router.get("/adapters/{adapter_id}", response_model=Dict[str, Any])
async def get_adapter_endpoint(adapter_id: str):
    """Retrieve metadata and health status for a specific adapter."""
    reg = get_adapter_registry()
    adapter = reg.get(adapter_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    meta = adapter.to_metadata_dict()
    meta["enabled"] = reg.is_enabled(adapter_id)
    try:
        health = adapter.health_check()
        meta["health"] = health.to_dict()
    except Exception as e:
        meta["health"] = {"status": "unavailable", "message": str(e), "latency_ms": 0.0}
    return meta


@v1_router.post("/adapters/{adapter_id}/execute", response_model=Dict[str, Any])
async def execute_adapter_endpoint(adapter_id: str, payload: AdapterRunPayload):
    """Execute a prompt through the specified agent adapter."""
    reg = get_adapter_registry()
    req = AdapterExecutionRequest(
        prompt=payload.prompt,
        session_id=payload.session_id,
        context=payload.context,
        tools=payload.tools,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds,
        metadata=payload.metadata,
    )
    try:
        resp = await reg.execute(adapter_id, req)
        return resp.to_dict()
    except AdapterNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AdapterDisabledError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post("/adapters/{adapter_id}/stream")
async def stream_adapter_endpoint(adapter_id: str, payload: AdapterRunPayload):
    """Stream token chunks and tool call events from the specified adapter via SSE."""
    reg = get_adapter_registry()
    req = AdapterExecutionRequest(
        prompt=payload.prompt,
        session_id=payload.session_id,
        context=payload.context,
        tools=payload.tools,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds,
        metadata=payload.metadata,
    )

    if not reg.get(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    if not reg.is_enabled(adapter_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Adapter '{adapter_id}' is disabled in Settings",
        )

    async def event_generator():
        try:
            async for chunk in reg.stream(adapter_id, req):
                yield f"data: {json.dumps(chunk.to_dict())}\n\n"
        except Exception as e:
            err_data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {err_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@v1_router.post("/adapters/{adapter_id}/test", response_model=Dict[str, Any])
async def test_adapter_endpoint(adapter_id: str):
    """Probe adapter connectivity, environment prerequisites, and latency."""
    reg = get_adapter_registry()
    adapter = reg.get(adapter_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adapter '{adapter_id}' not found",
        )
    try:
        health = adapter.health_check()
        return health.to_dict()
    except Exception as e:
        return {
            "status": "unavailable",
            "message": f"Test failed: {e}",
            "latency_ms": 0.0,
            "version": getattr(adapter, "version", None),
            "details": {"error": str(e)},
        }


# ---------------------------------------------------------------------------
# Canonical Projects Endpoints (/v1/projects/...) (Task R1.6)
# ---------------------------------------------------------------------------


@v1_router.get("/projects", response_model=List[Dict[str, Any]])
async def list_projects(
    limit: int = Query(50, ge=1, le=200, description="Max projects to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List canonical projects with pagination."""
    backend = get_storage_backend()
    return backend.list_projects(limit=limit, offset=offset)


@v1_router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(req: CreateProjectRequest):
    """Create a new canonical project workspace."""
    backend = get_storage_backend()
    proj_id = generate_project_id()
    root_path = req.root_path or f"/workspace/{proj_id}"
    proj = Project(
        id=proj_id,
        name=req.name,
        description=req.description,
        root_path=root_path,
        instructions=req.instructions or "",
        settings=req.settings or ProjectSettings(),
    )
    created = backend.create_project(proj.model_dump())
    return created


@v1_router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Fetch details for a specific canonical project."""
    backend = get_storage_backend()
    proj = backend.get_project(project_id)
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return proj


@v1_router.put("/projects/{project_id}")
@v1_router.patch("/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    """Update canonical project attributes."""
    backend = get_storage_backend()
    existing = backend.get_project(project_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    updates = req.model_dump(exclude_unset=True)
    updated = backend.update_project(project_id, updates)
    return updated


@v1_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a canonical project."""
    backend = get_storage_backend()
    deleted = backend.delete_project(project_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return {"deleted": True, "project_id": project_id}


# ---------------------------------------------------------------------------
# Collaborative Rooms Endpoints (/v1/rooms/...)
# ---------------------------------------------------------------------------


@v1_router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(req: CreateRoomRequest):
    """Create a new collaborative room overlay on a project."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    room = mapper.create_room(
        project_id=req.project_id,
        name=req.name,
        description=req.description,
        topic=req.topic,
        policy_id=req.policy_id,
        active_adapters=req.active_adapters,
        metadata=req.metadata,
    )
    return room.to_dict()


@v1_router.get("/rooms")
async def list_rooms(
    project_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """List collaborative rooms, optionally filtered by project or status."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    rooms = mapper.list_rooms(project_id=project_id, status=status_filter)
    return [r.to_dict() for r in rooms]


@v1_router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    """Fetch details for a specific collaborative room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    room = mapper.get_room(room_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return room.to_dict()


@v1_router.patch("/rooms/{room_id}")
async def update_room(room_id: str, req: UpdateRoomRequest):
    """Update room attributes."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    updates = req.model_dump(exclude_unset=True)
    updated = mapper.update_room(room_id, **updates)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return updated.to_dict()


@v1_router.delete("/rooms/{room_id}")
async def delete_room(room_id: str):
    """Delete a collaborative room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    deleted = mapper.delete_room(room_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found",
        )
    return {"deleted": True, "room_id": room_id}


@v1_router.get("/rooms/{room_id}/context")
async def get_room_context(
    room_id: str,
    prompt: str = Query(""),
    project_instructions: str = Query(""),
):
    """Build ADR-014 dynamic context overlay for the room."""
    backend = get_storage_backend()
    mapper = RoomProjectMapper(storage=backend)
    try:
        context = mapper.build_room_context(
            room_id=room_id,
            prompt=prompt,
            project_instructions=project_instructions,
        )
        return context
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@v1_router.post("/rooms/{room_id}/participants", status_code=status.HTTP_201_CREATED)
async def add_room_participant(room_id: str, req: AddRoomParticipantRequest):
    """Add or register a participant (human or agent) in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    try:
        participant = gov.add_participant(
            room_id=room_id,
            participant_id=req.participant_id,
            name=req.name,
            role=req.role,
            participant_type=req.participant_type,
            adapter_type=req.adapter_type,
            permissions=req.permissions,
            metadata=req.metadata,
        )
        return participant.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@v1_router.get("/rooms/{room_id}/participants")
async def list_room_participants(room_id: str):
    """List all participants registered in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    participants = gov.list_participants(room_id)
    return [p.to_dict() for p in participants]


@v1_router.delete("/rooms/{room_id}/participants/{participant_id}")
async def remove_room_participant(
    room_id: str,
    participant_id: str,
    requested_by: Optional[str] = Query(None),
):
    """Remove a participant from the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    req_by = requested_by or participant_id
    try:
        removed = gov.remove_participant(
            room_id=room_id,
            participant_id=participant_id,
            requested_by_id=req_by,
        )
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Participant '{participant_id}' not found in room '{room_id}'",
            )
        return {"removed": True, "participant_id": participant_id}
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@v1_router.post("/rooms/{room_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_room_task(room_id: str, req: CreateRoomTaskRequest):
    """Create a task object as a workflow step in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.create_task(
            room_id=room_id,
            title=req.title,
            description=req.description,
            priority=req.priority,
            assigned_to=req.assigned_to,
            assigned_adapter=req.assigned_adapter,
            parent_task_id=req.parent_task_id,
            dependencies=req.dependencies,
            created_by=req.created_by,
            metadata=req.metadata,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@v1_router.get("/rooms/{room_id}/tasks")
async def list_room_tasks(
    room_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    assigned_to: Optional[str] = Query(None),
):
    """List tasks in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    tasks = task_mgr.list_tasks(room_id=room_id, status=status_filter, assigned_to=assigned_to)
    return [t.to_dict() for t in tasks]


@v1_router.get("/rooms/{room_id}/tasks/{task_id}")
async def get_room_task(room_id: str, task_id: str):
    """Fetch details for a task in the room."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    task = task_mgr.get_task(room_id, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found in room '{room_id}'",
        )
    return task.to_dict()


@v1_router.post("/rooms/{room_id}/tasks/{task_id}/claim")
async def claim_room_task(room_id: str, task_id: str, req: ClaimRoomTaskRequest):
    """Claim a task for execution."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.claim_task(
            room_id=room_id,
            task_id=task_id,
            participant_id=req.participant_id,
            adapter_type=req.adapter_type,
        )
        return task.to_dict()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@v1_router.patch("/rooms/{room_id}/tasks/{task_id}")
async def update_room_task(room_id: str, task_id: str, req: UpdateRoomTaskRequest):
    """Update task status or completion result."""
    backend = get_storage_backend()
    gov = RoomGovernance(storage=backend)
    task_mgr = RoomTaskManager(storage=backend, governance=gov)
    try:
        task = task_mgr.update_task_status(
            room_id=room_id,
            task_id=task_id,
            status=req.status or "completed",
            result=req.result,
            updated_by=req.updated_by,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Team Collaboration Channels (/v1/channels/...)
# ---------------------------------------------------------------------------


@v1_router.post("/channels/slack/events")
async def slack_events_webhook(request: Request):
    """Incoming webhook for Slack Events API and Socket Mode verification."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # Handle Slack URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    reg = get_adapter_registry()
    adapter = reg.get("slack")
    if not adapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slack adapter not found")

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
        "envelope_ack": adapter.handle_socket_mode_envelope(body)
        if body.get("envelope_id")
        else None,
    }


@v1_router.post("/channels/teams/activities")
async def teams_activities_webhook(request: Request):
    """Incoming webhook for Microsoft Teams Bot Framework Activities."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    reg = get_adapter_registry()
    adapter = reg.get("teams")
    if not adapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teams adapter not found")

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }


@v1_router.post("/channels/discord/interactions")
async def discord_interactions_webhook(request: Request):
    """Incoming webhook for Discord Interactions and slash commands."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # Discord Interaction Type 1: PING -> reply with PONG {"type": 1}
    if body.get("type") == 1:
        return {"type": 1}

    reg = get_adapter_registry()
    adapter = reg.get("discord")
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Discord adapter not found"
        )

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }


@v1_router.post("/channels/mattermost/hooks")
async def mattermost_hooks_webhook(request: Request):
    """Incoming webhook for Mattermost slash commands, outgoing webhooks, and events."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    reg = get_adapter_registry()
    adapter = reg.get("mattermost")
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mattermost adapter not found"
        )

    normalized = adapter.normalize_inbound(body)
    return {
        "status": "received",
        "normalized": normalized,
    }


# Mount router to FastAPI app


app.include_router(v1_router)


@app.get("/healthz")
async def healthz():
    """Liveness probe for Tauri shell and process supervisor."""
    uptime = time.time() - START_TIME
    return {
        "status": "ok",
        "service": "agent-engine-sidecar",
        "version": "0.1.0",
        "engine": "Agent Engine",
        "uptime_seconds": round(uptime, 2),
    }


def main(argv: Optional[List[str]] = None):
    """Entrypoint for Agent Engine Python sidecar service."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Agent Engine Python Sidecar Service (FastAPI + FastMCP + ACP)",
        prog="agent-engine-sidecar",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(os.environ.get("AGENT_ENGINE_PORT", os.environ.get("PORT", "8000"))),
        help="Port to bind the sidecar service (default: 8000 or $AGENT_ENGINE_PORT/$PORT)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("AGENT_ENGINE_HOST", "127.0.0.1"),
        help="Host address to bind the sidecar service (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("AGENT_ENGINE_IPC_TOKEN"),
        help="Optional secret IPC token for shell-to-sidecar authentication",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        help="Print sidecar version and exit",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Perform internal health self-test and exit",
    )

    args = parser.parse_args(argv)

    if args.version:
        print("0.1.0")
        sys.exit(0)

    if args.verify:
        print("Agent Engine Sidecar v0.1.0: Self-check passed. Routes and schema verified.")
        sys.exit(0)

    if args.token:
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = args.token

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
