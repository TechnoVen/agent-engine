# Agent Engine — Canonical Implementation Status & Capability Matrix

> **Status:** Authoritative Implementation Reality  
> **Updated:** September 18, 2026 (Stage R0 Baseline — Corrected per CTO Review)  
> **Governing Release:** 0.5 Nadir Founder MVP  

---

## 1. Maturity Level Definitions

The S0–S5 maturity scale applies strictly to **runtime capabilities** (execution code, integrations, and behavioral verification). Governance, specification, and architectural review tasks track operational status (`task_status: planned | in_progress | done`); their capability maturity is designated `N/A (Specification/Governance)`:

| Maturity Level | Criteria | Verification Standard |
|---|---|---|
| **S0 — Specified** | Architecture, interfaces, and acceptance criteria documented in canonical specs. | Approved design doc or ADR exists. |
| **S1 — Implemented** | Code exists, components load, unit-level logic is tested. | Unit tests pass in isolated test runner. |
| **S2 — Integrated** | Connected to adjacent subsystems in the primary application path. | REST API endpoints, client methods, UI screens wired. |
| **S3 — Behavior Verified** | Real behavior verified with external systems, negative paths, and failure modes. | E2E integration tests pass without mocks/stubs. |
| **S4 — Release Verified** | Verified in clean packaged desktop installer on target platform. | Desktop build, Tauri sidecar packaging verified. |
| **S5 — Production** | Hardened, monitored, observed, documentation complete, rollback proven. | Continuous production dogfooding without regressions. |

---

## 2. Implemented Legacy Capability Inventory (Phases 0.1 – 7.5)

Every implemented task from legacy Phases 0.1 through 7.5 is inventoried below with its canonical destination, migration action, and verified runtime maturity:

