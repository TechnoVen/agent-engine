# Agent Engine — Canonical Implementation Status & Capability Matrix

> **Status:** Authoritative Implementation Reality  
> **Updated:** October 7, 2026 (Milestone R2 Formally Closed at S1 per CTO Review)  
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
```

---

## 6. Canonical Task Tracking Matrix (Stage R2 — Security, Authorization & Recovery)

> **Milestone Status:** S1 — Implemented and implementation-tested  
> **0.5 Hard-Exit Gate:** PASSED (R2.1–R2.12 completed for 0.5 security scope; R2.13 deferred to 1.0 release-trust scope)  
> **Verification Evidence:** 808 full regression tests passed, 274 combined R2 security tests passed across 11 suites, 3 known upstream warnings, 0 new unexplained/project-owned warnings  

```yaml
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
    - "apps/desktop/src/renderer/api/client.ts"
    - "core/diagnostics.py"
    - "tests/test_r2_ipc_authentication.py"
  notes: "Implemented IPCTokenManager enforcing fail-closed local IPC authentication. Auto-generates cryptographically secure 256-bit per-launch tokens with POSIX 0600 and Windows user-only ACL permissions at authoritative path ~/.agent_engine/ipc.token, registered with cleanup_handshake_file() and atexit. Enforces constant-time HMAC comparison (hmac.compare_digest) strictly via Authorization: Bearer and X-IPC-Token headers, explicitly rejecting query parameter tokens to prevent URL leakage. Frontend client.ts holds token in-memory only (zero localStorage). Redacts sensitive headers in logs and diagnostics. 14/14 dedicated security tests passing."
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
  notes: "Hardened CORSMiddleware in create_app(). Split into strict production policy (tauri://localhost, http://tauri.localhost, https://tauri.localhost) and development policy (Vite/Tauri ports 1420, 5173, 3000 and loopback regex). External origins (e.g. evil.com) fail closed. Hardened /healthz to minimal non-sensitive liveness info."
- id: R2.3
  title: "Mandatory backend policy boundary"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Authorization"
  depends_on: [R1.3]
  evidence:
    - "core/safety/policy.py"
    - "core/execution/coordinator.py"
    - "core/execution/state.py"
    - "tests/test_r2_policy_and_approvals.py"
  notes: "Wired PolicyEngine authoritatively into Phase 4 and Phase 6 of ExecutionCoordinator.execute(). Enforces declarative guardrails, dynamic risk scoring, automatic permission inference for consequential capabilities (DESTRUCTIVE, FINANCIAL, ADMIN), and C6 high-risk staging. All execution surfaces (chat, DSPy, skills, adapters, pipelines) evaluate policy before execution. Policy DENY/BLOCK halts pre-flight with ExecutionStatus.BLOCKED and error_code='POLICY_BLOCKED'. Staged actions transition to WAITING_FOR_APPROVAL and emit APPROVAL_REQUIRED. Policy evaluation errors fail closed (1.0 risk score, critical level, blocked). Frontend-supplied claims (approved=true, allow_high_risk=true) are ignored by the backend."
- id: R2.4
  title: "Exact-operation approval tokens"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Authorization"
  depends_on: [R2.3]
  evidence:
    - "core/safety/pending.py"
    - "core/execution/coordinator.py"
    - "core/ledger/models.py"
    - "core/ledger/service.py"
    - "core/storage/sqlite.py"
    - "core/skills/boundary.py"
    - "docs/SECURITY.md"
    - "tests/test_r2_policy_and_approvals.py"
  notes: "Implemented cryptographic, single-use exact-operation authorization with durable SQLite persistence (`approvals` table) and database-level Compare-And-Swap (`atomic_consume_approval`). Enforces 60-second TTL expiration window, deterministic canonical argument digest (`compute_canonical_operation_digest` via recursive sorted normalization, path canonicalization, command parsing, and SHA-256), exact tool/capability binding, and actor attribution ('local_operator'). Tokens are verified via SHA-256 verifiers; raw bearer secrets are never stored in memory, DB, or ledger. Reconstructed ApprovalRecord in ledger records request, decision, actor, digest, and consumed status. Passed all 15 CTO Review Section 12 security closure scenarios."
