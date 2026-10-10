# Founder Acceptance & Core Pack Integration Report (R5.1)

**Milestone:** R5 (Founder Dogfood & Capability Packs) — Task R5.1 (Core Pack MVP)  
**Date:** 2026-10-11  
**Status:** ACCEPTED AT S2 (Integrated & Verified on Host Hardware)  
**Prior Checkpoints:**
- R4 Substrate Freeze: `35d78ac` (CLOSED / FROZEN)
- GUI Founder MVP Baseline: `b1f8350` (RESTORED TO S3)
- R5.1 Implementation: `189b8ce` (S1 Implementation Baseline)
- R5.2 Status: STRICTLY NOT STARTED

---

## 1. Formal Maturity & Status Corrections

### 1.1 R4 Substrate Freeze
- Milestone R4 (0.5 Durable Workflow Substrate) is formally **CLOSED / FROZEN** at commit `35d78ac`.
- Migrations 001–009 in `core/jobs/migrations.py` are sealed. No Migration 010 was created.

### 1.2 GUI Maturity Ledger Correction (b1f8350 -> S3)
- **Truthful Status:** GUI Founder MVP Baseline `b1f8350` is restored to **S3** (Implementation & Behavior Verified in Dev Shell / E2E).
- **Rationale:** `b1f8350` was tested and behavior-verified in the dev shell and Tauri E2E test runner; however, clean-packaged installer verification (`.deb` / `.dmg` installation and launch on a clean system) has not yet been executed. Per CTO instruction, S4 cannot be claimed without clean-package installation evidence.
- **GUI Invariant:** The frozen GUI implementation at `b1f8350` remains completely untouched.

### 1.3 Fixed Route-Count Completion Logic Elimination
- In `tests/test_api_domain_decomposition.py`, brittle fixed-count assertions (`assert router_count == 19`, `assert route_count == 178`) have been eliminated.
- Replaced with semantic invariant assertions:
  1. All 19 canonical domain routers are properly mounted into the sidecar.
  2. Required domain operations are accessible and return valid responses.
  3. Zero duplicate routes exist across the mounted OpenAPI route registry.

---

## 2. Canonical Product Services & Architecture Boundaries

To ensure the Core Pack binds to real product-level capabilities rather than raw infrastructure internals, three canonical domain services were created:

| Capability | Canonical Service Binding | Architecture Boundary |
| :--- | :--- | :--- |
| `chat_session` / `conversation` | `core.execution.coordinator.ExecutionCoordinator` | Central execution engine; no shadow chat loops |
| `project_manager` | `core.projects.service.ProjectService` | Project CRUD, workspace boundaries, context assembly |
| `model_execution` | `core.execution.coordinator.ExecutionCoordinator` | ModelRouter and ProviderRegistry remain internal |
| `task_manager` | `core.jobs.service.JobService` | SQLiteJobQueue and Worker threads remain internal |
| `approval_service` | `core.safety.service.ApprovalService` | PendingOperationRegistry & CAS remain internal |

### Key Architectural Invariants
1. **Zero Shadow Runtime:** All capability execution routes through canonical kernel services. Packs possess zero independent execution threads or custom background runner loops.
2. **Authority Escalation Invariant:** Pack presence does not grant authority escalation. The Core Pack manifest strictly defines least-privilege permissions (`workspace:read`, `execution:run`, `jobs:manage`, `approvals:manage`). Requests for unauthorized permissions (such as arbitrary `net:outbound` bypass) are rejected.
3. **One-Unit Enablement & Atomic Persistence:** Pack state is atomically persisted to `packs_state.json` (`tempfile` atomic replace). The Core Pack is designated as a protected system pack (`is_system: true`) that cannot be disabled.

---

## 3. Real Product Sidecar Mounting (`/v1/packs`)

