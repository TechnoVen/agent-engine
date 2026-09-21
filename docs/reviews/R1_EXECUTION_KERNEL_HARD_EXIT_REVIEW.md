# R1 Hard Exit Review: Single Authoritative Execution Kernel

**Milestone:** R1 — Core Execution Kernel  
**Governing ADR:** [ADR-016: Single Authoritative Execution Kernel Invariant](../../docs/adr/ADR-016-single-execution-kernel.md)  
**Status:** COMPLETE — PENDING CTO HARD EXIT SIGN-OFF  
**Date:** September 21, 2026  
**Auditor / Lead:** Senior Kernel Architect / Antigravity AI  

---

## Executive Summary

Milestone **R1 (Single Authoritative Execution Kernel)** has successfully fulfilled all exit criteria defined in ADR-016 and the architectural roadmap. All legacy bypass execution paths—including direct model provider instantiation, unmonitored skill execution, rogue DSPy programs, uncoordinated external agent adapters, and arbitrary subprocess shell escapes—have been eliminated. Every supported execution surface originating from REST, FastMCP, or internal pipeline execution routes authoritatively through `ExecutionCoordinator.execute(...)`.

The monolithic server (`services/python/server/api.py`, formerly 5,683 lines) has been decomposed into **19 modular domain routers** under `services/python/server/routers/`, supported by an application factory (`create_app`), a central dependency container (`AppServices`), canonical domain error translation (`errors.py`), SSE streaming transport utilities (`transport.py`), and 139 verified Pydantic transport models (`schemas.py`). `api.py` is preserved strictly as a 345-line backward-compatible façade with zero route decorators and zero business logic.

Full verification confirms **522 passing tests (0 failures, 0 errors)**, a clean Rust Tauri desktop check (`cargo check` in 0.75s), and a clean frontend build (`pnpm -r build` across all workspace packages in 11.9s).

---

## 1. Architectural Invariant & Invocation Topology

### 1.1 Reconciled R1 Hard-Exit Invariant
> *"Every supported production execution surface in the R1 product path uses the canonical ExecutionCoordinator. Deferred legacy runtimes are either non-executable, explicitly experimental/unsupported, or documented for later convergence."*

### 1.2 Unified Invocation Topology

```
caller (REST Client / Tauri Shell / FastMCP Server / ACP Bridge)
       │
       ▼
ExecutionCoordinator.execute(ExecutionRequest)
       │
       ├─► 1. Consequential Operation Pre-flight & Safety Policies (PolicyEngine)
       ├─► 2. Budget & Spending Authorization (CostTracker)
       ├─► 3. Prompt Cancellation Token Verification (CancellationToken)
       │
       ▼
Skill / Adapter / Pipeline Resolution
       │
       ▼
CapabilityBoundary (Project-Root Containment / Bounded Subprocess / CWD Restriction)
       │
       ▼
Native Implementation / DSPy KernelLMAdapter / External Channel
       │
       ├─► Canonical Execution Events (SSE stream / SQLite execution table)
       ├─► Artifact Manifest & Content Preservation (ArtifactService)
       └─► Tamper-Evident SHA-256 Hash-Chained Trace (ExecutionLedgerService)
```

Every execution produces:
1. A unique, canonical `execution_id` prefixed by task type (`exec_...`).
2. Durable status tracking across 6 finite states (`QUEUED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`).
3. Project-scoped artifact preservation with SHA-256 checksums (`core/artifacts/service.py`).
4. A SHA-256 hash-chained tamper-evident execution trace (`core/ledger/service.py`).

---

## 2. R1 Support Matrix & Production Paths