- id: R2.5
  title: "Canonical workspace path enforcement"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Authorization"
  depends_on: [R2.3, R2.4]
  evidence:
    - "core/skills/path.py"
    - "core/skills/boundary.py"
    - "core/skills/models.py"
    - "core/execution/coordinator.py"
    - "tests/test_r2_workspace_paths.py"
  notes: "S1 — implemented and implementation-tested. Implemented canonical path resolution + scope containment + symlink validation + immediate pre-side-effect revalidation adhering to all CTO design corrections. Established ResolvedWorkspacePath canonical PathLike value object, trusted workspace scope hierarchy (effective = project_root ∩ union(capability_scopes) ∩ union(policy_scopes) ∩ optional_caller_narrower_scope) with caller-narrowing-only semantics (widening attempts ignored fail-closed, empty authority fails closed), parent-chain validation for non-existent targets, internal symlink destination binding, immediate pre-side-effect TOCTOU revalidation, cross-platform path semantics implemented and tested at unit level, immutable project identity (project_id) binding preventing cross-project authorization reuse, null-byte rejection fail-closed, and machine path redaction in public traces. 24/24 dedicated security test scenarios passing, full regression suite passing."
- id: R2.6
  title: "Secrets service and runtime injection"
  task_status: done
  capability_maturity: S1
  migration: EXPAND
  owner: "Security & Authorization"
  depends_on: [R2.1]
  evidence:
    - "core/security/secrets.py"
    - "core/security/credentials.py"
    - "core/security/__init__.py"
    - "core/models.py"
    - "core/router/model_router.py"
    - "services/python/server/routers/credentials.py"
    - "tests/test_r2_secrets_service.py"
  notes: "S1 — implemented and implementation-tested. Unified credential and secrets subsystem into SecretsService. Implemented strong value object isolation: SecretReference (public), SecretMetadata (masked public), SecretValue (transient internal container with str/repr/format returning '***', reveal() strictly scoped, and wipe() zeroing). Storage hierarchy prioritizes OS Keychain with hardened AES-256-GCM EncryptedVault fallback. Eliminated weak machine identifiers; vault uses 256-bit high-entropy key via AGENT_ENGINE_VAULT_KEY or vault.key with 0600 POSIX permissions. Added automatic transparent migration for existing legacy vaults. Permanently eliminated plaintext reveal APIs (reveal=true rejected with 403 Forbidden). Implemented backend-only connection testing. Completely eliminated global os.environ pollution from core/models.py and model_router.py; API keys injected directly into dspy.LM and child subprocess invocation environments. Enforced consumer authorization and project scope isolation. 30/30 dedicated security test scenarios passing, full regression passing."
- id: R2.7
  title: "Untrusted-content labeling and prompt-injection controls"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Security & Prompt Architecture"
  depends_on: [R1.7, R2.3]
  evidence:
    - "core/context/models.py"
    - "core/context/builder.py"
    - "core/context/__init__.py"
    - "core/skills/boundary.py"
    - "tests/test_r2_prompt_injection.py"
  notes: "S1 — implemented and implementation-tested. Established machine-readable ContentTrust / ContentAuthority separation + backend authorization boundary + untrusted content remains EVIDENCE (ContentTrust: SYSTEM, TRUSTED_USER, INTERNAL_STATE, UNTRUSTED_CONTENT; ContentAuthority: SYSTEM_POLICY, USER_DIRECTIVE, EVIDENCE). Enforced strict inviolable security invariant: untrusted content can never claim or exercise SYSTEM_POLICY or USER_DIRECTIVE authority (raises ValueError fail-closed). Structured envelopes (<<<BEGIN_UNTRUSTED_EXTERNAL_DATA>>> / <<<END_UNTRUSTED_EXTERNAL_DATA>>>) serve as defense-in-depth with mandatory delimiter escaping, zero-width Unicode smuggling sanitization, and role spoofing neutralization (prepending [DATA] to simulated system/human/assistant turns); delimiters alone do not prevent injection without the backend authorization boundary. ContextBuilder enforces automatic enveloping for untrusted fields, RAG retrievals, and untrusted inputs. Defends across 26 comprehensive adversarial scenarios (jailbreaks, fake approvals, fake policies, path escapes, delimiter breakouts, secret exfiltration, token exhaustion DoS, external API downgrades, RAG metadata downgrades, derived child invariance, etc.). Full backend defense-in-depth: backend capability boundary, policy engine, and secrets service fail closed regardless of LLM generation. 26/26 dedicated security test scenarios passing, 675/675 full regression passing."
