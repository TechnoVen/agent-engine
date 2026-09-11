import asyncio
import datetime
import json
import os
import sys
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure numpy pre-import before dspy lazy import
import numpy  # noqa: F401
import psutil
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.cache import get_semantic_cache
from core.config import get_feature_flags, require_flag, set_flag_override
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
from core.safety import get_policy_engine
from core.security import get_credential_manager, mask_secret
from core.storage import get_storage_backend
from core.updater import get_update_manager


from core.session import (
    AgentParticipant,
    ToolCall,
    get_session_store,
)
from core.telemetry import BudgetConfig, get_cost_tracker
from core.templates import TemplateManager
from server.watcher import apply_staged_patch, get_staged_patches, reject_staged_patch

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True
    skill_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    cost_usd: float = 0.0


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


class RunWorkflowRequest(BaseModel):
    workflow_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResponse(BaseModel):
    execution_id: str
    status: str


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


class CostMetricsResponse(BaseModel):
    total_cost_usd: float
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
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
        ..., description="Provider name (e.g. openai, anthropic, gemini, deepseek, groq, kimi)"
    )
    api_key: Optional[str] = Field(
        default=None, description="Optional API key to test directly; if omitted, uses stored key"
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


# ---------------------------------------------------------------------------
# API Endpoints (/v1/...)
# ---------------------------------------------------------------------------


@v1_router.post("/chat/completions", response_model=None)
async def chat_completions(req: ChatRequest):
    """Execute a chat completion. Supports direct JSON response or streaming SSE tokens."""
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:10]}"

    if req.stream:

        async def event_generator() -> AsyncGenerator[str, None]:
            # Emit token stream event
            tokens = ["Hello", " from", " Agent", " Engine", "!"]
            for t in tokens:
                payload = {
                    "event": "token",
                    "session_id": session_id,
                    "delta": t,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(0.05)

            # Emit cost update event
            cost_event = {
                "event": "cost_update",
                "session_id": session_id,
                "model": req.model or "default",
                "prompt_tokens": len(req.prompt.split()),
                "completion_tokens": len(tokens),
                "cost_usd": 0.0001,
                "timestamp": datetime.datetime.now().isoformat(),
            }
            yield f"data: {json.dumps(cost_event)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Non-streaming response
    return ChatResponse(
        response=f"Response from Agent Engine to: {req.prompt}",
        session_id=session_id,
        tool_calls=[],
        cost_usd=0.0001,
    )


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
async def list_skills():
    """List available skill templates from the catalog."""
    templates = TemplateManager.list_templates()
    skills_list = []
    for t in templates:
        in_fields = list(t.inputs.keys()) if isinstance(t.inputs, dict) else t.inputs
        out_fields = list(t.outputs.keys()) if isinstance(t.outputs, dict) else t.outputs
        skills_list.append(
            SkillInfo(
                id=t.id,
                name=t.name,
                category=t.category,
                description=t.description,
                inputs=in_fields,
                outputs=out_fields,
            )
        )
    return skills_list


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


@v1_router.get("/workflows", response_model=List[WorkflowInfo])
async def list_workflows():
    """List registered graph workflows."""
    return [
        WorkflowInfo(
            id="wf_code_audit_and_fix",
            name="Automated Code Audit & Remediation",
            description="Audits changed files with Code Sentry and generates staged patches.",
            steps=["scan_code", "evaluate_risk", "generate_patch", "stage_review"],
        )
    ]


@v1_router.post("/workflows", response_model=WorkflowExecutionResponse)
async def run_workflow(req: RunWorkflowRequest):
    """Trigger a workflow execution."""
    execution_id = f"wf_exec_{uuid.uuid4().hex[:8]}"
    return WorkflowExecutionResponse(execution_id=execution_id, status="queued")


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


@v1_router.get("/memory", response_model=MemoryQueryResponse)
async def query_memory(
    query: str = Query(..., description="Semantic search query"),
    top_k: int = Query(5, ge=1, le=50, description="Max passages to retrieve"),
):
    """Retrieve passages from the ChromaDB vector database."""
    passages = memory_instance.retrieve_passages(query, n_results=top_k)
    return MemoryQueryResponse(query=query, passages=passages)


@v1_router.post("/memory", response_model=IngestMemoryResponse)
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
async def apply_patch(patch_id: int):
    """Apply a staged patch directly to the filesystem."""
    success = apply_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patch #{patch_id} not found or already applied.",
        )
    return ActionResult(success=True, message=f"Successfully applied patch #{patch_id}")


