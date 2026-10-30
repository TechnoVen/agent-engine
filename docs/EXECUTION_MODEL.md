# Agent Engine — Canonical Execution Model

> **Status:** Canonical Architecture Specification  
> **Governing ADR:** ADR-016 (Single Authoritative Execution Kernel Invariant)  
> **Target Release:** 0.5 (Stage R1 Implementation Target)  

---

## 1. Overview & Architectural Invariant

The canonical execution model enforces one fundamental invariant across the entire product:

> **All work in Agent Engine—whether from chat, DSPy programs, skills, tools, workflows, swarms, or background jobs—must execute through the canonical `ExecutionCoordinator`.**

No presentation surface, API route, or subsystem may bypass this pipeline to invoke models or tools directly.

---

## 2. Universal Execution Pipeline

Every execution follows ten sequential phases:

```text
1. ExecutionRequest
       │
2. Context Assembly ──── (ContextBuilder: project files, bounded history, skills)
       │
3. Policy Pre-Flight ─── (SecurityGuardrails: trust boundary check, AST scan)
       │
4. Budget Check ──────── (CostTracker: verify spend limit, rate cap, off-peak)
       │
5. Routing & Planning ── (ExecutionRouter: resolve tier, model, tool parameters)
       │
6. Consequential Gate ── (ApprovalService: pause if destructive operation)
       │
7. Execution Dispatch ── (Model Gateway, Skill Runner, or Worker)
       │
8. Verification ──────── (Schema validation, safety check, assertion testing)
       │
9. Telemetry Recording ─ (Record real tokens, latency, cost, event trace)
       │
10. ExecutionResult
```

---

## 3. Core Data Structures

### 3.1. `ExecutionRequest`
```python
class ExecutionRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    project_id: str
    session_id: Optional[str] = None
    task_type: str  # "chat", "dspy", "skill", "workflow_step", "agent_task"
    prompt: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    model_preference: Optional[str] = None
    target_tier: Optional[str] = None  # "code", "cache", "small", "mid", "frontier"
    isolation_mode: str = "standard"  # "standard", "worktree", "read_only"
    parent_execution_id: Optional[str] = None
```

### 3.2. `ExecutionContext`
```python
class ExecutionContext(BaseModel):
    execution_id: str
    project_root: str
    project_instructions: str
    active_skills: List[str]
    retrieved_passages: List[Dict[str, Any]]
    conversation_history: List[Dict[str, str]]
    token_budget: int
    security_policy_id: str
    created_at: str
```

### 3.3. `ExecutionEvent` (Streaming)
```python
class ExecutionEventType(str, Enum):
    STARTED = "started"
    ROUTING_RESOLVED = "routing_resolved"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    TOKEN_STREAM = "token_stream"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionEvent(BaseModel):
    event_id: str
    execution_id: str
    event_type: ExecutionEventType
    timestamp: str
    payload: Dict[str, Any]
```

### 3.4. `ExecutionResult`
```python
class ExecutionResult(BaseModel):
    execution_id: str
    status: str  # "completed", "failed", "cancelled"
    outputs: Dict[str, Any]
    error: Optional[str] = None
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    duration_ms: float
    model_used: str
    provider_used: str
    cache_hit: bool
    artifacts_created: List[str] = Field(default_factory=list)
```

---

## 4. Execution State Machine

```text
                ┌─────────┐
                │ PENDING │
                └────┬────┘
                     │
              ┌──────▼──────┐
              │   ROUTING   │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
    ┌────────►│   RUNNING   │◄────────┐
    │         └──────┬──────┘         │
    │                │                │
(Approved)    (Approval Gate)     (Redirect)
    │                │                │
    │     ┌──────────▼──────────┐     │
    └─────┤  WAITING_APPROVAL   ├─────┘
          └──────────┬──────────┘
                     │ (Rejected / Cancelled)
                     │
              ┌──────▼──────┐
              │ VERIFYING   │
              └──────┬──────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
  ┌─────▼─────┐┌─────▼─────┐┌─────▼─────┐
  │ COMPLETED ││  FAILED   ││ CANCELLED │
  └───────────┘└───────────┘└───────────┘
```

* **Transition Invariants:**
  * Once a state is terminal (`COMPLETED`, `FAILED`, `CANCELLED`), no further state transitions or token streams are permitted.
  * Stop command immediately sets status to `CANCELLED` and sends cancellation signals to upstream HTTP/process threads.
  * Rejection at `WAITING_APPROVAL` either diverts execution to a designated fallback node or cleanly terminates with status `CANCELLED`.

---

## 5. Cancellation & Process Isolation

1. **In-Flight Cancellation:**
   * Every execution holds an `asyncio.Event` cancellation token.
   * Model HTTP streams are aborted using client timeouts and socket drops.
   * Subprocess executions (e.g., skill scripts, compilers) are launched in dedicated process groups and terminated using canonical cross-platform semantics: graceful termination -> bounded wait (1.5s) -> force termination using platform-appropriate process semantics.
2. **Worktree Isolation for Coding:**
   * High-risk code alterations run in isolated Git worktrees (`git worktree add`).
   * Working branches are never merged into the user's canonical branch without explicit test validation and operator approval.

---

## 6. Event Durability & Persistence Classification

Execution events are explicitly categorized into **Durable** and **Transient** tiers:

| Tier | Event Types | Persistence Invariant | Purpose |
|---|---|---|---|
| **Durable Events** | `STATE_CHANGE`, `ROUTING_RESOLVED`, `APPROVAL_REQUIRED`, `APPROVAL_RESOLVED`, `TOOL_CALL_STARTED`, `TOOL_CALL_COMPLETED`, `VERIFICATION_STARTED`, `VERIFICATION_COMPLETED`, `COMPLETED`, `FAILED`, `CANCELLED` | Persisted immediately to SQLite `execution_events` ledger. | Authoritative execution reconstruction, audit provenance, replay, and restart recovery. |
| **Transient Events** | `TOKEN_DELTA`, `OUTPUT_CHUNK` | In-memory only; bypass SQLite disk ledger; streamed live via SSE bounded queue. | Real-time UI responsiveness without disk write amplification. Process restart does not reconstruct individual token deltas. |

---

## 7. Partial-Output Semantics Across Terminal States

When execution concludes or terminates prematurely, generated outputs are governed by strict semantic invariants:

- **`COMPLETED`**: Persist full, verified assistant response to `UnifiedSessionStore`.
- **`PARTIAL`**: Persist clearly marked partial output in execution metadata/drafts; marked explicitly as partial.
- **`CANCELLED`**: Partial output is retained in execution diagnostics / drafts (`ExecutionResult.partial_output`), but is **never** persisted to `UnifiedSessionStore` as a successful assistant response.
- **`FAILED`**: Partial output is retained in execution diagnostic evidence for debugging; never represented as a successful assistant message.
- **`TIMED_OUT`**: Partial output is retained in execution diagnostic evidence; never represented as a completed response.