- id: R2.8
  title: "Sandbox worker runtime"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Security & Sandbox Architecture"
  depends_on: [R2.5, R2.6, R2.7, R1.9, R1.10, R1.11]
  evidence:
    - "core/sandbox/models.py"
    - "core/sandbox/backend.py"
    - "core/sandbox/service.py"
    - "core/sandbox/__init__.py"
    - "tools/dev_dashboard.py"
    - "core/engine.py"
    - "tests/test_r2_sandbox_runtime.py"
    - "tests/test_sandbox.py"
  notes: "S1 — implemented and implementation-tested. Delivered container-isolated Sandbox Worker Runtime with complete Closure Pass hardening. Established SandboxSpec, SandboxResult, SandboxFilesystemGrant, SandboxMount, SandboxNetworkGrant, and SandboxExecutionRecord. Implemented explicit mount modes (READ_ONLY, READ_WRITE, OUTPUT_ONLY, SCRATCH) with project workspaces mounted READ_ONLY by default. Implemented LinuxBubblewrapBackend utilizing Linux Bubblewrap (bwrap) unprivileged user namespaces (--unshare-all, --unshare-net, --clearenv, --die-with-parent, /proc, /dev, minimal system ro-binds, private HOME=/tmp/home, TMPDIR=/tmp, XDG_RUNTIME_DIR=/tmp/run; host /home, /run, /var, root /etc never mounted). Enforced default-deny network isolation and default-deny environment allowlisting (zero host env leakage; IPC token, vault keys, and ambient API keys strictly excluded). Enforced execution- and capability-bound secret grants (consumer_id = sandbox:<project_id>:<execution_id>:<capability_id>) with zero-secrets default and automatic redaction from stdout, stderr, and untrusted ContextItem evidence. Probed bwrap from trusted system paths (/usr/bin/bwrap, /bin/bwrap) with minimal unprivileged user namespace testing. Integrated R2.5 canonical workspace containment and symlink escape prevention. Integrated R2.7 by classifying worker stdout/stderr and output files as UNTRUSTED_CONTENT / EVIDENCE via ContextItem. Integrated R1.9 CancellationToken process lifecycle termination cleaning the entire process tree via os.killpg. Integrated R1.10 artifact brokering with strict regular-file, size, and symlink containment validation. Implemented fail-closed platform backend strategy (DarwinSandboxBackend, WindowsSandboxBackend fail closed with SandboxUnavailableError; zero host fallback). Remediated in-process execution: replaced eval() in calculator_tool with safe AST parser; replaced Streamlit dev_dashboard in-process exec() with SandboxService. 26/26 dedicated security scenarios passing, 705/705 full regression passing."
- id: R2.9
  title: "Sandbox resource limits"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Security & Sandbox Architecture"
  depends_on: [R2.8]
  evidence:
    - "core/sandbox/models.py"
    - "core/sandbox/backend.py"
    - "core/sandbox/service.py"
    - "core/sandbox/__init__.py"
    - "tests/test_r2_sandbox_resource_limits.py"
  notes: "S1 — implemented and implementation-tested. Fully addressed all CTO Review corrections: (1) Bubblewrap genuine network isolation: default DENY unshares net namespace; ALLOW_UNRESTRICTED passes --share-net when authorized by policy (authorized_by_policy=True), verified by real TCP loopback canary. (2) Parent admission capacity (max_concurrent_sandboxes, max_total_memory_bytes) strictly separated from worker runtime limits, mapping to SandboxStatus.BLOCKED with typed reasons CONCURRENCY_CAPACITY_EXCEEDED and MEMORY_CAPACITY_EXCEEDED. (3) Eliminated unsafe Python preexec_fn; RLIMIT_CPU enforced via trusted prlimit wrapper in transient systemd scope. (4) Documented S1 test-evidence classification matrix (UNIT, CONTRACT, REAL_LINUX_INTEGRATION). (5) Async cancellation through to_thread reliably terminates child OS process group and transient scope without orphans. (6) Kernel resource evidence captured strictly before scope destruction; non-OOM SIGKILL classified as BACKEND_ERROR. (7) Default resource profile stable identifier untrusted_default_v1 with concrete values documented. 38/38 dedicated resource limit precision tests passing, 721/721 full regression passing."
- id: R2.10
  title: "Safe staged patch application"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Control Plane Architecture"
  depends_on: [R2.5]
  evidence:
    - "core/patch/models.py"
    - "core/patch/service.py"
    - "core/patch/__init__.py"
    - "tests/test_r2_patch_service.py"
  notes: "S1 — implemented and implementation-tested. Delivered Safe Staged Patch Application subsystem honoring core invariant: Agent Engine never overwrites newer human edits. (1) Canonical PatchOperation model supporting CREATE, UPDATE, DELETE with explicit expected-state (exists + content_hash) and proposed-state definitions. (2) Strict distinction between absent file (exists=False, hash=None) and empty file (exists=True, hash='e3b0c44...'). (3) Cryptographic byte hashing (SHA-256) over exact file bytes on disk without normalization. (4) Exact approval digest binding covering project, path, op, expected hash, and proposed hash. (5) Immediate pre-commit revalidation. (6) Linux renameat2(RENAME_NOREPLACE) for CREATE and atomic os.replace for UPDATE with POSIX directory fsync. (7) Durable crash recovery journal and operation-scoped backup (.ae_patch_recovery/backups/{project_id}/{op_id}.bak, 0o600). (8) Idempotent startup crash recovery. (9) In-process PatchLockManager serializing Agent Engine writers. (10) Audit-safe execution ledger (PatchExecutionRecord). 25/25 dedicated patch scenarios passing."
