# Founder Acceptance & Core Pack Integration Report (R5.1)

**Milestone:** R5 (Founder Dogfood & Capability Packs) — Task R5.1 (Core Pack MVP)  
**Date:** 2026-10-11  
**Status:** S2 INTEGRATED / ACCEPTANCE INCOMPLETE (J7 Real Cloud Blocked by Test Environment)  
**Authority Ledger & Frozen Checkpoints:**
- **R4 Substrate Freeze:** `35d78ac` (CLOSED / FROZEN)
- **GUI Founder MVP Baseline:** `b1f8350` (S3 Verified in Dev/E2E)
- **R5.1 Implementation Baseline:** `189b8ce` (S1 Implementation Baseline)
- **R5.1 Integration Baseline:** `a811986` (S2 Integrated Baseline)
- **R5.2 Extension Packs:** STRICTLY DO NOT START

---

## 1. Formal Maturity & Status Ledger

```
+------------------------------------+--------------------------+-----------------------+
| Component / Milestone              | Canonical Status         | Baseline / Reference  |
+------------------------------------+--------------------------+-----------------------+
| R4 0.5 Workflow Substrate          | CLOSED / FROZEN          | 35d78ac               |
| GUI Founder MVP Baseline           | S3 (Dev/E2E Verified)    | b1f8350               |
| R5.1 Implementation                | S1 Complete              | 189b8ce               |
| R5.1 Integration                   | S2 Integrated            | a811986               |
| R5.1 Founder Acceptance            | S2 (J7 Cloud Blocked)    | Current Working Tree  |
| R5.2 Extension Packs               | STRICTLY NOT STARTED     | N/A                   |
+------------------------------------+--------------------------+-----------------------+
```

### 1.1 R4 Substrate Freeze Invariant
- Milestone R4 (0.5 Durable Workflow Substrate) is formally **CLOSED / FROZEN** at commit `35d78ac`.
- Migrations 001–009 in `core/jobs/migrations.py` are sealed. No Migration 010 exists or was created.

### 1.2 GUI Maturity Ledger (b1f8350 -> S3)
- **Status:** GUI Founder MVP Baseline `b1f8350` remains strictly **S3** (Implementation & Behavior Verified in Dev Shell / Tauri E2E).
- **Packaging Boundary:** Promotion to S4 requires evidence of a clean packaged installation (`.deb` / `.dmg`) verified on a clean machine. S4 is not claimed without packaged installer execution evidence.
- **GUI Code Scope:** Limited strictly to factual execution inspection (`ExecutionInspector.tsx`) and operational activity history (`Activity.tsx`) wired to canonical sidecar REST endpoints. Zero unrequested GUI expansion.

### 1.3 Semantic Route Identity Normalization
- All brittle fixed-count completion assertions (`assert router_count == 19`, `assert route_count == 178`) were replaced with semantic invariant checks in `tests/test_api_domain_decomposition.py`:
  1. Semantic Domain Routers (`ChatRouter`, `ExecutionsRouter`, `LedgerRouter`, `ArtifactsRouter`, `SkillsRouter`, `PipelinesRouter`, `AdaptersRouter`, `ProjectsRouter`, `PoliciesRouter`, `TelemetryRouter`, `ModelsRouter`, `CredentialsRouter`, `WorkflowsRouter`, `SwarmRouter`, `TasksRouter`, `MemoryRouter`, `CollaborationRouter`, `PatchesRouter`) are properly mounted.
  2. Canonical endpoints are reachable and execute against shared backend service singletons.
  3. Route ownership is unambiguous with zero duplicate path/method combinations.

---

## 2. Canonical Product Services & Architecture Boundaries

The Core Pack binds exclusively to high-level product service boundaries above internal queues, worker threads, and model registries:

| Capability | Canonical Service Binding | Architecture Boundary / Internal Substrate |
| :--- | :--- | :--- |
| `chat_session` / `conversation` | `core.execution.coordinator.ExecutionCoordinator` | Authoritative execution kernel; zero shadow runtime |
| `project_manager` | `core.projects.service.ProjectService` | Project CRUD, workspace bounds, context assembly |
| `model_execution` | `core.execution.coordinator.ExecutionCoordinator` | `ModelRouter` and `ProviderRegistry` remain internal |
| `task_manager` | `core.jobs.service.JobService` | `SQLiteJobQueue` and `JobWorker` remain internal |
| `approval_service` | `core.safety.service.ApprovalService` | `PendingOperationRegistry` & CAS remain internal |

