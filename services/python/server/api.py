import asyncio
import datetime
import json
import os
import sys
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

from core.config import get_feature_flags, require_flag, set_flag_override
from core.memory import AgentMemory, ObservationalMemory
from core.pipelines import get_pipeline_registry
from core.router import ModelRouter
from core.safety import get_policy_engine
from core.storage import get_storage_backend
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
    breakdown: List[Dict[str, Any]]


class AuthSession(BaseModel):
    user_id: str
    email: Optional[str] = None
    role: str
    tenant_id: Optional[str] = None


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
async def get_cost_metrics(group_by: str = Query("day", pattern="^(agent|model|project|day)$")):
    """Get aggregated token usage and spend metrics."""
    summary = get_storage_backend().get_cost_summary()
    return CostMetricsResponse(
        total_cost_usd=summary.get("total_cost_usd", 0.0),
        breakdown=[
            {
                "group": group_by,
                "prompt_tokens": summary.get("total_prompt_tokens", 0),
                "completion_tokens": summary.get("total_completion_tokens", 0),
                "cost_usd": summary.get("total_cost_usd", 0.0),
            }
        ],
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


# Mount router to FastAPI app
app.include_router(v1_router)


@app.get("/healthz")
async def healthz():
    """Liveness probe for Tauri shell and process supervisor."""
    return {"status": "ok", "service": "agent-engine-sidecar"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("services.python.server.api:app", host="127.0.0.1", port=8765, reload=False)