- id: R2.11
  title: "Checkpoint and rollback service"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Security & Control Plane Architecture"
  depends_on: [R1.10, R2.10]
  evidence:
    - "core/checkpoint/models.py"
    - "core/storage/paths.py"
    - "core/storage/__init__.py"
    - "core/patch/service.py"
    - "core/checkpoint/backends/base.py"
    - "core/checkpoint/backends/file.py"
    - "core/checkpoint/backends/git.py"
    - "core/checkpoint/backends/database.py"
    - "core/checkpoint/backends/config.py"
    - "core/checkpoint/service.py"
    - "core/checkpoint/__init__.py"
    - "tests/test_r2_checkpoint_service.py"
  notes: "S1 — implemented and implementation-tested. Completed R2.11 Final Recovery Closure: (1) Permanently removed public force=True rollback; live divergence unconditionally halts with ROLLBACK_CONFLICT. (2) Relocated checkpoint & patch recovery storage to Agent Engine private root (~/.agent_engine/checkpoints/ and ~/.agent_engine/patch_recovery/, mode 0o700/0o600), guaranteeing sandbox workers with project READ_ONLY access cannot access them. (3) Durable restore operation journal (RestoreOperation: PREPARED, RESTORING, COMPLETED, PARTIAL, CONFLICT, RECOVERY_REQUIRED, FAILED) persisted with fsync before live mutation; restart reconciliation. (4) Immediate pre-mutation resource revalidation with engine locks; truthful partial multi-resource restore reporting (PARTIAL). (5) Canonical R2.4 structured compute_rollback_approval_digest binding complete restore plan (digest_version 1, project, checkpoint, restore ID, sorted resource identities, types, paths, pre-state hashes, expected post-state hashes). (6) Checkpoint material integrity verified before mutation; tampered backup raises CheckpointIntegrityError (tested across file, config, SQLite, and Git). (7) File permission semantics: stat.S_IMODE(st_mode) & 0o777 bitmask (0600, 0644, 0755), never blanket chmod; privileged setuid/setgid bits strictly masked out; staged atomic commit uses kernel/filesystem-enforced atomic no-clobber. (8) Git bounded scope: only declared/tracked files, never .env, credentials, or untracked files; 0 remote ops. (9) SQLite restore maintenance boundary: exclusive lock, connection quiescing, WAL mode consistency. (10) Typed config serialization: SecretReference preserved, SecretValue forbidden, fail-closed on unknown objects without repr(). 35/35 dedicated precision tests passing, full regression passing."
- id: R2.12
  title: "Diagnostics redaction"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Security & Control Plane Architecture"
  depends_on: [R2.6]
  evidence:
    - "core/diagnostics/models.py"
    - "core/diagnostics/policy.py"
    - "core/diagnostics/redactor.py"
    - "core/diagnostics/exporter.py"
    - "core/diagnostics/__init__.py"
    - "tests/test_r2_diagnostics_redaction.py"
  notes: "S1 — Implemented and implementation-tested. Completed R2.12 Central Diagnostics Redaction and Export Policy: (1) Reopen-and-decompress canary verification scanning every archive member with 0 secret leaks. (2) Strict archive member security: rejected path traversals, absolute paths, non-regular members, and normalized uid/gid/mtime metadata. (3) Acyclic integrity manifest with per-member SHA-256 hashes excluding manifest.json. (4) SecretReference diagnostic minimization by default (credential_configured=True, provider=...). (5) Diagnostic egress inventory covering all 10 outward surfaces with central policy enforcement. (6) Fail-safe error handling avoiding repr()/str() on unknown objects and guarding recursion/cycles/depth. (7) Bounded collection protecting against local denial-of-service. (8) Known-root path minimization for POSIX and Windows preserving benign URLs. (9) Comprehensive seeded-canary production artifact test covering 17 vectors. 27/27 precision tests passing, full regression 808 passed."