### Architectural Invariants Verified
1. **Zero Shadow Runtime:** All pack capabilities route through canonical services (`ExecutionCoordinator`, `JobService`, `ApprovalService`, `ProjectService`). No independent background loops or worker threads exist inside packs.
2. **Authority Escalation Invariant:** Enabling a pack registers bindings, but never grants execution authority without explicit `PolicyEngine` evaluation and operator approval for consequential actions.
3. **One-Unit Enablement & Atomic Persistence:** Pack state is atomically persisted to `packs_state.json` via tempfile replacement. Core Pack is designated `is_system: true` and cannot be disabled.

---

## 3. Normalized Pack Permission Vocabulary & Zero-Trust Boundary

The pack permission mapping table in `core/packs/service.py` was normalized to establish a clean, non-circular directional contract: `pack scope -> canonical security capability/permission -> PolicyEngine`.

| Pack Scope | Description | Canonical Capability | Canonical Permission | Policy Governed | Consequential | Requires HITL Approval |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| `fs:read` | Read project files and architecture documents | `fs:read` | `read` | Yes | No | No |
| `storage:sqlite` | Local SQLite persistence for sessions and jobs | `storage:sqlite` | `write_local` | Yes | No | No |
| `execution:run` | Execute model inferences and safe queries | `execution:run` | `execute` | Yes | No | No |
| `jobs:manage` | Manage durable background jobs via JobService | `jobs:manage` | `execute` | Yes | No | No |
| `approvals:manage` | Verification and atomic CAS consumption | `approvals:manage` | `admin` | Yes | **Yes** | **Yes** |

### Zero-Trust Proof (`test_core_pack_permission_vocabulary_and_zero_trust_boundary`)
1. **No Circular Aliases:** `fs:read` maps to `read` and `fs:read` (circular alias `workspace:read <-> fs:read` completely eliminated).
2. **Undeclared Scope Rejection:** Undeclared scopes (`net:outbound`, `shell:execute`, `db:drop`) return `False` and cannot be evaluated.
3. **Policy Engine Boundary:** Even when a pack is enabled and declares a consequential scope (`approvals:manage`), if `PolicyEngine.evaluate()` denies the operation (e.g. destructive command matching policy rule), the boundary returns `False`. Enabling a pack never bypasses security policy.

---

## 4. Cost Terminology Normalization

The desktop UI and sidecar ledger conform strictly to normalized cost accounting:

1. **Local Model Inferences:**
   - Provider charges: `Provider charge: $0.00`
   - Hardware/electricity cost: `Local compute cost: Unavailable (hardware/electricity unmeasured)`
   - Prohibited terms: "Local compute cost = $0.00" and "Local Free" are eliminated.
2. **Cloud Model Inferences:**
   - Provider-reported usage: `Provider charge: $X.XXXX (Actual)`
   - Catalog-calculated usage: `Provider charge: $X.XXXX (Estimated)`
   - Missing or unmeasured cost: `Provider charge: Unavailable`
   - Prohibited behavior: Missing metrics are never fabricated or converted to zero.

---

## 5. Founder Acceptance Test Suite (`tests/test_founder_acceptance.py`)

All founder journeys were evaluated on host hardware using real CPU inference, real SQLite databases, and real REST sidecar endpoints.

