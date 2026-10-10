# Founder Acceptance & Core Pack Integration Report (R5.1)

**Milestone:** R5 (Founder Dogfood & Capability Packs) — Task R5.1 (Core Pack MVP)  
**Date:** 2026-10-11  
**Status:** ACCEPTED AT S3 (Behavior Verified across Canonical Founder Journeys on Host Hardware)  
**Prior Checkpoints & Authority Registry:**
- **R4 Substrate Freeze:** `35d78ac` (CLOSED / FROZEN)
- **GUI Founder MVP Baseline:** `b1f8350` (RESTORED TO S3)
- **R5.1 Implementation Baseline:** `189b8ce` (S1 Implementation Baseline)
- **R5.1 Integration Baseline:** `a811986` (S2 Integrated Baseline)
- **R5.2 Status:** STRICTLY NOT STARTED

---

## 1. Formal Maturity & Status Ledger

```
+------------------------------------+--------------------------+-----------------+
| Component / Milestone              | Canonical Status         | Frozen Commit   |
+------------------------------------+--------------------------+-----------------+
| R4 0.5 Workflow Substrate          | CLOSED / FROZEN          | 35d78ac         |
| GUI Founder MVP Baseline           | S3 (Verified in Dev/E2E) | b1f8350         |
| R5.1 Core Pack Implementation      | S3 BEHAVIOR VERIFIED     | Current Branch  |
| R5.1 Task Closure                  | CLOSED (Founder Gate Met)| Current Branch  |
| R5.2 Extension Packs               | STRICTLY NOT STARTED     | N/A             |
+------------------------------------+--------------------------+-----------------+
```

### 1.1 R4 Substrate Freeze Invariant
- Milestone R4 (0.5 Durable Workflow Substrate) is formally **CLOSED / FROZEN** at commit `35d78ac`.
- Migrations 001–009 in `core/jobs/migrations.py` are sealed. No Migration 010 was created or touched.

### 1.2 GUI Maturity Ledger (b1f8350 -> S3)
- **Truthful Status:** GUI Founder MVP Baseline `b1f8350` remains strictly **S3** (Implementation & Behavior Verified in Dev Shell / Tauri E2E).
- **CTO Enforcement:** S4 requires evidence of a clean packaged installation (`.deb` / `.dmg`) launched and verified on a clean machine. S4 is not claimed without packaged installer evidence.
- **GUI Invariant:** Zero GUI code changes were made in this pass. The GUI implementation at `b1f8350` remains completely untouched.

### 1.3 Fixed Route-Count Completion Logic Elimination
- Brittle route-count checks (`assert router_count == 19`, `assert route_count == 178`) were replaced with semantic invariant checks in `tests/test_api_domain_decomposition.py`:
  1. All 19 canonical domain routers are registered.
  2. Core domain operations are reachable and functional.
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

## 3. Pack Permission Vocabulary & Zero-Trust Boundary Mapping

Pack capabilities declare scopes mapped to canonical zero-trust policy engine permissions. Pack presence does not grant authority escalation:

| Pack Scope | Description | Canonical Policy Engine Permission | Policy Governed | Consequential | Requires HITL Approval |
| :--- | :--- | :--- | :---: | :---: | :---: |
| `fs:read` | Read project files and architecture documents | `workspace:read` | Yes | No | No |
| `storage:sqlite` | Local SQLite persistence for sessions and jobs | `storage:read_write` | Yes | No | No |
| `workspace:read`| Read files within bounded project root | `fs:read` | Yes | No | No |
| `execution:run` | Execute model inferences and safe queries | `execution:run` | Yes | No | No |
| `jobs:manage` | Manage durable background jobs via JobService | `jobs:manage` | Yes | No | No |
| `approvals:manage`| Verification and atomic CAS consumption | `safety:approvals` | Yes | **Yes** | **Yes** |

**Zero-Trust Proof:** `CapabilityPackService.verify_zero_trust_authority_boundary` guarantees that `is_consequential=True` operations evaluate strictly through `PolicyEngine` and require operator authorization, regardless of whether a pack is enabled.

---

## 4. Founder Acceptance Test Suite (`tests/test_founder_acceptance.py`)

All 6 canonical founder journeys were executed on Nadir's host machine with real CPU hardware inference, real SQLite databases, and real sidecar REST endpoints.