```

---

## 7. Canonical Task Tracking Matrix (Stage R3 — Model Layer & Routing Convergence)

```yaml
- id: R3.1
  title: "Canonical provider registry contract"
  task_status: done
  capability_maturity: S1
  migration: REFACTOR
  owner: "Core & Model Architecture"
  depends_on: [R1.5, R2.6]
  evidence:
    - "core/providers/models.py"
    - "core/providers/base.py"
    - "core/providers/adapters/openai.py"
    - "core/providers/adapters/anthropic.py"
    - "core/providers/adapters/gemini.py"
    - "core/providers/adapters/ollama.py"
    - "core/providers/adapters/llamacpp.py"
    - "core/providers/adapters/compatible.py"
    - "core/providers/adapters/deepseek.py"
    - "core/providers/adapters/groq.py"
    - "core/providers/adapters/kimi.py"
    - "core/providers/registry.py"
    - "core/providers/__init__.py"
    - "core/models.py"
    - "core/router/model_router.py"
    - "core/ledger/models.py"
    - "core/ledger/service.py"
    - "core/execution/kernel_lm_adapter.py"
    - "tests/test_r3_provider_registry.py"
  notes: "S1 — Implemented and implementation-tested. Established single canonical provider contract: (1) Machine provider identity (provider_id) separated from display names, aliases, endpoints, and model catalogs. (2) Provider vs model responsibility separation: provider owns connection/auth/health/protocols; model owns reasoning/context/tokens. (3) Separated 3-dimensional health state taxonomy: ProviderConfigurationState (CONFIGURED, UNCONFIGURED, INVALID), ProviderAvailability (AVAILABLE, UNAVAILABLE, UNKNOWN), ProviderHealthStatus (HEALTHY, DEGRADED, UNHEALTHY, AUTHENTICATION_FAILED, UNKNOWN), enforcing configured != available != healthy. (4) Low-cost, strictly bounded (<= 5s) health probes querying lightweight metadata endpoints without executing LLM completions, with sanitized errors and zero secret leaks. (5) Strict R2.6 Secret Boundary: secrets resolved through SecretsService or direct call-scope parameters; 0 global os.environ pollution, 0 plaintext secrets in logs/diagnostics/dumps. (6) Pure migration idempotency (migrate(old) == migrate(canonical) == migrate(migrate(old))). (7) Alias shadow protection and normalization; generic 'local' strictly scoped as legacy migration alias. (8) RLock concurrency discipline: network I/O never held across locks. (9) Complete 9-adapter conformance suite passing identical contract (openai, anthropic, gemini, ollama, llamacpp, deepseek, groq, kimi, compatible). (10) Controlled non-sensitive endpoint_class taxonomy (cloud, local_managed, local_external, custom_remote) with zero URLs/ports/secrets in ledger evidence. 27/27 dedicated conformance tests passing, 848/848 full regression passing."

- id: R3.2
  title: "Model capability registry"
  task_status: done
  capability_maturity: S1
  migration: NEW
  owner: "Core & Model Architecture"
  depends_on: [R3.1]
  evidence:
    - "core/model_registry/__init__.py"
    - "core/model_registry/models.py"
    - "core/model_registry/catalog.py"
    - "core/model_registry/registry.py"
    - "core/models.py"
    - "tests/test_r3_model_registry.py"
  notes: "S1 — Implemented and implementation-tested. Completed Model Capability Registry (Final Capability-Truth Closure): (1) Structured ModelIdentity(provider_id, model_id) avoiding colon parsing ambiguities; versioned serialization (v1:provider:model) supporting colons, slashes, spaces, and Unicode round-trips. (2) 3-valued logic (TriStateBool: TRUE, FALSE, UNKNOWN) for capabilities and privacy facts; UNKNOWN strictly fails hard requirements (require_local_only, no_data_leaves_device, zero_retention). (3) Complete roadmap capability dimensions with per-field CapabilityFact provenance tracking; USER_OVERRIDE remains visible and never masquerades as provider-certified metadata. (4) Distinct token context limits: max_input_tokens, max_output_tokens, and max_total_context_tokens. (5) Unit-explicit (PER_1M_TOKENS) and time-aware TokenPrice; missing pricing is UNKNOWN, never zero ($0.0). (6) Latency separation: static catalog_latency_class is preserved independently from live observed telemetry metrics. (7) Privacy facts (execution_location, data_leaves_device, zero_data_retention); user override cannot downgrade cloud data_leaves_device=TRUE to FALSE. (8) Precedence force restriction: force=True is strictly rejected for untrusted callers and discovery (PermissionError). (9) Field-level provenance merging: sparse higher-precedence records do not erase known independent facts; FALSE overrides TRUE while UNKNOWN does not. (10) Conservative defaults for generic 'compatible' provider (unsupported facts remain UNKNOWN). (11) Non-routing candidate evaluation: ModelCandidate.score is deterministic metadata completeness [0.0, 1.0], no premature winner ranking. (12) Known limitation documented: 0.5 scopes 'compatible' as a single configured provider kind instance; multi-instance disambiguation requires future provider_instance_id. 16/16 precision tests passing, 851/851 full regression passing."