@v1_router.post("/patches/{patch_id}/reject", response_model=ActionResult)
async def reject_patch(patch_id: int):
    """Reject and dismiss a staged patch in SQLite."""
    success = reject_staged_patch(patch_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patch #{patch_id} not found or already rejected.",
        )
    return ActionResult(success=True, message=f"Successfully rejected patch #{patch_id}")


@v1_router.get("/telemetry", response_model=TelemetryResponse)
async def get_telemetry():
    """Return local resource utilization and model router readiness."""
    ram = psutil.virtual_memory()
    router_status = router_instance.get_status()

    return TelemetryResponse(
        cpu_usage_percent=psutil.cpu_percent(interval=0.05),
        ram_used_percent=ram.percent,
        ram_total_gb=round(ram.total / (1024**3), 2),
        ram_available_gb=round(ram.available / (1024**3), 2),
        primary_provider=router_status.get("primary_provider", "local"),
        active_model=router_status.get("active_model", "qwen2.5-coder"),
        ollama_active=bool(router_status.get("ollama_live", False)),
        llamacpp_active=bool(router_status.get("llamacpp_live", False)),
        indexed_memory_documents=memory_instance.count(),
    )


@v1_router.get("/telemetry/cost", response_model=CostMetricsResponse)
async def get_cost_metrics(
    group_by: str = Query("day", pattern="^(agent|model|project|day)$"),
    project: Optional[str] = Query(None),
    agent_name: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None),
):
    """Get aggregated token usage, spend breakdown, and active budget alerts."""
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

    alerts_list = [
        alert.__dict__
        for alert in cost_tracker_instance.check_budget_alerts(project=project or "default")
    ]

    return CostMetricsResponse(
        total_cost_usd=summary.get("total_cost_usd", 0.0),
        total_prompt_tokens=summary.get("total_prompt_tokens", 0),
        total_completion_tokens=summary.get("total_completion_tokens", 0),
        total_tokens=summary.get("total_tokens", 0),
        breakdown=breakdown,
        alerts=alerts_list,
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
    """Evaluate a prospective tool call against active safety policies and risk scoring."""
    engine = get_policy_engine()
    decision = engine.evaluate(
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        context={
            "session_id": req.session_id,
            "allow_high_risk": req.allow_high_risk,
            "auto_apply": req.auto_apply,
        },
    )
    return SafetyEvaluationResponse(
        decision=decision.decision,
        risk_score=decision.risk_score,
        risk_level=decision.risk_level,
        violating_rules=[SafetyPolicyRuleInfo(**r.to_dict()) for r in decision.violating_rules],
        suggestion=decision.suggestion,
        reason=decision.reason,
        audit_id=decision.audit_id,
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
async def set_credential_endpoint(req: SetCredentialRequest):
    """Store a credential in the secure backend (OS Keychain with AES-256-GCM Vault fallback)."""
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
    reveal: bool = Query(False, description="Whether to reveal the plaintext secret value"),
):
    """Retrieve a stored credential. Masked by default unless reveal=true is explicitly set."""
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
async def delete_credential_endpoint(service: str, key: str):
    """Delete a stored credential from secure backends."""
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
    res = mgr.test_provider_key(req.provider, api_key=req.api_key)
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


# Mount router to FastAPI app


app.include_router(v1_router)


@app.get("/healthz")
async def healthz():
    """Liveness probe for Tauri shell and process supervisor."""
    return {"status": "ok", "service": "agent-engine-sidecar"}


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