| Execution Surface | Entrypoint / Protocol | R1 Execution Authority | R1 Support Status | Planned Convergence |
| :--- | :--- | :--- | :--- | :--- |
| **Chat Completions** | `POST /v1/chat/completions` | `ExecutionCoordinator.execute(task_type="chat")` | **Supported (Tier 1 Production)** | Canonical |
| **DSPy Pipelines** | `POST /v1/pipelines/{id}/run` | `KernelLMAdapter` -> `ExecutionCoordinator` | **Supported (Tier 1 Production)** | Canonical |
| **Skills & Tools** | `POST /v1/skills/{id}/execute`<br>MCP `execute_skill_template` | `ExecutionCoordinator(task_type="skill")`<br>+ `CapabilityBoundary` | **Supported (Tier 1 Production)** | Canonical |
| **External Agent Adapters** | `POST /v1/adapters/{id}/execute`<br>`POST /v1/adapters/{id}/stream` | `ExecutionCoordinator(task_type="adapter")`<br>+ `CapabilityBoundary` | **Supported (Tier 1 Production)** | Canonical |
| **Dynamic MCP Blueprints** | FastMCP `execute_dynamic_blueprint` | `ExecutionCoordinator.execute(...)` | **Supported (Tier 1 Production)** | Canonical |
| **Artifacts & Storage** | `/v1/artifacts/*`, `/v1/projects/*/artifacts` | `ArtifactService` (Project containment) | **Supported (Tier 1 Production)** | Canonical |
| **Execution Ledger** | `GET /v1/executions/{id}/trace` | `ExecutionLedgerService` (SHA-256 chain) | **Supported (Tier 1 Production)** | Canonical |
| **Channel Webhooks** | `/slack/events`, `/teams/activities`<br>`/discord/interactions`, `/mattermost/hooks` | Normalized inbound ingestion only;<br>zero model or subprocess execution | **Supported (Ingestion Only)** | Canonical |
| **Workflow DAG Execution** | `POST /v1/workflows/{id}/run` | Legacy `WorkflowEngine` (Phase 7 Simulation) | **Deferred Legacy Runtime** | Milestone R4 |
| **Swarm Coordination** | `POST /v1/swarm/run` | Legacy `SwarmCoordinator` (Phase 7 Simulation) | **Deferred Legacy Runtime** | Milestone R4 |
| **Scheduled Tasks** | `POST /v1/tasks/{id}/trigger` | In-memory metadata & trigger simulation | **Deferred Legacy Runtime** | Milestone R3 / R4 |
| **Collaboration Rooms** | `/v1/rooms/*` | In-memory room metadata & task boards | **UI Placeholder / Metadata** | Milestone R4 |

---

## 3. Shadow Execution Registry

To ensure 100% truthful architecture without pretending that legacy mock engines are canonical, all legacy execution surfaces outside `ExecutionCoordinator` are cataloged in this registry:

| Component | File Path | Nature of Legacy Runtime | Current R1 Status | Target Convergence Milestone |
| :--- | :--- | :--- | :--- | :--- |
| `WorkflowEngine` | `core/workflows/engine.py` | Phase 7 DAG traversal engine returning synthetic node responses (`"Executed skill '{skill_id}'"`) and `asyncio.sleep(0.05)` simulation delays. | `DEFERRED_LEGACY_RUNTIME` | **Milestone R4 (Multi-Agent & Long-Horizon Workflows)**: Rewrite engine to dispatch every step as a child `ExecutionRequest` through `ExecutionCoordinator`. |
| `SwarmCoordinator` | `core/workflows/swarm.py` | Phase 7 multi-agent simulation loop allocating mock tasks across synthetic agent clusters without real model calls. | `DEFERRED_LEGACY_RUNTIME` | **Milestone R4**: Converge onto canonical `ExecutionCoordinator` multi-agent coordination primitives. |
| Scheduled Task Runner | `services/python/server/routers/tasks.py` | In-memory cron task registry storing scheduling metadata; trigger endpoint returns synthetic acknowledgment. | `DEFERRED_LEGACY_RUNTIME` | **Milestone R3 / R4**: Wire cron scheduler to submit canonical `ExecutionRequest`s via `coordinator`. |
| Room Collaboration | `services/python/server/routers/collaboration.py` | Metadata store managing collaborative chat rooms, participant rosters, and shared task claim states. | `UI_PLACEHOLDER / METADATA` | **Milestone R4**: Wire collaborative room turns into shared multi-agent session execution. |

---

## 4. Comprehensive Audit & Verification Questions