- id: R3.3
  title: "Resource Manager"
  task_status: done
  capability_maturity: S1
  migration: EXPAND
  owner: "Core & Host Architecture"
  depends_on: []
  evidence:
    - "core/resources/models.py"
    - "core/resources/probes/base.py"
    - "core/resources/probes/linux.py"
    - "core/resources/probes/darwin.py"
    - "core/resources/probes/windows.py"
    - "core/resources/manager.py"
    - "core/resources/__init__.py"
    - "core/telemetry/hardware.py"
    - "services/python/server/routers/telemetry.py"
    - "services/python/server/api.py"
    - "tests/test_r3_resource_manager.py"
  notes: "S1 — Implemented and implementation-tested. Completed Host Resource Manager (Final Telemetry Closure): (1) Factual, timestamped host telemetry snapshot (captured_at, platform, architecture, cpu, memory, accelerators, probe_status). (2) Honest memory accounting in bytes (total_bytes, available_bytes, used_bytes, free_bytes) with strict non-negative and available <= total invariants. (3) Accelerators discovery with truthful VRAM and Apple Silicon unified memory protection (never double-counted as separate VRAM). Zero accelerators is valid. (4) Independent probe failure: failure in accelerator detection does not drop CPU/memory facts. (5) Zero device fingerprinting: hostname, username, serial number, and home paths are strictly excluded. (6) Bounded external probes with safe stream draining: timeout <= 2s, shell=False argv list execution, output truncated to <= 64KB, and child process terminated on overflow without retaining parent memory. (7) Trusted executable resolution: probe binaries resolve strictly from trusted system paths, rejecting PATH-shadowing and project/workspace directories. (8) CPU utilization honest baseline: first non-blocking sample returns None (zero fake 0.0), subsequent samples return factual measured utilization. (9) Multi-probe accelerator deduplication: merges sysfs, nvidia-smi, and lspci entries by PCI bus ID or vendor/model into a single record with richer driver marketing names, live NVML memory, and process-local IDs (gpu:0). (10) Concurrency discipline: RLock is never held across probe I/O. (11) Cache and stale semantics: fresh for stale_threshold (2s), cached up to cache_ttl (10s), with factual captured_at and cache_age_seconds preserved. (12) Canonical REST API endpoint GET /v1/resources with local IPC authentication enforcement; adapted legacy GET /telemetry/hardware. (13) Strict R3.2 boundary: host facts exposed without premature model recommendation or winner ranking. 18/18 precision tests passing, 869/869 full regression passing."

- id: R3.4
  title: "Managed Local Inference Supervisor"
  task_status: done
  capability_maturity: S1
  migration: CREATE
  owner: "Runtime & Model Architecture"
  depends_on: ["R3.1", "R3.2", "R3.3"]
  evidence:
    - "core/inference/__init__.py"
    - "core/inference/models.py"
    - "core/inference/binary.py"
    - "core/inference/environment.py"
    - "core/inference/validation.py"
    - "core/inference/manifest.py"
    - "core/inference/installer.py"
    - "core/inference/ports.py"
    - "core/inference/process.py"
    - "core/inference/supervisor.py"
    - "core/providers/adapters/llamacpp.py"
    - "core/execution/kernel_lm_adapter.py"
    - "tests/test_r3_local_supervisor.py"
  notes: "S1 — Implemented and implementation-tested. Completed Managed Local Inference Supervisor final closure: (1) Safe session isolation via start_new_session=True (POSIX) and CREATE_NEW_PROCESS_GROUP (Windows), completely eliminating unsafe Python preexec_fn across all production code. (2) Clean-machine runtime provenance owned strictly by Agent Engine private store (~/.agent_engine/runtimes/llamacpp/llama-server) or packaged desktop resources (zero Ollama or system PATH dependency). (3) AGENT_ENGINE_LLAMA_BIN operator override strictly gated behind AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY=true or dev mode; rejected in default/production mode. (4) Local endpoint protection (--api-key) with documented same-UID process threat model; token masked via repr=False, sanitized in argv, ring buffer logs, and never persisted to ledger. (5) Deterministic canary prompt ('Repeat this exact code word once: AE_E2E_K7M4' at temperature=0) verified in real clean-machine model completion; ledger records provider_id='llamacpp', canonical ModelIdentity, endpoint_class='local_managed', and execution_id. (6) Port collision bounded retry (max 3 retries) catching PortCollisionError, terminating own child handle, and never adopting or terminating foreign processes. (7) Runtime bundle integrity manifest (core/inference/manifest.py) enforcing exact SHA-256 byte integrity across main binary and required sibling libraries (.so, .dylib, .dll); 1-byte alteration, unversioned binaries, and wrong platform artifacts strictly rejected. (8) Controlled runtime provisioning (core/inference/installer.py) proving fresh install from empty private store to verified canary completion and 0 orphan processes. (9) Precise terminology: SHA-256 + trusted expected digest proves byte integrity; publisher authenticity and trust roots reserved for R2.13. 25/25 precision tests passing, 894/894 full regression passing."