| Journey ID | Journey Name | Host Test Execution & Factual Evidence | Verdict |
| :--- | :--- | :--- | :---: |
| **MVP-J1** | Project-Aware Conversation | Real `agent_engine` instructions + context executed on host CPU via AE-managed `llama.cpp` supervisor running `qwen2.5-coder-3b-instruct-q4_k_m.gguf`. | **PASS** |
| **MVP-J7 (Local)** | Local Model Routing | `LOCAL_ONLY` policy routes deterministically to host CPU llama.cpp runtime. Zero network bytes transmitted. | **PASS** |
| **MVP-J7 (Privacy)** | Cloud Privacy Gate | Cloud model (`gpt-4o`) requested under `LOCAL_ONLY` policy is blocked closed with `NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY`. | **PASS** |
| **MVP-J7 (Unauth)** | Approved Cloud Unavailable / Fallback | Approved cloud requested on unconfigured/unauthenticated host fails closed with explicit dispatch error; zero silent degradation. | **PASS** |
| **MVP-J7 (Cloud)** | Real Approved Cloud Execution | Canonical storage checked (`KeyringBackend` / `.env`). Only template placeholders (`your_key_here`) and test fixture keys exist. Zero live provider credentials. Truthfully marked `BLOCKED BY TEST ENVIRONMENT`. No fake cloud or synthetic success. | **BLOCKED BY TEST ENVIRONMENT** |
| **MVP-J8** | Approval & Safety (Exact Digest) | Canonical digest version 1 binds operation, capability, arguments, execution ID, and actor. Mutated arguments rejected. Atomic CAS consumption succeeds once; replay attack fails closed. | **PASS** |
| **MVP-J9** | Real Cancellation | `CancellationToken` cancelled mid-flight halts execution loop cooperatively. State machine transitions cleanly to `CANCELLED`. | **PASS** |
| **MVP-J10** | Restart Recovery | Process boundary crash/restart recovery of 3 distinct product states verified: (1) `UnifiedSessionStore` session + conversation messages, (2) `JobService` durable queued job, (3) Suspended HITL Gate workflow remaining in `WAITING_APPROVAL` with upstream node completed and not re-executed. | **PASS** |
| **MVP-J12** | Truthful Execution History & Desktop Trace | REST API endpoints `GET /v1/executions`, `GET /v1/executions/{id}`, `GET /v1/executions/{id}/trace` return factual duration, monotonic timestamps, provider identities (`llamacpp`), measured tokens, and truthful cost provenance (`calculated` with $0.00 provider charge). Unrecorded executions report `cost_provenance == UNAVAILABLE`. Desktop `ExecutionInspector` renders status, duration, provider charge, tool calls, approvals, and artifacts matching `ExecutionLedger`. | **PASS** |

---

## 6. Full Quality Gate Verification Evidence

| Quality Gate | Command | Result | Duration |
| :--- | :--- | :--- | :---: |
| **Founder Acceptance Suite** | `uv run pytest tests/test_founder_acceptance.py -v` | **7 PASSED, 1 SKIPPED** (Truthful J7 Cloud skip) | 113.04s |
| **Core Pack Suite** | `uv run pytest tests/test_r5_1_core_pack.py -v` | **12 PASSED** | 8.47s |
| **API Domain Decomposition** | `uv run pytest tests/test_api_domain_decomposition.py -v` | **25 PASSED** | 24.62s |
| **R4 Hard Exit Suite** | `uv run pytest tests/test_r4_hard_exit.py -v` | **6 PASSED** | 8.94s |
| **Python Static Analysis** | `uv run ruff check` | **CLEAN (0 errors)** | <1s |
| **Python Code Formatting** | `uv run ruff format --check` | **CLEAN (28 files formatted)** | <1s |
| **Desktop Production Build** | `pnpm build` (in `apps/desktop`) | **CLEAN (0 errors, Vite build OK)** | 6.16s |
| **Tauri Desktop Rust Shell** | `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` | **CLEAN (0 errors)** | 0.83s |

---

## 7. Milestone Transition Boundary & CTO Recommendation

1. **R4 Substrate:** CLOSED and FROZEN at `35d78ac`. Migrations 001–009 sealed.
2. **GUI Founder MVP Baseline:** Maintained at **S3** at `b1f8350`. Promotion to S4 remains blocked until clean packaged installation (`.deb`/`.dmg`) is proven on a clean machine.
3. **R5.1 Core Pack Status:** Remains **OPEN AT S2 INTEGRATED**. Because live cloud credentials are not configured in the host environment, MVP-J7 Real Cloud is truthfully marked **BLOCKED BY TEST ENVIRONMENT**. S3 closure will occur when a real cloud credential is provided through `Settings -> Connections` or OS Keychain and verified end-to-end.
4. **R5.2 Extension Packs:** **STRICTLY DO NOT START**.