| Legacy ID | Description | Canonical Destination | Migration Action | Current Maturity | Evidence Link |
|---|---|---|---|---|---|
| **0.1** | Monorepo Structure & Build | Root workspace & configs | `KEEP` | **S4** | `pnpm build`, `cargo check` |
| **0.2** | Shared Schema & Contract Tests | `packages/shared-schema/` | `KEEP` | **S3** | `tests/test_api_contract.py` |
| **0.3** | SQLite Storage Repository | `core/storage/sqlite.py` | `KEEP` | **S3** | `tests/test_storage_repository.py` |
| **0.4** | Feature Flag Subsystem | `core/config/flags.py` | `KEEP` | **S3** | `tests/test_feature_flags.py` |
| **1.1** | Pipeline Registry & Dynamic Discovery | `core/execution/registry.py` | `KEEP` | **S3** | `tests/test_pipeline_registry.py` |
| **1.2** | Router Fallback Chain | `core/execution/router.py` | `INTEGRATE` | **S2** | `tests/test_router_hardening.py` |
| **1.3** | Observational Memory Subsystem | `core/memory/observational.py` | `INTEGRATE` | **S3** | `tests/test_observational_memory.py` |
| **1.4** | AST Safety Guardrails | `core/security/guardrails.py` | `INTEGRATE` | **S3** | `tests/test_safety_guardrails.py` |
| **1.5** | Real-Time Cost Tracker | `core/telemetry/cost.py` | `INTEGRATE` | **S3** | `tests/test_cost_tracker.py` |
| **1.6** | Unified Session Store & Converters | `core/session/store.py` | `KEEP` | **S3** | `tests/test_session_store.py` |
| **1.7** | Chroma Semantic Cache (L1/L2) | `core/resources/cache.py` | `KEEP` | **S3** | `tests/test_semantic_cache.py` |
| **1.8** | Context Budgeting Builder | `core/execution/context.py` | `INTEGRATE` | **S3** | `tests/test_context_builder.py` |
| **1.9** | Model Evaluation Suite | `core/eval/suite.py` | `KEEP` | **S3** | `tests/test_model_eval_suite.py` |
| **1.10**| Execution Router Integration | `core/execution/router.py` | `INTEGRATE` | **S3** | `tests/test_execution_router_integration.py` |
| **2.1** | Tauri v2 Desktop Shell Skeleton | `apps/desktop/` | `KEEP` | **S4** | `tests/test_desktop_shell.py` |
| **2.2** | Sidecar Bundling & Verification | `apps/desktop/src-tauri/` | `KEEP` | **S3** | `tests/test_sidecar_bundling.py` |
| **3.1** | Kimi-Style Conversational Shell | `apps/desktop/src/renderer/` | `KEEP` | **S3** | `apps/desktop/src/renderer/shell/` |
| **3.10**| Universal ChatInput & Mode Pages | `apps/desktop/src/renderer/` | `KEEP` | **S3** | `screens/Modes/` |
| **4.1** | Project Workspaces & Metadata | `apps/desktop/screens/Projects`| `KEEP` | **S3** | `apps/desktop/src/renderer/screens/Projects.tsx` |
| **4.2** | Human Approval Card & Gate Queue | `core/security/approval.py` | `INTEGRATE` | **S3** | `components/ApprovalCard.tsx` |
| **4.3** | Live Sidecar Health & Telemetry | `apps/desktop/src/renderer/` | `KEEP` | **S3** | `tests/test_desktop_shell.py` |
| **4.4** | Unified Settings UI | `apps/desktop/screens/Settings`| `KEEP` | **S3** | `apps/desktop/src/renderer/screens/Settings.tsx` |
| **5A.1**| MCP Client & Server Protocol | `core/mcp/` | `KEEP` | **S3** | `tests/test_mcp.py` |
| **5B.1**| Collaborative Room-to-Project Map | `core/teams/rooms.py` | `INTEGRATE` | **S3** | `tests/test_rooms.py` |
| **5B.2**| Room Roles & SQLite RBAC | `core/teams/governance.py` | `INTEGRATE` | **S3** | `tests/test_rooms.py` |
| **5B.3**| Room Task State Engine & REST | `core/teams/tasks.py` | `INTEGRATE` | **S3** | `tests/test_rooms.py` |
| **5C.1**| Slack In-Tree Channel Adapter | `core/channels/slack.py` | `KEEP` | **S3** | `tests/test_channel_adapters.py` |
| **5C.2**| Teams In-Tree Channel Adapter | `core/channels/teams.py` | `KEEP` | **S3** | `tests/test_channel_adapters.py` |
| **5C.3**| Discord In-Tree Channel Adapter | `core/channels/discord.py` | `KEEP` | **S3** | `tests/test_channel_adapters.py` |
| **5C.4**| Mattermost Channel Adapter | `core/channels/mattermost.py`| `KEEP` | **S3** | `tests/test_channel_adapters.py` |
| **6.1** | Multi-Tool Skill Discovery | `core/skills/discovery.py` | `KEEP` | **S3** | `tests/test_skills.py` |
| **6.2** | Skill Editor & Validation API | `core/skills/editor.py` | `KEEP` | **S3** | `tests/test_skills.py` |
| **6.3** | Skill Collections & Full-Text Search| `core/skills/collections.py`| `KEEP` | **S3** | `tests/test_skills.py` |
| **6.4** | Skill Registry Client & Safety Scan | `core/skills/registry.py` | `KEEP` | **S3** | `tests/test_skills.py` |
| **6.5** | Remote Skill Discovery & Desktop UI | `apps/desktop/screens/Skills` | `KEEP` | **S3** | `tests/test_skills.py` |
| **7.1** | Workflow Schema & DAG Parser | `core/workflows/compiler.py` | `INTEGRATE` | **S3** | `tests/test_workflows.py` |
| **7.2** | Workflow Storage & REST Endpoints | `core/storage/workflows.py` | `INTEGRATE` | **S3** | `tests/test_workflows.py` |
| **7.3** | Approval Gates (Pause/Resume/Redirect)| `core/workflows/gates.py` | `INTEGRATE` | **S3** | `tests/test_workflows.py` |
| **7.4** | Swarm Dashboard (Screen 4 `/swarm`) | `apps/desktop/screens/Swarm` | `KEEP` (UI) / `REFACTOR` (Runtime) | **S2** (UI) / **S1** (Stub) | `tests/test_workflows.py` |
| **7.5** | Visual Workflow Builder (Screen 5 `/workflows`)| `apps/desktop/screens/Workflows` | `KEEP` (UI) / `REFACTOR` (Runtime) | **S2** (UI) / **S1** (Stub) | `tests/test_workflows.py` |