- id: R3.5
  title: "Local model catalog and recommendation"
  task_status: done
  capability_maturity: S1
  migration: CREATE
  owner: "Runtime & Model Architecture"
  depends_on: ["R3.2", "R3.3", "R3.4"]
  evidence:
    - "core/model_recommendation/__init__.py"
    - "core/model_recommendation/models.py"
    - "core/model_recommendation/policy.py"
    - "core/model_recommendation/catalog.py"
    - "core/model_recommendation/engine.py"
    - "services/python/server/routers/models.py"
    - "apps/desktop/src/renderer/types/index.ts"
    - "apps/desktop/src/renderer/api/client.ts"
    - "apps/desktop/src/renderer/components/LocalModelRecommendations.tsx"
    - "apps/desktop/src/renderer/screens/Settings.tsx"
    - "tests/test_r3_model_recommendation.py"
  notes: "S1 — Implemented and implementation-tested. Completed Local Model Catalog and Recommendation final closure: (1) Numeric fact provenance model (NumericFactProvenance) distinguishing declared facts, inspected facts, measured facts, derived estimates, curated heuristics, and curated policy. (2) Removed unsourced benchmark claims; replaced with curated recommendation policy rank (1..10) explicitly sourced to Curated Quality Policy. (3) Architecture-aware KV-cache overhead scaling monotonically with context length via ModelKVArchitectureMetadata (layers, heads, head_dim, element_bytes=2) and truthful unknown handling. (4) Unambiguous integer bytes for memory calculations with explicit MiB/GiB reporting. (5) Explicit stale resource snapshot policy (auto-refresh, graceful fallback with warning, resource_captured_at and resource_stale exposed). (6) Headroom denominator strictly defined as usable_before_model = available_ram - OS - AE - runtime_base with headroom_ratio = remaining / usable_before_model. (7) Realistic accelerator requirements: models capable of CPU execution do not mandate GPU; zero-GPU hosts eligible for CPU-capable models. (8) Deterministic tie-breaking ending in canonical_id, strictly invariant under shuffled catalog ordering. (9) Pure side-effect-free execution: zero model downloading, zero process spawning, zero configuration mutations. (10) Privacy-safe explainability: transparent audit trail exposing byte memory and core counts with strictly zero hostnames, usernames, home paths, or hardware serials. (11) Behavior-complete desktop UI component (LocalModelRecommendations.tsx) integrated in Settings.tsx with Fast/Balanced/Best Local cards, freshness badge, no-safe-model state, expandable audit details, and zero side effects. (12) Mandatory IPC token authentication enforced on /v1/models/recommendations and /v1/models/catalog. 14/14 precision tests passing, 100/100 R3 suites passing, 908/908 full regression passing."
- id: R3.6
  title: "Managed model download and verification"
  task_status: done
  capability_maturity: S1
  migration: CREATE
  owner: "Runtime & Model Architecture"
  depends_on: ["R3.4", "R3.5"]
  evidence:
    - "core/model_download/__init__.py"
    - "core/model_download/models.py"
    - "core/model_download/network.py"
    - "core/model_download/storage.py"
    - "core/model_download/manager.py"
    - "core/model_recommendation/catalog.py"
    - "core/inference/validation.py"
    - "core/safety/policy.py"
    - "services/python/server/routers/models.py"
    - "apps/desktop/src/renderer/types/index.ts"
    - "apps/desktop/src/renderer/api/client.ts"
    - "tests/test_r3_model_download.py"
  notes: "S1 — Implemented and implementation-tested. Completed Managed Model Download and Verification final download-safety closure: (1) Anti-SSRF and DNS rebinding immunity with socket-level IP pinning (PinningHTTPAdapter, PinningPoolManager, PinningHTTPConnection, PinningHTTPSConnection) validating all candidate IPs from socket.getaddrinfo and connecting directly to the validated IP while preserving the hostname for TLS SNI and certificate verification. (2) Ambient proxy isolation (session.trust_env = False) rejecting HTTP_PROXY, HTTPS_PROXY, and ALL_PROXY environment variables. (3) Storage authority and path restriction (validate_model_root) rejecting system roots, home root, ~/Downloads, ~/Desktop, /tmp, and workspace source tree; disallowing custom roots in production mode without explicit dev/test authorization; enforcing 0700 directory and 0600 file permissions. (4) Post-verification integrity recomputation in ModelArtifactValidator, checking on-disk SHA-256 before runtime launch and rejecting tampered files with ModelValidationError. (5) Atomic no-clobber promotion (atomic_promote) via hardlink and parent directory fsync; conflicting existing destination files raise ArtifactConflictError without overwriting. (6) Startup reconciliation (reconcile_startup_state) recovering factual truth across mid-download, post-fsync, verifying, and uncommitted placement crashes. (7) Full-artifact resumed checksum verification pre-hashing existing partial files and detecting corrupted partials upon resume. (8) Authoritative PolicyEngine gating on download initiation requiring SkillPermission.NETWORK and SkillPermission.WRITE_LOCAL, returning structured HTTP 403 with zero network, filesystem, or lock side-effects on policy denial. (9) Streamed socket actual-byte ceiling enforcement aborting runaway downloads. (10) Factual resumable and partial_present status semantics with catalog versioning (catalog_version='2026.10.1'). 24/24 precision tests passing, 124/124 R3 suites passing, 932/932 full regression passing."