The pack router (`routers/packs.py`) was mounted directly into `services/python/server/app.py` under the `/v1` router prefix:

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/v1/packs` | GET | List discovered packs with enablement and system status |
| `/v1/packs/{id}` | GET | Retrieve detailed pack manifest and binding status |
| `/v1/packs/{id}/validate` | POST | Validate pack manifest against schema and canonical bindings |
| `/v1/packs/{id}/enable` | POST | Enable pack (atomically persisted) |
| `/v1/packs/{id}/disable` | POST | Disable pack (system packs fail closed with 400 Bad Request) |

---

## 4. Founder Acceptance Test Suite (`tests/test_founder_acceptance.py`)

All 6 mandatory founder journeys were executed and verified on Nadir's host hardware:

```
tests/test_founder_acceptance.py::test_mvp_j1_project_aware_conversation[asyncio] PASSED [ 16%]
tests/test_founder_acceptance.py::test_mvp_j7_routing_privacy_enforcement[asyncio] PASSED [ 33%]
tests/test_founder_acceptance.py::test_mvp_j9_real_cancellation[asyncio] PASSED [ 50%]
tests/test_founder_acceptance.py::test_mvp_j12_truthful_execution_history[asyncio] PASSED [ 66%]
tests/test_founder_acceptance.py::test_mvp_j8_approval_and_safety_exact_digest PASSED [ 83%]
tests/test_founder_acceptance.py::test_mvp_j10_restart_recovery PASSED [100%]
```

### Detailed Journey Results

#### MVP-J1: Real Agent Engine Project Context Conversation — PASS
- **Target:** Real `agent_engine` project directory context on host.
- **Model:** Real `qwen2.5-coder-3b-instruct-q4_k_m.gguf` running via AE-managed `llama.cpp` supervisor process.
- **Verification:** Assembled prompt incorporates real project instructions. Execution routed through `ExecutionCoordinator`. Provenance recorded in `ExecutionLedger`.

#### MVP-J7: Local/Cloud Routing & Privacy Gate — PASS
- **Test A (Local Model):** Local routing policy (`LOCAL_ONLY`) selected `llamacpp` runtime on host hardware. Zero outbound internet requests occurred.
- **Test B (Privacy Gate):** Request specifying cloud model (`gpt-4o`) under `LOCAL_ONLY` policy was blocked at the privacy boundary with `NO_ELIGIBLE_MODEL_UNDER_PRIVACY_POLICY`.
- **Environment Limitation Note:** No live cloud credentials (`OPENAI_API_KEY`) are configured in the environment; cloud invocation is proven blocked by policy rather than failing on network timeout.

#### MVP-J8: Approval & Safety (Exact-Operation Digest Binding) — PASS
- **Mechanism:** Protected operation pauses and registers pending approval with canonical digest binding version, operation, capability, arguments, execution ID, and actor.
- **Verification:** Mutated arguments produce a different digest. Operator approval requires matching digest. Single-use atomic CAS consumption succeeds once; replay attack fails closed.

#### MVP-J9: Real Cancellation — PASS
- **Mechanism:** `CancellationToken` injected into `ExecutionCoordinator.execute`.
- **Verification:** Cancellation request cancels token mid-execution, propagates cooperative cancellation, and transitions state machine to `CANCELLED` status.

#### MVP-J10: Restart Recovery — PASS
- **Mechanism:** Durable background jobs submitted via `JobService` persisted to SQLite repository.
- **Verification:** Service restarted across process boundary with separate instance. Job recovered with intact state (`READY`), payload summary, and metadata.

#### MVP-J12: Truthful Execution History — PASS
- **Mechanism:** Ledger traces queried for completed executions.
- **Verification:** Actual durations, monotonic timestamps, provider identities, and model identifiers recorded without synthetic zeros or invented cost values.

---

## 5. Quality Gate Verification

| Quality Gate | Command | Result |
| :--- | :--- | :--- |
| Founder Acceptance Suite | `uv run pytest tests/test_founder_acceptance.py -v` | **6 / 6 PASSED** (27.5s) |
| Core Pack Suite | `uv run pytest tests/test_r5_1_core_pack.py -v` | **11 / 11 PASSED** |
| API Domain Decomposition | `uv run pytest tests/test_api_domain_decomposition.py -v` | **25 / 25 PASSED** |
| R4 Hard Exit Suite | `uv run pytest tests/test_r4_hard_exit.py -v` | **6 / 6 PASSED** |
| Combined Regression | `uv run pytest tests/test_founder_acceptance.py tests/test_r5_1_core_pack.py tests/test_api_domain_decomposition.py tests/test_r4_hard_exit.py -v` | **48 / 48 PASSED** (41.8s) |
| Python Linting | `uv run ruff check` | **CLEAN (0 errors)** |
| Python Formatting | `uv run ruff format --check` | **CLEAN (366 files formatted)** |
| Frontend Build | `pnpm -r build` | **CLEAN (13.3s)** |
| Tauri Rust Check | `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` | **CLEAN (1.39s)** |

---

## 6. Milestone Transition Boundary

- **R4 Substrate:** CLOSED and FROZEN.
- **R5.1 Core Pack MVP:** ACCEPTED and CLOSED.
- **R5.2:** NOT STARTED. Awaiting Founder & CTO directive before any further milestone progression.