---

## 3. Legacy Planned Work Inventory (Phases 8.1 – 15.x)

The legacy roadmap contained planned but unimplemented phases. These were never coded and are mapped into the canonical roadmap as follows:

| Legacy Scope | Original Description | Canonical Release Destination | Disposition / Rationale |
|---|---|---|---|
| **Phase 8** | Advanced Memory, Hybrid RAG, Knowledge Ingestion | Release 0.6 / Stage R6 (Knowledge Engine) | `ABSORBED INTO R6`: Unimplemented in legacy tree; slated for canonical Knowledge Engine. |
| **Phase 9** | Unified Audit Telemetry & Spend Analytics | Release 0.5 / Stage R1 & R2 | `ABSORBED INTO R1 / R2`: Core execution ledger in R1 and security audit in R2. |
| **Phase 10** | Dynamic Architecture Visualizer | Release 0.9 / Stage R11 | `DEFERRED`: Advanced visual diagnostics deferred past founder MVP. |
| **Phase 11** | Enterprise Multi-User, Tenancy, RBAC | Release 1.5 / Stage R16 (Business Edition) | `ABSORBED INTO R16`: Multi-tenancy deferred to enterprise business release. |
| **Phase 12** | Public Skill & Agent Package Registry | Release 1.0 / Stage R13 (Package Model & Marketplace) | `ABSORBED INTO R13`: Marketplace model scheduled for 1.0 Local-First Stable. |
| **Phase 13** | Kubernetes SaaS Cluster & Cloud Sync | Release 3.x / Stage R17 (Enterprise Cloud) | `ABSORBED INTO R17`: Cloud infrastructure out of scope for local-first MVP. |
| **Phase 14** | Enterprise Compliance & Security Hardening | Release 1.5 / Stage R16 | `ABSORBED INTO R16`: Enterprise compliance suites deferred to Business edition. |
| **Phase 15** | Production Operations & Package Installers | Release 1.0 / Stage R14 | `ABSORBED INTO R14`: Packaged installers slated for 1.0 release gate. |

---

## 4. Canonical Task Tracking Matrix (Stage R0 — Architecture Rebaseline)