### Question 1: Are there any execution bypasses remaining outside ExecutionCoordinator?
**Verdict:** **ZERO BYPASSES IN SUPPORTED PRODUCTION PATHS.**
- **Chat Completions:** Dispatches via `ExecutionCoordinator.execute(...)` with `task_type="chat"`.
- **Pipelines (DSPy):** Intercepted via `KernelLMAdapter` (inheriting `dspy.LM`), authoritatively enforcing model routing, cancellation checks, token accounting, and cost tracking.
- **Skills:** `execute_skill` (REST) and `execute_skill_template` (MCP) route strictly through `coordinator.execute(...)` with `task_type="skill"`.
- **External Adapters:** `execute_adapter_endpoint` and `stream_adapter_endpoint` route strictly through `coordinator.execute(...)` with `task_type="adapter"`.
- **Dynamic MCP Blueprints:** `execute_dynamic_blueprint` in `server/mcp_server.py` rewired to dispatch through `coordinator.execute(...)`.

### Question 2: Are execution states, cancellation, timeouts, and failures truthfully handled?
**Verdict:** **TRUTHFUL & UNCOMPROMISED.**
- **Zero Fake-Success Placeholders in Production:** Unimplemented skills or missing prompt templates raise explicit errors (`FileNotFoundError`, `ValueError`) and fail with `ExecutionStatus.FAILED` rather than generating mock success strings.
- **Cancellation Lifecycle:** Cooperative cancellation checked before every tier dispatch, tool call, and subprocess step. Cancelled executions transition to `CANCELLED` (or HTTP 409) with partial output saved as `partial_output.txt` artifacts.
- **Process Termination Safety:** Subprocesses managed under `CapabilityBoundary` employ the canonical cross-platform termination contract:
  $$\text{graceful termination} \longrightarrow \text{bounded wait} \longrightarrow \text{force termination using platform-appropriate process semantics}$$
  POSIX systems use `proc.terminate()` $\to$ bounded wait (1.5s) $\to$ `proc.kill()`; Windows systems escalate gracefully through process handle termination.

### Question 3: How is sandbox terminology scoped ahead of R2?
**Verdict:** **ACCURATELY QUALIFIED.**
- Subprocess execution in R1 is strictly documented and implemented as **"constrained subprocess boundaries"** and **"bounded capability wrappers"** providing project-root containment, cwd enforcement, argument sanitization, and timeout bounding.
- Full kernel sandbox enforcement (Linux namespaces, seccomp-bpf filters, network namespace isolation, unshare) is explicitly reserved for **Milestone R2 (Security & Isolation)**.

### Question 4: Are artifacts and ledger records properly attributed and secured?
**Verdict:** **VERIFIED PROJECT ATTRIBUTION & TAMPER-EVIDENT INTEGRITY.**
- **Artifacts:** Stored with metadata, SHA-256 checksums, and strict project attribution in `core/artifacts/service.py`. Cross-project access raises `ArtifactSecurityError` / HTTP 403. Path traversal attempts (`../`) are rejected.
- **Ledger:** Recorded chronologically as a **SHA-256 hash-chained tamper-evident execution trace** in `core/ledger/service.py`. Each entry cryptographically hashes the previous entry's checksum. (Unanchored claims of "asymmetric cryptographic verification" are retracted; digital signatures and external timestamping belong to R2/R3).

### Question 5: Has the monolithic `api.py` been cleanly divided by domain?
**Verdict:** **DECOMPOSED INTO 19 DOMAIN ROUTERS.**
The monolithic `services/python/server/api.py` was reduced from 5,683 lines down to 345 lines (94.0% reduction).
The 19 modular domain routers under `services/python/server/routers/` are:

1. `chat.py` (1 endpoint: `/v1/chat/completions`)
2. `executions.py` (5 endpoints: status, events, stream, cancel, project executions)
3. `ledger.py` (1 endpoint: execution trace)
4. `artifacts.py` (5 endpoints: artifact CRUD & content)
5. `pipelines.py` (6 endpoints: pipeline registry, execution, cases, router audit)
6. `skills.py` (22 endpoints: skill CRUD, execution, collections, packages)
7. `adapters.py` (9 endpoints: adapter listing, execution, streaming, test, webhooks)
8. `projects.py` (17 endpoints: project CRUD, unified sessions, context builder)
9. `policies.py` (16 endpoints: safety operations, approvals, audit logs, policy YAML)
10. `telemetry.py` (9 endpoints: hardware telemetry, cost metrics, budget, distillation)
11. `models.py` (9 endpoints: semantic cache, model eval suite, router tiers)
12. `credentials.py` (5 endpoints: API key / credential management CRUD & test)
13. `workflows.py` (14 endpoints: workflow definitions, DAG gates, run inspection)
14. `swarm.py` (3 endpoints: swarm cases, cost estimate, swarm execution)
15. `tasks.py` (5 endpoints: scheduled task CRUD, toggle, trigger)
16. `memory.py` (5 endpoints: ChromaDB vector query, ingestion, observational memory)
17. `collaboration.py` (14 endpoints: collaborative rooms, participant roster, room tasks)
18. `patches.py` (3 endpoints: staged patch inspection, apply, reject)
19. `system.py` (12 endpoints: health probe, app settings, auto-updater, feature flags)