| Journey ID | Journey Name | Host Test Execution | Verdict |
| :--- | :--- | :--- | :---: |
| **MVP-J1** | Project-Aware Conversation | Real `agent_engine` instructions + context executed on host CPU via AE-managed `llama.cpp` supervisor running `qwen2.5-coder-3b-instruct-q4_k_m.gguf`. | **PASS** |
| **MVP-J7 (Local)** | Local Model Routing | `LOCAL_ONLY` policy routes deterministically to host CPU llama.cpp runtime. Zero network bytes transmitted. | **PASS** |
| **MVP-J7 (Privacy)** | Cloud Privacy Gate | Cloud model (`gpt-4o`) requested under `LOCAL_ONLY` policy is blocked closed with `NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY`. | **PASS** |
| **MVP-J7 (Unauth)** | Approved Cloud Unavailable / Fallback | Approved cloud requested on unconfigured/unauthenticated host fails closed with explicit dispatch error; zero silent degradation. | **PASS** |
| **MVP-J7 (Cloud)** | Real Approved Cloud Execution | Checked `.env` for live API keys. Found template placeholders (`your_key_here`). Truthfully skipped with `BLOCKED BY TEST ENVIRONMENT`. No fake cloud or synthetic success. | **BLOCKED BY TEST ENVIRONMENT** |
| **MVP-J8** | Approval & Safety (Exact Digest) | Canonical digest version 1 binds operation, capability, arguments, execution ID, and actor. Mutated arguments rejected. Atomic CAS consumption succeeds once; replay attack fails closed. | **PASS** |
| **MVP-J9** | Real Cancellation | `CancellationToken` cancelled mid-flight halts execution loop cooperatively. State machine transitions cleanly to `CANCELLED`. | **PASS** |
| **MVP-J10** | Restart Recovery | Process boundary crash/restart recovery of 3 distinct product states verified: (1) `UnifiedSessionStore` session + conversation messages, (2) `JobService` durable queued job, (3) Suspended HITL Gate workflow remaining in `WAITING_APPROVAL` with upstream node completed and not re-executed. | **PASS** |
| **MVP-J12** | Truthful Execution History | REST API endpoints `GET /v1/executions/{id}`, `GET /v1/executions/{id}/trace`, `GET /v1/projects/{id}/executions` return factual duration, monotonic timestamps, provider identities (`llamacpp`), measured tokens, and truthful cost provenance (`calculated` with $0.00 for local compute). Unrecorded executions truthfully report `cost_provenance == UNAVAILABLE`. | **PASS** |

### Execution Trace & Metrics Truth (MVP-J12)
- Local inference compute cost: exactly `$0.000000` (free local hardware compute). Synthetic non-zero costs ($0.000021) were eliminated from `ExecutionCoordinator`.
- Timing: Monotonic `started_at <= completed_at`, `duration_ms > 0.0`.
- Tokens: Measured `input_tokens > 0`, `output_tokens > 0`, `total_tokens = input + output`.
- Unrecorded metrics: `cost_provenance == UNAVAILABLE`, rejecting synthetic zeros and unmeasured numbers.

---

## 5. Quality Gate Verification Evidence

| Quality Gate | Command | Result |
| :--- | :--- | :--- |
| **Founder Acceptance Suite** | `uv run pytest tests/test_founder_acceptance.py -v` | **7 PASSED, 1 SKIPPED** (22.88s) |
| **Core Pack Suite** | `uv run pytest tests/test_r5_1_core_pack.py -v` | **12 PASSED** (6.15s) |
| **API Domain Decomposition** | `uv run pytest tests/test_api_domain_decomposition.py -v` | **25 PASSED** (13.74s) |
| **R4 Hard Exit Suite** | `uv run pytest tests/test_r4_hard_exit.py -v` | **6 PASSED** (6.24s) |
| **Python Static Analysis** | `uv run ruff check` | **CLEAN (0 errors)** |
| **Python Code Formatting** | `uv run ruff format --check` | **CLEAN (367 files formatted)** |
| **Frontend Production Build** | `pnpm -r build` | **CLEAN (15.3s)** |
| **Tauri Desktop Rust Shell** | `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` | **CLEAN (0.81s)** |

---

## 6. Milestone Transition Boundary

- **R4 Substrate:** CLOSED and FROZEN at `35d78ac`.
- **GUI Founder MVP Baseline:** RESTORED to S3 at `b1f8350`. (Clean packaged installation required for S4).
- **R5.1 Core Pack MVP:** ACCEPTED and CLOSED at S3.
- **R5.2 Extension Packs:** STRICTLY DO NOT START.