```yaml
- id: R0.1
  title: "Archive the legacy roadmap"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: ARCHIVE
  owner: "Architecture"
  depends_on: []
  evidence: ["docs/archive/ROADMAP_LEGACY.md with superseded banner", "Commit e63892f"]
  notes: "Completed and checkpoint committed."

- id: R0.2
  title: "Create canonical architecture document set"
  task_status: done
  capability_maturity: "N/A (Specification)"
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.1]
  evidence: ["docs/PRODUCT.md", "docs/ARCHITECTURE.md", "docs/STATUS.md", "docs/EXECUTION_MODEL.md", "docs/SECURITY.md", "docs/DATA_MODEL.md", "docs/RELEASE_GATES.md", "docs/INTEGRATIONS.md", "docs/CAPABILITY_PACKS.md"]
  notes: "Canonical specifications created and cross-referenced."

- id: R0.3
  title: "Build legacy capability inventory"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: INTEGRATE
  owner: "Architecture"
  depends_on: [R0.2]
  evidence: ["docs/STATUS.md Section 2 (Phases 0-7.5) & Section 3 (Phases 8-15)"]
  notes: "All 35 implemented tasks mapped; unimplemented 8-15 mapped to canonical releases."

- id: R0.4
  title: "Freeze canonical domain vocabulary"
  task_status: done
  capability_maturity: "N/A (Specification)"
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.2]
  evidence: ["docs/DATA_MODEL.md", "docs/ARCHITECTURE.md Section 5"]
  notes: "Definitions frozen for Project, Session, Execution, Job, Workflow, Skill, Agent, Team, Artifact."

- id: R0.5
  title: "Establish ADR process & ADR-016"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.2, R0.4]
  evidence: ["docs/ADR/TEMPLATE.md", "docs/ADR/016-single-execution-kernel-invariant.md", "docs/ADR/README.md"]
  notes: "ADR-016 defines single execution kernel invariant."

- id: R0.6
  title: "Dependency, provenance and license inventory"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: NEW
  owner: "Architecture"
  depends_on: []
  evidence: ["docs/DEPENDENCY_AND_LICENSE_INVENTORY.md"]
  notes: "Python, TS, and Rust dependencies audited. Weak copyleft (MPL-2.0) documented."

- id: R0.7
  title: "Replace test-count completion gates"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: REFACTOR
  owner: "Architecture"
  depends_on: [R0.3]
  evidence: ["docs/RELEASE_GATES.md"]
  notes: "Replaced fixed numerical gates with named behavioral and release verification suites."

- id: R0.8
  title: "Verify reported legacy Phase 7 completion"
  task_status: done
  capability_maturity: "N/A (Governance)"
  migration: INTEGRATE
  owner: "Architecture"
  depends_on: [R0.3]
  evidence: ["docs/reviews/PHASE_7_CANONICAL_INTEGRATION_REVIEW.md"]
  notes: "Comprehensive ground-truth audit of Phase 7 source code completed and documented."
```

---

## 5. Canonical Task Tracking Matrix (Stage R1 — Execution Kernel Convergence)