**Total Inventory:** Exactly 161 unique domain routes + 1 root `/healthz` liveness probe = 162 operations.

- Application factory: `services/python/server/app.py` (`create_app()`).
- Centralized container: `services/python/server/container.py` (`AppServices`).
- Single shared service identity: verified across all routers (`ExecutionCoordinator`, `StorageBackend`, `PolicyEngine`, `ModelRouter`, `CostTracker`, `ArtifactService`, `ExecutionLedgerService`).
- Compatibility façade: `api.py` has **0 route decorators**, **0 business logic**, and exactly 1 registered handler per route.

### Question 6: Do inbound channel webhooks spawn unmonitored agent executions?
**Verdict:** **AUDITED — ZERO BACKGROUND EXECUTION.**
Inbound webhooks in `services/python/server/routers/adapters.py` (`/slack/events`, `/teams/activities`, `/discord/interactions`, `/mattermost/hooks`):
- Only execute synchronous payload normalization via `adapter.normalize_inbound(body)`.
- Return an immediate acknowledgement response: `{"status": "received", "event_id": ...}`.
- Do NOT invoke language models, trigger subprocesses, or spawn unmonitored background tasks.
- Outbound responses are triggered exclusively when callers invoke `/v1/adapters/{id}/execute` through canonical `ExecutionCoordinator`.

---

## 5. Repository Audits

### 5.1 Direct Execution Audit
A comprehensive AST and regex search for direct subprocess invocation (`subprocess.run`, `subprocess.Popen`, `os.system`, `os.popen`, `asyncio.create_subprocess_exec`) and direct provider SDK instantiation across `core/` and `services/python/server/` yielded:
- **Subprocess calls in core/server:** Exactly 3 instances in `core/telemetry/hardware.py` (lines 107, 162, 198) strictly for read-only hardware telemetry inspection (`nvidia-smi`, `lspci`, `rocm-smi` with bounded timeouts).
- **Subprocess calls for agent tasks:** Exactly 1 location: `CapabilityBoundary.run_subprocess(...)` in `core/skills/boundary.py`, strictly wrapped under declared permission checks and cancellation tokens.
- **Direct model calls:** Zero direct bypasses. All model generation flows through `ModelRouter` managed by `ExecutionCoordinator`.
- **Unauthorized Bypasses:** **0 violations.**

### 5.2 Fake / Stub / Simulation Audit
A repository-wide audit for keywords (`fake`, `mock`, `stub`, `simulation`, `simulate`, `dummy`) in `core/` and `server/` identified 37 occurrences across 15 files, classified as follows:

| Classification | Count | Files | Description |
| :--- | :--- | :--- | :--- |
| `TEST_ONLY` | 9 | `core/adapters/mock.py`, `core/adapters/__init__.py` | Deterministic `MockAgentAdapter` used exclusively for offline integration tests. |
| `LEGITIMATE_SIMULATION_FEATURE` | 21 | `core/adapters/{codex,goose,discord,mattermost,slack,teams,openclaw,mcp_fallback}.py`, `core/eval/suite.py`, `routers/policies.py` | Offline fallback modes when API keys are absent, policy dry-run (`/v1/safety/dry-run`), and eval benchmark simulation. Explicitly logged as simulation modes; zero fake success. |
| `DEFERRED_LEGACY_RUNTIME` | 6 | `core/workflows/engine.py`, `core/workflows/swarm.py`, `routers/workflows.py` | Phase 7 legacy workflow and swarm simulation runners scheduled for canonical rewrite in Milestone R4. |
| `PRODUCTION_FAKE_SUCCESS` | **0** | None | **Zero unexplained fake successes.** |

