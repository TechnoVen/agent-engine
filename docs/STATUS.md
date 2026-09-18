# Agent Engine — Canonical Implementation Status & Capability Matrix

> **Status:** Authoritative Implementation Reality  
> **Updated:** September 18, 2026 (Stage R0 Baseline)  
> **Governing Release:** 0.5 Nadir Founder MVP  

---

## 1. Maturity Level Definitions

| Maturity Level | Criteria | Verification Standard |
|---|---|---|
| **S0 — Specified** | Architecture, interfaces, and acceptance criteria documented in canonical specs. | Approved design doc or ADR exists. |
| **S1 — Implemented** | Code exists, components load, unit-level logic is tested. | Unit tests pass in isolated test runner. |
| **S2 — Integrated** | Connected to adjacent subsystems in the primary application path. | REST API endpoints, client methods, UI screens wired. |
| **S3 — Behavior Verified** | Real behavior verified with external systems, negative paths, and failure modes. | E2E integration tests pass without mocks/stubs. |
| **S4 — Release Verified** | Verified in clean packaged desktop installer on target platform. | Desktop build, Tauri sidecar packaging verified. |
| **S5 — Production** | Hardened, monitored, observed, documentation complete, rollback proven. | Continuous production dogfooding without regressions. |

---

## 2. Legacy Capability Inventory (Phases 0.1 – 7.5)

Every task from the legacy Phase 0–15 roadmap is inventoried below with its canonical destination, migration action, and verified maturity:

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

## 3. Canonical Task Tracking Matrix (Stage R0 — Architecture Rebaseline)

```yaml
- id: R0.1
  title: "Archive the legacy roadmap"
  status: done
  maturity: S3
  migration: ARCHIVE
  owner: "Architecture"
  depends_on: []
  evidence: ["docs/archive/ROADMAP_LEGACY.md with superseded banner", "Commit e63892f"]
  notes: "Completed and checkpoint committed."

- id: R0.2
  title: "Create canonical architecture document set"
  status: done
  maturity: S3
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.1]
  evidence: ["docs/PRODUCT.md", "docs/ARCHITECTURE.md", "docs/STATUS.md", "docs/EXECUTION_MODEL.md", "docs/SECURITY.md", "docs/DATA_MODEL.md", "docs/RELEASE_GATES.md", "docs/INTEGRATIONS.md", "docs/CAPABILITY_PACKS.md"]
  notes: "Canonical specifications created and cross-referenced."

- id: R0.3
  title: "Build legacy capability inventory"
  status: done
  maturity: S3
  migration: INTEGRATE
  owner: "Architecture"
  depends_on: [R0.2]
  evidence: ["docs/STATUS.md Section 2 capability matrix"]
  notes: "All 35 legacy tasks mapped to canonical subsystems and maturity."

- id: R0.4
  title: "Freeze canonical domain vocabulary"
  status: done
  maturity: S3
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.2]
  evidence: ["docs/DATA_MODEL.md", "docs/ARCHITECTURE.md Section 5"]
  notes: "Definitions frozen for Project, Session, Execution, Job, Workflow, Skill, Agent, Team, Artifact."

- id: R0.5
  title: "Establish ADR process & ADR-016"
  status: done
  maturity: S3
  migration: NEW
  owner: "Architecture"
  depends_on: [R0.2, R0.4]
  evidence: ["docs/ADR/TEMPLATE.md", "docs/ADR/016-single-execution-kernel-invariant.md", "docs/ADR/README.md"]
  notes: "ADR-016 defines single execution kernel invariant."

- id: R0.6
  title: "Dependency, provenance and license inventory"
  status: done
  maturity: S3
  migration: NEW
  owner: "Architecture"
  depends_on: []
  evidence: ["docs/DEPENDENCY_AND_LICENSE_INVENTORY.md"]
  notes: "Python (uv), TS (pnpm), and Rust (cargo) dependencies audited."

- id: R0.7
  title: "Replace test-count completion gates"
  status: done
  maturity: S3
  migration: REFACTOR
  owner: "Architecture"
  depends_on: [R0.3]
  evidence: ["docs/RELEASE_GATES.md"]
  notes: "Replaced fixed numerical gates with named behavioral and release verification suites."

- id: R0.8
  title: "Verify reported legacy Phase 7 completion"
  status: done
  maturity: S3
  migration: INTEGRATE
  owner: "Architecture"
  depends_on: [R0.3]
  evidence: ["docs/reviews/PHASE_7_CANONICAL_INTEGRATION_REVIEW.md"]
  notes: "Comprehensive ground-truth audit of Phase 7 source code completed and documented."
```