```yaml
- id: R1.1
  title: "Canonical Execution domain"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Execution Kernel"
  depends_on: [R0.4]
  evidence:
    - "core/execution/models.py"
    - "core/storage/base.py"
    - "core/storage/sqlite.py"
    - "alembic/versions/003_canonical_executions.py"
    - "tests/test_execution_models.py"
    - "tests/test_execution_storage.py"
  notes: "Execution, ExecutionRequest, ExecutionContext, ExecutionResult, ExecutionEvent defined with immutable IDs and SQLite/Alembic persistence."

- id: R1.2
  title: "Execution state machine"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Execution Kernel"
  depends_on: [R1.1]
  evidence:
    - "core/execution/state.py"
    - "tests/test_execution_state_machine.py"
  notes: "Deterministic transition graph with strict VerificationResult guard on COMPLETED state, invalid transition rejection, and append-only state change events."

- id: R1.3
  title: "ExecutionCoordinator service"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Execution Kernel"
  depends_on: [R1.1, R1.2]
  evidence:
    - "core/execution/coordinator.py"
    - "core/execution/__init__.py"
    - "tests/test_execution_coordinator.py"
  notes: "Universal 10-phase execution coordinator integrating context building, routing, safety policy pre-flight, budget check, consequential gating, verification, and telemetry."

- id: R1.4
  title: "Rewire chat to real execution"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Execution Kernel"
  depends_on: [R1.3]
  evidence:
    - "services/python/server/api.py"
    - "core/execution/coordinator.py"
    - "tests/test_chat_execution_integration.py"
  notes: "Eliminated all test-trigger/fake-success routes in chat completions. Wired POST /v1/chat/completions directly through ExecutionCoordinator with strict fail-closed decoupled HTTP status codes (503/403/504/502/400) / error SSE handling and deterministic-first routing with quality-adjusted cost routing."

- id: R1.5
  title: "Real provider/model resolution"
  task_status: done
  capability_maturity: S1
  migration: INTEGRATE
  owner: "Execution Kernel"
  depends_on: [R1.3]
  evidence:
    - "core/router/model_router.py"
    - "core/execution/coordinator.py"
    - "tests/test_router_hardening.py"
    - "tests/test_chat_execution_integration.py"
  notes: "Implemented ResolvedModel dataclass, model resolution by tier/preference, circuit breaker status checking, and transparent fallback recording with ROUTING_RESOLVED events."

- id: R1.6
  title: "Canonical project context"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Execution Kernel"
  depends_on: [R1.1]
  evidence:
    - "core/projects/models.py"
    - "core/storage/base.py"
    - "core/storage/sqlite.py"
    - "alembic/versions/004_canonical_projects.py"
    - "services/python/server/api.py"
    - "tests/test_chat_execution_integration.py"
  notes: "Created canonical Project domain model, SQLite persistence with auto-seeded default workspace (proj_default, is_default=1), full REST CRUD endpoints (/v1/projects), context assembly injection, and cross-project session isolation enforcement."

- id: R1.7
  title: "Bounded real conversation history"
  task_status: done
  capability_maturity: S1
  migration: INTEGRATE
  owner: "Execution Kernel"
  depends_on: [R1.3, R1.6]
  evidence:
    - "core/execution/coordinator.py"
    - "tests/test_r1_reconciliation.py"
    - "tests/test_chat_execution_integration.py"
  notes: "Implemented bounded conversation history budget allocation: current prompt and project instructions are protected from eviction. History is capped to min(token_budget // 2, remaining_budget) preserving chronological order of retained turns, with full audit provenance (history_truncated, total_available_turns, retained_turns_count, dropped_turns_count, history_tokens, prompt_tokens, instruction_tokens, token_budget)."

- id: R1.8
  title: "Real streaming"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Execution Kernel"
  depends_on: [R1.3, R1.4]
  evidence:
    - "services/python/server/api.py"
    - "core/execution/coordinator.py"
    - "tests/test_r1_reconciliation.py"
  notes: "Implemented genuine real-time incremental provider streaming over bounded queues (maxsize=1000) with backpressure and client disconnect cancellation. Eliminated SQLite write amplification for transient token deltas/output chunks while forwarding live SSE chunks. Assistant message persisted to UnifiedSessionStore exactly once upon stream completion, with structured domain error codes on mid-stream failure."

- id: R1.9
  title: "Real cancellation"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Execution Kernel"
  depends_on: [R1.8]
  evidence:
    - "core/execution/cancellation.py"
    - "core/execution/coordinator.py"
    - "services/python/server/api.py"
    - "tests/test_cancellation.py"
  notes: "Implemented canonical CancellationToken primitive with cancellation reason/actor/timestamp metadata, cooperative generator cancellation via aclose()/close(), process termination registry with cross-platform termination contract (graceful termination -> bounded wait -> force termination using platform-appropriate process semantics), REST cancellation API endpoints (POST /v1/executions/{id}/cancel, GET /v1/executions/{id}, GET /v1/executions/{id}/events), SSE cancellation events, zero chunk emission after cancellation, strict terminal state immutability, and guarantee of zero assistant turn persistence to UnifiedSessionStore on cancelled executions."

- id: R1.10
  title: "Execution artifact model"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Execution Kernel"
  depends_on: [R1.1]
  evidence:
    - "core/artifacts/models.py"
    - "core/artifacts/service.py"
    - "core/artifacts/storage.py"
    - "core/artifacts/__init__.py"
    - "core/storage/base.py"
    - "core/storage/sqlite.py"
    - "alembic/versions/005_canonical_artifacts.py"
    - "services/python/server/api.py"
    - "tests/test_artifacts.py"
  notes: "Implemented canonical Artifact domain model (art_<hex12> ID, project_id, execution_id, type, mime_type, storage_kind, file_path, inline_content, sha256_hash, size_bytes, status, lineage, created_by, created_at) with ArtifactPayloadStore abstraction, tombstone deletion preservation (status=deleted, deleted_at=<timestamp>, payload removed), managed filesystem root with path traversal and symlink escape detection. Enforced automatic storage tiering, cryptographic SHA-256 integrity verification, project-scope integrity verification, partial-output artifact creation on cancellation with ARTIFACT_CREATED durable events, Alembic migration 005_canonical_artifacts, and complete REST API CRUD and content streaming endpoints."

- id: R1.11
  title: "Execution ledger"
  task_status: done
  capability_maturity: S1
  migration: INTEGRATE
  owner: "Execution Kernel"
  depends_on: [R1.3, R1.10]
  evidence:
    - "core/ledger/models.py"
    - "core/ledger/service.py"
    - "core/ledger/__init__.py"
    - "services/python/server/api.py"
    - "tests/test_ledger.py"
  notes: "Implemented authoritative Execution Ledger read-side projection answering 'what actually happened during this execution?' without duplicate write tables. Assembles immutable ExecutionTrace from executions, execution_events, cost_records, and artifacts. Projects requested vs resolved vs actual model/provider, runtime fallback history, context provenance (project_root, instructions SHA-256 hash without secret leakage, turn statistics), tool invocations, approval gates, artifact references, usage/cost accounting with provenance (calculated, estimated, provider_reported, unavailable), verification outcomes, and strictly monotonic durable event sequences. Exposes REST endpoints (GET /v1/executions/{id}/trace with project-scope integrity and GET /v1/projects/{id}/executions with pagination). 15/15 behavioral tests passing."
- id: R1.12
  title: "Rewire DSPy pipeline registry"
  task_status: done
  capability_maturity: S1
  migration: INTEGRATE
  owner: "Execution Kernel"
  depends_on: [R1.3]
  evidence:
    - "core/execution/kernel_lm_adapter.py"
    - "core/execution/coordinator.py"
    - "core/pipelines/registry.py"
    - "services/python/server/api.py"
    - "core/ledger/models.py"
    - "core/ledger/service.py"
    - "tests/test_pipeline_kernel_integration.py"
    - "tests/test_pipeline_registry.py"
  notes: "Eliminated all direct bypass routes for DSPy pipelines in accordance with ADR-016. Implemented KernelLMAdapter (dspy.LM) to authoritatively intercept all internal DSPy LM calls into ModelRouter, enforcing cancellation checks, token and cost accounting, and model call provenance. Rewired PipelineRegistry.run to route exclusively through ExecutionCoordinator.execute with execution_id generation and synchronous/asynchronous safety bridges. Rewired POST /v1/pipelines/{name}/run to return canonical execution_id and record durable execution records. Enforced Single Root Execution Invariant (zero shadow executions for multi-hop DSPy programs), policy pre-flight and guardrails, budget limits, cancellation with partial artifact preservation, completed artifact registration (PATCH, DATA, CODE), and ExecutionLedgerService trace projection with pipeline identity provenance. 16/16 new integration tests passing, 475/475 full regression suite passing."
- id: R1.13
  title: "Rewire skills and adapters"
  task_status: done
  capability_maturity: S1
  migration: INTEGRATE
  owner: "Execution Kernel"
  depends_on: [R1.3]
  evidence:
    - "core/skills/models.py"
    - "core/skills/boundary.py"
    - "core/skills/discovery.py"
    - "core/execution/coordinator.py"
    - "services/python/server/api.py"
    - "server/mcp_server.py"
    - "core/ledger/models.py"
    - "core/ledger/service.py"
    - "core/safety/policy.py"
    - "core/artifacts/models.py"
    - "tests/test_skills_kernel_integration.py"
    - "tests/test_skills.py"
    - "tests/test_adapters.py"
    - "tests/test_templates.py"
  notes: "Eliminated all direct bypass execution routes for skills and external agent adapters in accordance with ADR-016. Integrated MultiToolSkillDiscovery and AdapterRegistry authoritatively into ExecutionCoordinator. Implemented canonical capability boundaries (CapabilityBoundary) with strict filesystem project containment and constrained subprocess boundary execution. Governed skill/adapter executions under kernel budget limits, policy pre-flight, consequential operation staging gates, prompt cancellation, and independent ToolInvocationRecord tracking. Preserved skill output artifacts (PATCH for diffs, CODE for scripts/fixes) in ArtifactService. Rewired REST endpoints (POST /v1/skills, POST /v1/adapters/{id}/execute, POST /v1/adapters/{id}/stream) and MCP tool execute_skill_template through the coordinator with truthful failure propagation and zero fake success. 18/18 new integration tests passing, 497/497 full regression suite passing."
- id: R1.14
  title: "Split monolithic API by domain"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Execution Kernel"
  depends_on: [R1.3]
  evidence:
    - "services/python/server/routers/__init__.py"
    - "services/python/server/routers/adapters.py"
    - "services/python/server/routers/artifacts.py"
    - "services/python/server/routers/chat.py"
    - "services/python/server/routers/collaboration.py"
    - "services/python/server/routers/credentials.py"
    - "services/python/server/routers/executions.py"
    - "services/python/server/routers/ledger.py"
    - "services/python/server/routers/memory.py"
    - "services/python/server/routers/models.py"
    - "services/python/server/routers/patches.py"
    - "services/python/server/routers/pipelines.py"
    - "services/python/server/routers/policies.py"
    - "services/python/server/routers/projects.py"
    - "services/python/server/routers/skills.py"
    - "services/python/server/routers/swarm.py"
    - "services/python/server/routers/system.py"
    - "services/python/server/routers/tasks.py"
    - "services/python/server/routers/telemetry.py"
    - "services/python/server/routers/workflows.py"
    - "services/python/server/app.py"
    - "services/python/server/container.py"
    - "services/python/server/schemas.py"
    - "services/python/server/errors.py"
    - "services/python/server/transport.py"
    - "services/python/server/dependencies.py"
    - "services/python/server/api.py"
    - "tests/test_api_domain_decomposition.py"
  notes: "Decomposed the monolithic services/python/server/api.py (5,683 lines, 161 route handlers) into 19 coherent domain routers under services/python/server/routers/. Established AppServices centralized dependency container in container.py with lazy accessors and test injection hooks, canonical domain error translation in errors.py, SSE streaming transport helpers in transport.py, IPC security verifiers in dependencies.py, and all 139 Pydantic schemas in schemas.py. Constructed create_app() application factory in app.py mounting all 19 domain routers under /v1 and root liveness probe at /healthz. Refactored api.py into a lightweight 345-line backward-compatible facade with zero route decorators and zero business logic. 25/25 dedicated domain decomposition tests passing, 522/522 full regression suite passing."
- id: R2.1
  title: "Mandatory local IPC authentication"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Authorization"
  depends_on: [R1.3]
  evidence:
    - "services/python/server/dependencies.py"
    - "services/python/server/app.py"
    - "tests/test_r2_ipc_authentication.py"
  notes: "Implemented IPCTokenManager enforcing fail-closed local IPC authentication. Auto-generates cryptographically secure 256-bit per-launch tokens with POSIX 0600 file permissions (~/.agent_engine/ipc.token and data/ipc.token) when unconfigured in environment. Enforces constant-time HMAC comparison (hmac.compare_digest) across Authorization: Bearer, X-IPC-Token headers, and token query parameters. Wired verify_ipc_token as mandatory FastAPI dependency across all domain routers under /v1, ensuring unauthenticated or wrong-token callers receive HTTP 401 Unauthorized with WWW-Authenticate header. Preserved minimal unauthenticated liveness endpoint at /healthz. 9/9 dedicated security tests passing, 539/539 full regression suite passing."
- id: R2.2
  title: "Origin/CORS hardening"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Authorization"
  depends_on: [R2.1]
  evidence:
    - "services/python/server/app.py"
    - "tests/test_r2_ipc_authentication.py"
  notes: "Hardened CORSMiddleware configuration in create_app() composition root. Replaced legacy wildcard access with explicit whitelist of trusted Tauri and desktop shell origins (tauri://localhost, http://tauri.localhost, https://tauri.localhost, http://localhost:1420, http://127.0.0.1:1420, http://localhost:5173, http://127.0.0.1:5173, http://localhost:3000, http://127.0.0.1:3000) and strict loopback regex (^https?://(localhost|127\\.0\\.0\\.1)(:\\d+)?$). Verified arbitrary external web origins (e.g. malicious-website.com) are rejected without access-control-allow-origin headers."
```