---

## 6. Regression & Verification Evidence

| Component / Test Suite | Command | Result | Duration | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Full Python Regression** | `uv run pytest` | **522 passed, 0 failed** | 67.45s | 100% pass rate across 43 test suites |
| **API Domain Decomposition** | `uv run pytest tests/test_api_domain_decomposition.py` | **25 passed** | 10.44s | Validates all 19 domain routers, shared services, and façade integrity |
| **Router Hardening & Failover** | `uv run pytest tests/test_router_hardening.py` | **7 passed** | 3.99s | Circuit breaker fast-path, outage fallback < 2s |
| **Skills & Kernel Integration** | `uv run pytest tests/test_skills_kernel_integration.py` | **18 passed** | 5.77s | CapabilityBoundary & coordinator execution |
| **Pipeline Kernel Integration** | `uv run pytest tests/test_pipeline_kernel_integration.py` | **16 passed** | 8.55s | KernelLMAdapter intercepting DSPy |
| **Artifact Model & Storage** | `uv run pytest tests/test_artifacts.py` | **15 passed** | 6.95s | Project attribution & SHA-256 checksums |
| **Cancellation & State Machine** | `uv run pytest tests/test_cancellation.py` | **17 passed** | 7.35s | Cooperative cancellation & process cleanup |
| **Execution Ledger & Provenance**| `uv run pytest tests/test_ledger.py` | **18 passed** | 6.00s | Tamper-evident hash chain verification |
| **Tauri Desktop Shell (Rust)** | `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` | **0 errors, clean check** | 0.75s | Clean Rust compile |
| **Desktop & JS SDK Build** | `pnpm -r build` | **3 packages built** | 11.9s | Clean TypeScript & Vite build |

### Upstream Vendor Warnings Audit
Exactly 3 warnings are emitted during pytest execution. None originate from project-owned code:

| Warning Type | Emitting File | Cause / Upstream Owner | Impact on Agent Engine |
| :--- | :--- | :--- | :--- |
| `StarletteDeprecationWarning` | `fastapi/testclient.py:1` | Upstream FastAPI notice: `Using httpx with starlette.testclient is deprecated; install httpx2 instead.` | None. Standard Starlette test client deprecation notice; non-blocking. |
| `DeprecationWarning` | `starlette/testclient.py:53` | Upstream Starlette notice: `The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.` | None. Upstream Starlette/AnyIO import alias notice. |
| `DeprecationWarning` | `chromadb/telemetry/opentelemetry/__init__.py:128` | Upstream ChromaDB telemetry notice: `'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16`. | None. Upstream telemetry dependency notice. All project-owned code uses `inspect.iscoroutinefunction`. |

---

## 7. Hard Exit Gate Sign-Off Declaration

With all 14 R1 tasks fully implemented, verified, reconciled, and audited:
- **R1.1** Project Registry & Multi-Tenancy (`S1`)
- **R1.2** Single Root Execution Kernel & Request Model (`S1`)
- **R1.3** Execution State Machine & Lifecycle Hooks (`S1`)
- **R1.4** SQLite Storage Schema & Migrations (`S1`)
- **R1.5** Model Router & Tier Dispatch (`S1`)
- **R1.6** Cost Tracker & Budget Guardrails (`S1`)
- **R1.7** Context Builder & Project Memory (`S1`)
- **R1.8** Prompt Cancellation & Process Termination (`S1`)
- **R1.9** Consequential Operation Staging & Safety Policies (`S1`)
- **R1.10** Execution Artifact Service & Storage (`S1`)
- **R1.11** Execution Ledger & Tamper-Evident Hash Chain (`S1`)
- **R1.12** Rewire DSPy & Pipelines to Execution Kernel (`S1`)
- **R1.13** Rewire Skills & External Agent Adapters (`S1`)
- **R1.14** Split Monolithic API by Domain (`S1`)

Milestone **R1 (Execution Kernel)** is declared **HARD EXIT READY**.

Execution is strictly halted at this gate pending CTO review and sign-off. Neither **Track A (R2: Security, Authorization & Recovery)** nor **Track B (GUI Visual Pass 1)** shall commence until explicit user authorization is provided.