```

---

## 8. Active Test Suite & Deprecation Warnings Log

- **Full Regression Suite:** `932 passed, 3 warnings` (`uv run pytest -q`)
- **Combined R3 Model Layer Suites:** `124 passed in 29.28s` (`uv run pytest tests/test_r3_*.py`)
- **R3.1 Canonical Provider Registry Suite:** `27 passed in 3.32s` (`uv run pytest tests/test_r3_provider_registry.py`)
- **R3.2 Model Capability Registry Suite:** `16 passed in 3.16s` (`uv run pytest tests/test_r3_model_registry.py`)
- **R3.3 Resource Manager Suite:** `18 passed in 5.95s` (`uv run pytest tests/test_r3_resource_manager.py`)
- **R3.4 Managed Local Inference Supervisor Suite:** `25 passed in 20.38s` (`uv run pytest tests/test_r3_local_supervisor.py`)
- **R3.5 Local Model Catalog & Recommendation Suite:** `14 passed in 4.13s` (`uv run pytest tests/test_r3_model_recommendation.py`)
- **R3.6 Managed Model Download & Verification Suite:** `24 passed in 10.06s` (`uv run pytest tests/test_r3_model_download.py`)
- **R2 Checkpoint and Rollback Suite:** `35 passed in 3.93s` (`uv run pytest tests/test_r2_checkpoint_service.py`)
- **R2 Diagnostics Redaction Suite:** `27 passed in 3.91s` (`uv run pytest tests/test_r2_diagnostics_redaction.py`)
- **R2 Safe Staged Patch Application Suite:** `25 passed in 2.85s` (`uv run pytest tests/test_r2_patch_service.py`)
- **R2 Sandbox Resource Limits Suite:** `38 passed in 14.69s` (`uv run pytest tests/test_r2_sandbox_resource_limits.py`)
- **R2 Sandbox Worker Runtime Suite:** `26 passed in 9.54s` (`uv run pytest tests/test_r2_sandbox_runtime.py`)
- **R2 Secrets Service & Runtime Injection Suite:** `30 passed in 4.50s` (`uv run pytest tests/test_r2_secrets_service.py`)
- **R2 Prompt-Injection & Untrusted Content Suite:** `26 passed in 3.14s` (`uv run pytest tests/test_r2_prompt_injection.py`)
- **R2 Canonical Workspace Paths Suite:** `24 passed in 2.90s` (`uv run pytest tests/test_r2_workspace_paths.py`)
- **R2 Policy & Exact-Operation Approvals Suite:** `33 passed in 4.26s` (`uv run pytest tests/test_r2_policy_and_approvals.py`)
- **R2 IPC Authentication Suite:** `14 passed in 7.83s` (`uv run pytest tests/test_r2_ipc_authentication.py`)
- **Combined R2 Security Verification:** `274 passed in 59.80s` across 11 security suites
- **Static Code Analysis & Formatting:**
  - `uv run ruff check`: passed (`All checks passed!`)
  - `uv run ruff format --check`: passed on all modified files
- **Desktop Tauri & Frontend Workspace:**

  - `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml`: passed (`0.77s`)
  - `pnpm -r build`: passed (`5.58s`)
- **Documented Upstream Warnings (3 known upstream warnings, 0 new unexplained/project-owned warnings):**
  1. `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` (Origin: `fastapi/testclient.py:1` — Upstream FastAPI/Starlette testclient deprecation notice; non-runtime).
  2. `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.` (Origin: `starlette/testclient.py:53` — Upstream Starlette/AnyIO import alias notice; non-runtime).
  3. `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead` (Origin: `chromadb/telemetry/opentelemetry/__init__.py:128` — Upstream ChromaDB telemetry compatibility notice for Python 3.16+; non-blocking on current Python 3.10–3.14).