---

## 6. Active Test Suite & Deprecation Warnings Log

- **Full Regression Suite:** `539 passed in 78.14s` (`uv run pytest`)
- **R2 IPC Authentication & CORS Suite:** `9 passed in 4.24s` (`uv run pytest tests/test_r2_ipc_authentication.py`)
- **Hard-Exit Truth Verification Suite:** `8 passed in 4.00s` (`uv run pytest tests/test_r1_hard_exit_truth.py`)
- **API Domain Decomposition Suite:** `25 passed in 10.44s` (`uv run pytest tests/test_api_domain_decomposition.py`)
- **Router Hardening & Outage Fallback Suite:** `7 passed in 3.99s` (`uv run pytest tests/test_router_hardening.py`)
- **Skills & Adapters Kernel Integration Suite:** `18 passed in 5.77s` (`uv run pytest tests/test_skills_kernel_integration.py`)
- **Legacy Skills, Adapters & Pipelines Compatibility Suite:** `65 passed in 13.33s` (`uv run pytest tests/test_skills.py tests/test_adapters.py tests/test_templates.py tests/test_pipeline_kernel_integration.py`)
- **Pipeline & Execution Kernel Core Suite:** `72 passed in 15.44s` (`uv run pytest tests/test_pipeline_kernel_integration.py tests/test_pipeline_registry.py tests/test_cancellation.py tests/test_artifacts.py tests/test_ledger.py`)
  - **Pipeline Kernel Integration Suite:** `16 passed in 8.55s` (`uv run pytest tests/test_pipeline_kernel_integration.py`)
  - **Pipeline Registry Suite:** `6 passed in 4.45s` (`uv run pytest tests/test_pipeline_registry.py`)
  - **Cancellation Suite:** `17 passed in 7.35s` (`uv run pytest tests/test_cancellation.py`)
  - **Artifacts Suite:** `15 passed in 6.95s` (`uv run pytest tests/test_artifacts.py`)
  - **Ledger Suite:** `18 passed in 6.00s` (`uv run pytest tests/test_ledger.py`)
- **Desktop Tauri & Frontend Workspace:**
  - `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml`: passed (`0.58s`)
  - `pnpm -r build`: passed (`11.2s`)
- **Documented Upstream Warnings (Non-blocking):**
  1. `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` (Origin: `fastapi/testclient.py:1` — Upstream FastAPI/Starlette testclient deprecation notice; non-runtime).
  2. `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.` (Origin: `starlette/testclient.py:53` — Upstream Starlette/AnyIO import alias notice; non-runtime).
  3. `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead` (Origin: `chromadb/telemetry/opentelemetry/__init__.py:128` — Upstream ChromaDB telemetry compatibility notice for Python 3.16+; non-blocking on current Python 3.10–3.14).






