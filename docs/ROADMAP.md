# Agent Engine — Canonical Comprehensive Roadmap

> **Status:** Canonical execution roadmap  
> **Audience:** Gemini / coding agents / maintainers / CTO / product owner  
> **Baseline:** Existing Agent Engine implementation through the legacy Phase 7 work, with legacy Phase 7 reported complete by the product owner and subject to verification in R0.  
> **Supersedes:** The legacy Phase 0–15 roadmap as the primary sequencing authority. The legacy roadmap remains implementation history and a migration reference.  
> **North Star:** One local-first AI operating environment with one execution kernel, one control plane, one skill system, one knowledge system, one approval/security boundary, local + cloud intelligence, durable automation, and protocol-based access from every surface.

---

## 0. How Gemini must use this roadmap

This file is an **execution contract**, not an idea list.

Gemini must follow these rules:

1. Work in task-ID order unless a task explicitly permits parallel execution.
2. Never mark a task complete because files exist. Completion requires the listed acceptance evidence.
3. Preserve useful existing code. Prefer **KEEP → INTEGRATE → REFACTOR** over rewrites.
4. Before replacing an existing subsystem, document why adaptation cannot satisfy the canonical architecture.
5. Every consequential execution path must converge on the canonical `ExecutionCoordinator` and its policy, budget, telemetry, approval, persistence and verification boundaries.
6. No production response may claim work happened unless the execution ledger records that work.
7. Every persistent-schema change requires a migration and rollback/recovery strategy.
8. Every externally adopted component or copied/adapted source requires license/provenance metadata.
9. Every UI change must include loading, empty, success, failure and cancellation states where relevant, plus keyboard and screen-reader behavior.
10. Every release gate blocks work on later product breadth when a P0/P1 defect invalidates a core guarantee.
11. Do not re-introduce the legacy rigid 90/9/1 rule. Optimise for **quality-adjusted cost per successful task** subject to privacy, risk and latency constraints.
12. If implementation reality differs from this roadmap, update `docs/STATUS.md` first and create an ADR before changing architecture.

### Required per-task status record

Each task tracked in `docs/STATUS.md` must contain:

```yaml
id: R1.3
status: planned | in_progress | blocked | done
maturity: S0 | S1 | S2 | S3 | S4 | S5
migration: KEEP | INTEGRATE | REFACTOR | EXPAND | SUPERSEDE | ARCHIVE | NEW
owner: null
depends_on: []
evidence: []
notes: null
```

### Maturity model

| Code | Meaning |
|---|---|
| **S0 — Specified** | Architecture, interfaces and acceptance criteria exist. |
| **S1 — Implemented** | Code exists and unit-level behavior is covered. |
| **S2 — Integrated** | The canonical product path uses the capability. |
| **S3 — Behavior Verified** | E2E tests prove real behavior, including failures. |
| **S4 — Release Verified** | Works from a clean packaged installation. |
| **S5 — Production** | Operational reliability, observability, rollback and support expectations are proven. |

Only S5 means fully complete. Roadmap tasks may close at an earlier maturity where the task explicitly says so, but the release gate may require higher maturity.

### Migration action codes

| Action | Meaning |
|---|---|
| **KEEP** | Existing architecture is valid; preserve implementation. |
| **INTEGRATE** | Existing code works but must enter the canonical execution/control path. |
| **REFACTOR** | Existing functionality is valuable but boundaries/contracts are wrong. |
| **EXPAND** | Foundation is good but missing new canonical responsibilities. |
| **SUPERSEDE** | Maintain compatibility while replacing the architectural approach. |
| **ARCHIVE** | Retain for history/dev diagnostics only; not a product authority. |
| **NEW** | New canonical capability. |

### Product personas used by user stories

| Persona | Description |
|---|---|
| **Nadir / Founder User** | Uses Agent Engine daily for personal, writing, research, coding, business and finance-analysis work. |
| **Everyday User** | Wants useful AI outcomes without understanding models, frameworks or protocols. |
| **Power User** | Wants control over models, skills, automation, costs and approvals. |
| **Developer** | Builds software, workflows, skills, integrations and Agent Engine itself. |
| **Workspace Admin** | Manages projects, policies, credentials and shared capabilities. |
| **Package Author** | Publishes skills, tools, workflows or capability packs. |
| **Team/Enterprise Admin** | Manages multi-user access, SSO, policies, tenancy and operations. |

---

# PART I — FOUNDER MVP

# MVP-N — Agent Engine 0.5 “Nadir Edition”

## Product intent

The first product target is not a marketplace or enterprise platform. It is a local application that **Nadir can use as his real daily AI environment** and that exposes architectural failures quickly.

The MVP must support real work across sufficiently different domains to test the architecture:

- persistent project chat;
- local and cloud model execution;
- automatic routing;
- file and project knowledge;
- writing;
- deep research;
- coding in isolated workspaces;
- read-only finance/document analysis;
- one durable scheduled workflow;
- exact-operation approvals;
- real cancellation;
- restart recovery;
- truthful execution/cost history.

## MVP capability packs

Ship only:

1. **Core Pack** — chat, projects, files, models, executions, approvals, tasks.
2. **Personal Pack** — general notes, task planning, local files and simple personal workflows.
3. **Writing Pack** — outline, draft, style review, claim review, final artifact.
4. **Research Pack** — research plan, source collection, evidence synthesis, citations/provenance.
5. **Developer Pack** — diagnose, specify, plan, isolated implementation, test, independent review.
6. **Finance Reader Pack** — invoice extraction, bank CSV analysis, classification suggestions and reconciliation proposals; no money movement.

## Founder journeys that must work

### MVP-J1 — Project-aware conversation
**User Story:** As Nadir, I want to open the Agent Engine project and ask questions that use its files, architecture documents and prior project conversations so I do not repeatedly explain the project.

**Pass condition:** Real project instructions/history/knowledge reach the selected provider; the execution ledger shows the actual context sources.

### MVP-J2 — Writing workflow
**User Story:** As Nadir, I want to turn notes into an article through outline, drafting, style review and factual review so I can use Agent Engine for real publishing work.

**Pass condition:** The final document is a persistent artifact linked to the project and every model/tool step is traceable.

### MVP-J3 — Deep research
**User Story:** As Nadir, I want evidence-aware research that distinguishes source facts, uncertainty and synthesis so I can rely on it for decisions and writing.

**Pass condition:** Sources and extracted claims are traceable; retrieval/model failures are visible rather than converted to success narratives.

### MVP-J4 — Coding workflow
**User Story:** As Nadir, I want Agent Engine to diagnose an issue, create a plan, work in an isolated Git worktree, implement, test and independently review the change so coding automation is safe enough to dogfood on Agent Engine itself.

**Pass condition:** No edits touch the canonical branch before approval; test and review evidence are linked to the execution.

### MVP-J5 — Document intelligence
**User Story:** As Nadir, I want to drop PDFs, Markdown, CSVs and source files into a project and have Agent Engine automatically choose the correct retrieval/analysis strategy.

**Pass condition:** The user never selects “RAG mode”; the retrieval decision and provenance are recorded automatically.

### MVP-J6 — Finance reader
**User Story:** As Nadir, I want Agent Engine to read invoices and bank exports, suggest categories and matches, and explicitly mark uncertainty so I can prepare bookkeeping without letting an AI post financial transactions autonomously.

**Pass condition:** Outputs are proposals only; confidence and source fields are visible.

### MVP-J7 — Local/cloud routing
**User Story:** As Nadir, I want simple private work to stay local while difficult tasks can use approved cloud models so I get a useful quality/cost/privacy balance without manually choosing every model.

**Pass condition:** Actual provider choice is visible and matches routing policy.

### MVP-J8 — Approval and safety
**User Story:** As Nadir, I want dangerous or consequential operations to pause with an exact description of what will happen so I can approve only the action I intend.

**Pass condition:** Changed arguments invalidate the approval; replay fails.

### MVP-J9 — Cancellation
**User Story:** As Nadir, I want Stop to halt real provider/tool work so I remain in control of long or mistaken tasks.

**Pass condition:** Upstream work is cancelled where supported and execution status is `CANCELLED`, never `COMPLETED`.

### MVP-J10 — Restart recovery
**User Story:** As Nadir, I want sessions, queued jobs and paused workflows to survive closing or crashing the desktop app so Agent Engine is dependable for everyday work.

**Pass condition:** Restart resumes or safely exposes interrupted work without duplicating completed steps.

### MVP-J11 — Scheduled automation
**User Story:** As Nadir, I want a weekly Agent Engine project review to run automatically and produce a brief so I can trust the scheduler for real recurring work.

**Pass condition:** The schedule survives restart and creates one idempotent durable job per occurrence.

### MVP-J12 — Truthful execution history
**User Story:** As Nadir, I want to see which models, tools, skills, tokens, costs, artifacts and approvals were actually used so I can understand and trust the system.

**Pass condition:** No fabricated telemetry; missing provider usage is explicitly marked estimated/unknown.

## MVP-N release gate

All must pass on Nadir’s normal machine from a clean installation:

- [ ] Application installs and launches without manual developer repair.
- [ ] At least one managed local model completes a real request.
- [ ] At least one cloud provider completes a real request.
- [ ] UI model selection actually changes provider/model execution.
- [ ] Two-turn conversation proves bounded history reaches inference.
- [ ] Project A data does not appear in Project B retrieval/context.
- [ ] Real file ingestion and retrieval work.
- [ ] Writing workflow produces a persistent artifact.
- [ ] Developer workflow uses an isolated worktree and real tests.
- [ ] Protected tool execution cannot bypass policy/approval.
- [ ] Stop cancels actual execution.
- [ ] Costs/usage are real or clearly labeled estimates.
- [ ] Sessions and durable jobs survive restart.
- [ ] A scheduled job executes once after restart.
- [ ] Provider outage produces truthful fallback/failure.
- [ ] No-provider state produces an explicit error and never fake success.
- [ ] Keyboard navigation and basic screen-reader semantics work for all MVP flows.

---

# PART II — RELEASE SEQUENCE

| Release | Canonical stages | Product outcome |
|---|---|---|
| **0.5 Nadir Edition** | R0–R5 | Reliable single-user founder dogfood release. |
| **0.6 Personal Alpha** | R6–R8 | Knowledge Engine, Skills 2.0, evaluation and controlled learning. |
| **0.7 Developer Alpha** | R9 | ACP/MCP and structured software-engineering workflows. |
| **0.8 Superhub Alpha** | R10 | Communication, email/calendar and personal automation surfaces. |
| **0.9 Power User Beta** | R11–R12 | Domain capability packs and safe multi-agent teams. |
| **1.0 Local-First Stable** | R13–R15 as needed for stable local product | Marketplace-ready package model, operations, installers, accessibility and backup. |
| **1.5 Business** | R16 | Shared/team server, RBAC and business deployment. |
| **2.0 Platform** | R13 + R17 platform pieces | Public ecosystem, SDKs and distributed execution. |
| **3.x Enterprise/Cloud** | R17 | SSO, tenancy, compliance and large-scale workers. |
| **Future Intelligence** | R18 | Fine-tuning, distillation, adaptive routing/retrieval and ambient automation. |

---

# PART III — CANONICAL ROADMAP

# R0 — Architecture Rebaseline & Truth Reset

## Objective

Create one authoritative view of implementation reality, freeze terminology and map all legacy work into the canonical architecture before changing product breadth.

## Hard exit gate

No important capability may be simultaneously described as “complete” while its acceptance behavior is unverified. `docs/STATUS.md` becomes the factual source of implementation maturity.

## Tasks

### [ ] R0.1 — Archive the legacy roadmap

- **Migration:** `ARCHIVE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a maintainer, I want the old roadmap preserved as implementation history so useful decisions remain traceable without controlling new sequencing.
- **Deliverables:**
  - Move/copy the legacy roadmap to `docs/archive/ROADMAP_LEGACY.md`.
  - Add a superseded banner linking to the canonical roadmap.
- **Acceptance Criteria:**
  - [ ] Legacy task text remains searchable.
  - [ ] Only the canonical roadmap is identified as sequencing authority.
- **Required Evidence:**
  - Git diff showing archive move/copy and banner.

### [ ] R0.2 — Create canonical architecture document set

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.1
- **User Story:** As a developer, I want one small set of authoritative documents so implementation decisions do not depend on contradictory planning files.
- **Deliverables:**
  - Create/refresh `PRODUCT.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `STATUS.md`, `EXECUTION_MODEL.md`, `SECURITY.md`, `DATA_MODEL.md`, `RELEASE_GATES.md`, `INTEGRATIONS.md`, `CAPABILITY_PACKS.md`.
- **Acceptance Criteria:**
  - [ ] Documents cross-reference each other and use the same entity names.
  - [ ] No canonical document claims unsupported current functionality.
- **Required Evidence:**
  - Documentation consistency check.

### [ ] R0.3 — Build legacy capability inventory

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.2
- **User Story:** As a CTO, I want every legacy Phase 0–7 capability mapped to real maturity so we preserve working assets and expose integration gaps.
- **Deliverables:**
  - Inventory every old task 0.1–7.x.
  - Assign canonical subsystem, migration action, current maturity and evidence link.
- **Acceptance Criteria:**
  - [ ] Every legacy task has exactly one canonical destination or archive decision.
- **Required Evidence:**
  - `docs/STATUS.md` capability matrix.

### [ ] R0.4 — Freeze canonical domain vocabulary

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.2
- **User Story:** As a developer, I want stable definitions for Project, Session, Execution, Job, Workflow, Skill, Agent, Team and Artifact so APIs and storage stop drifting conceptually.
- **Deliverables:**
  - Add domain glossary and type ownership.
  - Resolve legacy terms such as pipeline/swarm/room where they overlap.
- **Acceptance Criteria:**
  - [ ] Canonical entities have one definition and owning module.
- **Required Evidence:**
  - Glossary review + ADR.

### [ ] R0.5 — Establish ADR process

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.2, R0.4
- **User Story:** As a maintainer, I want significant architecture changes recorded with context and trade-offs so the project does not repeatedly reverse decisions.
- **Deliverables:**
  - ADR template.
  - Index and numbering convention.
  - First ADR: single Execution Kernel invariant.
- **Acceptance Criteria:**
  - [ ] Architecture-changing PRs reference an ADR.
- **Required Evidence:**
  - ADR template and first accepted ADR.

### [ ] R0.6 — Dependency, provenance and license inventory

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a product owner, I want every external component’s license and purpose recorded so future distribution and marketplace plans are legally maintainable.
- **Deliverables:**
  - Generate dependency inventory for Python/TS/Rust and copied/adapted assets.
  - Record license, source, version, use, replacement risk.
- **Acceptance Criteria:**
  - [ ] No unknown-license production dependency in release build.
- **Required Evidence:**
  - SBOM/license report artifact.

### [ ] R0.7 — Replace test-count completion gates

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.3
- **User Story:** As a developer, I want CI to prove behavior instead of fixed test counts so adding or removing legitimate tests does not create misleading completion signals.
- **Deliverables:**
  - Remove fixed test-number assertions from roadmap/CI.
  - Introduce named behavioral suites and release gates.
- **Acceptance Criteria:**
  - [ ] CI passes/fails on behavior, schema, security and packaging gates rather than a hard-coded test count.
- **Required Evidence:**
  - CI run output.

### [ ] R0.8 — Verify reported legacy Phase 7 completion

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.3
- **User Story:** As a CTO, I want the newly completed workflow work independently mapped and behavior-checked before treating it as the canonical workflow runtime.
- **Deliverables:**
  - Inspect Phase 7 implementation delivered after the legacy roadmap snapshot.
  - Record implemented nodes, builder, HITL, parallel execution and persistence maturity.
- **Acceptance Criteria:**
  - [ ] Every Phase 7 sub-capability has evidence and migration action.
- **Required Evidence:**
  - Workflow audit report.

# R1 — Execution Kernel Convergence

## Objective

Create one authoritative execution path for chat, DSPy programs, skills, tools, workflows, protocols and future agents.

## Hard exit gate

A real desktop request travels through project/session context, routing, a real provider, streaming, persistence, usage/cost and verification with no simulated-success branch.

## Tasks

### [x] R1.1 — Canonical Execution domain

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S1`
- **Dependencies:** R0.4
- **User Story:** As a developer, I want a stable Execution model so every surface describes work using the same lifecycle and identifiers.
- **Deliverables:**
  - Implement `Execution`, `ExecutionRequest`, `ExecutionContext`, `ExecutionResult`, `ExecutionEvent`, status enum.
  - Repository interfaces and migrations.
- **Acceptance Criteria:**
  - [x] Execution IDs are immutable and globally unique within deployment.
  - [x] State transitions are validated.
- **Required Evidence:**
  - Unit tests + migration test (`tests/test_execution_models.py`, `tests/test_execution_storage.py`).

### [x] R1.2 — Execution state machine

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S1`
- **Dependencies:** R1.1
- **User Story:** As a user, I want running, paused, failed, cancelled and completed work to have truthful states so the UI never invents progress.
- **Deliverables:**
  - Define allowed transitions for CREATED, CONTEXT_BUILDING, ROUTING, POLICY_CHECK, BUDGET_CHECK, PLANNING, READY, QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED, VERIFYING, COMPLETED, PARTIAL, BLOCKED, FAILED, TIMED_OUT, CANCELLED.
- **Acceptance Criteria:**
  - [x] Illegal transition is rejected and audited.
  - [x] `COMPLETED` requires verification result.
- **Required Evidence:**
  - State-machine tests (`tests/test_execution_state_machine.py`).

### [x] R1.3 — ExecutionCoordinator service

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S1`
- **Dependencies:** R1.1, R1.2
- **User Story:** As a maintainer, I want one entry point for model/tool/agent/workflow work so security, cost and telemetry cannot be bypassed accidentally.
- **Deliverables:**
  - Create `ExecutionCoordinator`.
  - Define adapters around existing router, context builder, policy, budget, model and telemetry components.
- **Acceptance Criteria:**
  - [x] No canonical product path invokes a provider/tool directly.
- **Required Evidence:**
  - Architecture dependency test + integration trace (`tests/test_execution_coordinator.py`).

### [ ] R1.4 — Rewire chat to real execution

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As Nadir, I want chat responses to come from actual configured intelligence so I can trust that a success message means work really happened.
- **Deliverables:**
  - Remove test-trigger/fake-success production branches.
  - Route chat through `ExecutionCoordinator`.
- **Acceptance Criteria:**
  - [ ] No-provider request fails explicitly.
  - [ ] Arbitrary prompt reaches provider stub unchanged except intentional context assembly.
- **Required Evidence:**
  - E2E provider-stub test.

### [ ] R1.5 — Real provider/model resolution

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a Power User, I want changing the selected model to change the model that executes so provider controls are real, not labels.
- **Deliverables:**
  - Bind UI/provider configuration to Model Router.
  - Persist model choice at profile/project/session/request scopes.
- **Acceptance Criteria:**
  - [ ] Two configured selections invoke two distinct provider/model targets.
- **Required Evidence:**
  - Provider-spy integration test.

### [ ] R1.6 — Canonical project context

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.1
- **User Story:** As Nadir, I want each project’s instructions, files, policies and budgets to affect only that project so work remains isolated and relevant.
- **Deliverables:**
  - Move browser-local project state into backend canonical Project model.
  - Pass project identity through execution context.
- **Acceptance Criteria:**
  - [ ] Project A instructions/files never enter Project B execution.
  - [ ] Reload preserves project records.
- **Required Evidence:**
  - Cross-project isolation E2E test.

### [ ] R1.7 — Bounded real conversation history

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3, R1.6
- **User Story:** As an Everyday User, I want follow-up questions to remember the conversation without sending unlimited history to the model.
- **Deliverables:**
  - Load authorized session history.
  - Apply context budget before inference.
- **Acceptance Criteria:**
  - [ ] Two-turn recall test passes.
  - [ ] History outside the current authorized session is excluded unless retrieved explicitly.
- **Required Evidence:**
  - Conversation-context E2E test.

### [ ] R1.8 — Real streaming

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3, R1.4
- **User Story:** As Nadir, I want tokens/events to appear while work is actually running so progress reflects upstream execution rather than a post-completion animation.
- **Deliverables:**
  - Use provider streaming where available.
  - Define canonical SSE/event stream.
- **Acceptance Criteria:**
  - [ ] First output event reaches UI before provider completion.
  - [ ] Disconnect handling leaves execution in a truthful state.
- **Required Evidence:**
  - Streaming timing E2E test.

### [ ] R1.9 — Real cancellation

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.8
- **User Story:** As Nadir, I want Stop to cancel actual model/tool work so I remain in control.
- **Deliverables:**
  - Cancellation token propagation.
  - Provider/tool adapters implement cancellation where possible.
  - Graceful fallback where upstream cannot cancel.
- **Acceptance Criteria:**
  - [ ] Stop prevents further tool dispatch.
  - [ ] Execution becomes CANCELLED, not COMPLETED.
- **Required Evidence:**
  - Cancellation E2E test with slow provider/tool stubs.

### [ ] R1.10 — Execution artifact model

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.1
- **User Story:** As a user, I want answers, files, patches, reports and queued jobs distinguished so the system never confuses a proposal with an applied change.
- **Deliverables:**
  - Implement typed `Artifact` metadata and storage references.
  - Link artifacts to executions/jobs.
- **Acceptance Criteria:**
  - [ ] UI/API can distinguish answer, file, patch, proposed change, applied change and queued job.
- **Required Evidence:**
  - Artifact round-trip tests.

### [ ] R1.11 — Execution ledger

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3, R1.10
- **User Story:** As Nadir, I want a truthful record of models, tools, skills, approvals, tokens, cost and artifacts so I can audit what Agent Engine did.
- **Deliverables:**
  - Unify cost, token, tool, approval and event records by `execution_id`.
  - Expose execution detail API/UI.
- **Acceptance Criteria:**
  - [ ] One execution can be reconstructed from persisted events/records.
- **Required Evidence:**
  - Golden execution trace fixture.

### [ ] R1.12 — Rewire DSPy pipeline registry

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a developer, I want existing DSPy programs preserved but executed through the canonical kernel so they inherit policy, cost, context and trace behavior.
- **Deliverables:**
  - Wrap legacy pipeline registry runs in executions.
  - Record DSPy program/version metadata.
- **Acceptance Criteria:**
  - [ ] Direct product endpoints cannot invoke DSPy outside coordinator.
- **Required Evidence:**
  - Integration test for standard pipeline.

### [ ] R1.13 — Rewire skills and adapters

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a developer, I want legacy skills/adapters to use the same execution semantics so integrations do not create shadow runtimes.
- **Deliverables:**
  - Introduce compatibility adapters that translate legacy calls to canonical executions.
- **Acceptance Criteria:**
  - [ ] Legacy adapter invocation produces normal execution events and policy/cost records.
- **Required Evidence:**
  - Adapter contract test.

### [ ] R1.14 — Split monolithic API by domain

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a maintainer, I want API modules aligned with domains so contract drift and merge risk decrease without changing behavior.
- **Deliverables:**
  - Extract routers/services for execution, projects, sessions, models, skills, policies, telemetry, workflows.
- **Acceptance Criteria:**
  - [ ] OpenAPI remains backward compatible where intended.
  - [ ] Contract tests cover desktop client methods.
- **Required Evidence:**
  - Schema diff + contract tests.

# R2 — Security, Authorization & Recovery

## Objective

Make the kernel safe enough for real local daily work and future external extensions.

## Hard exit gate

Protected operations cannot execute with missing, invalid, expired, replayed or argument-mismatched authorization; path escape and policy-service failure fail closed.

## Tasks

### [ ] R2.1 — Mandatory local IPC authentication

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As Nadir, I want only trusted local Agent Engine clients to call privileged sidecar APIs so another local process cannot read credentials or mutate state silently.
- **Deliverables:**
  - Generate per-launch/session secret.
  - Require auth on privileged APIs.
  - Keep only minimal liveness endpoint unauthenticated.
- **Acceptance Criteria:**
  - [ ] Missing/wrong token yields 401/403.
  - [ ] Desktop remains functional with trusted token.
- **Required Evidence:**
  - Security integration tests.

### [ ] R2.2 — Origin/CORS hardening

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.1
- **User Story:** As a user, I want browser-origin access restricted so arbitrary web pages cannot invoke my local control plane.
- **Deliverables:**
  - Explicit allowed origins.
  - Production-native mode disables unnecessary browser origins.
- **Acceptance Criteria:**
  - [ ] Arbitrary origin rejected.
- **Required Evidence:**
  - CORS regression test.

### [ ] R2.3 — Mandatory backend policy boundary

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a user, I want every protected tool call evaluated by policy at the execution boundary so UI or adapter failures cannot bypass safety.
- **Deliverables:**
  - Move policy interception into Tool Runtime/ExecutionCoordinator.
  - Remove frontend fail-open fallback.
- **Acceptance Criteria:**
  - [ ] Denied tool never executes.
  - [ ] Policy-evaluation error blocks protected work.
- **Required Evidence:**
  - Negative-path tool tests.

### [ ] R2.4 — Exact-operation approval tokens

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3
- **User Story:** As Nadir, I want approval to authorize only the exact operation shown to me so an agent cannot change arguments after I approve.
- **Deliverables:**
  - Bind approval to execution/tool/argument digest/actor/expiry/nonce.
  - Single-use consumption.
- **Acceptance Criteria:**
  - [ ] Forged, replayed, expired and mismatched approvals fail.
- **Required Evidence:**
  - Approval security suite.

### [ ] R2.5 — Canonical workspace path enforcement

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.6
- **User Story:** As a user, I want tools constrained to approved project roots so path traversal or symlink tricks cannot reach unrelated files.
- **Deliverables:**
  - Canonicalize paths.
  - Resolve symlinks before authorization.
  - Per-tool workspace scopes.
- **Acceptance Criteria:**
  - [ ] `../`, symlink and absolute escape tests blocked.
- **Required Evidence:**
  - Filesystem security tests.

### [ ] R2.6 — Secrets service and runtime injection

- **Migration:** `EXPAND`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.1
- **User Story:** As Nadir, I want credentials kept out of model context and renderer state so tools can authenticate without exposing secrets to the model.
- **Deliverables:**
  - Unify keychain/vault interface.
  - Inject secrets only into authorized tool/provider execution.
  - Remove plaintext reveal from normal renderer path.
- **Acceptance Criteria:**
  - [ ] Execution trace redacts secrets.
  - [ ] Model prompt snapshots contain no secrets unless explicit exceptional policy permits.
- **Required Evidence:**
  - Secret-leak tests.

### [ ] R2.7 — Untrusted-content labeling and prompt-injection controls

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.7, R2.3
- **User Story:** As a user, I want emails, web pages and retrieved documents treated as untrusted data so embedded instructions cannot silently override my policies.
- **Deliverables:**
  - Provenance/trust metadata on retrieved content.
  - Context builder separates system/user instructions from untrusted data.
  - Tool authorization never derives from retrieved text.
- **Acceptance Criteria:**
  - [ ] Prompt-injection fixtures cannot authorize tools or alter policy.
- **Required Evidence:**
  - Adversarial context tests.

### [ ] R2.8 — Sandbox worker runtime

- **Migration:** `SUPERSEDE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3
- **User Story:** As a user, I want generated or external code to run outside the Agent Engine control process so mistakes cannot directly compromise the host.
- **Deliverables:**
  - Separate worker process/container boundary.
  - Explicit filesystem/network/secret mounts.
- **Acceptance Criteria:**
  - [ ] Generated code cannot access host secrets or paths outside sandbox grants.
- **Required Evidence:**
  - Sandbox negative tests.

### [ ] R2.9 — Sandbox resource limits

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.8
- **User Story:** As a user, I want untrusted work limited by CPU, memory, process count and runtime so runaway code cannot freeze my machine.
- **Deliverables:**
  - CPU/RAM/time/process/network policies.
  - Kill and cleanup behavior.
- **Acceptance Criteria:**
  - [ ] Limit violations terminate job and record reason.
- **Required Evidence:**
  - Resource-limit tests.

### [ ] R2.10 — Safe staged patch application

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.5
- **User Story:** As a developer, I want stale patches rejected so Agent Engine never overwrites newer human edits.
- **Deliverables:**
  - Expected-original hash check.
  - Atomic replacement.
  - Recoverable backup/journal.
- **Acceptance Criteria:**
  - [ ] Stale patch leaves current file untouched.
  - [ ] Interrupted write is recoverable.
- **Required Evidence:**
  - Patch conflict tests.

### [ ] R2.11 — Checkpoint and rollback service

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.10, R2.10
- **User Story:** As Nadir, I want reversible operations to create real checkpoints so “undo” means a technically valid restore.
- **Deliverables:**
  - Git worktree/commit checkpoints.
  - File backup abstraction.
  - DB transaction/config snapshot interfaces.
- **Acceptance Criteria:**
  - [ ] Rollback restores pre-execution state for supported resource types.
- **Required Evidence:**
  - Rollback E2E tests.

### [ ] R2.12 — Diagnostics redaction

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.6
- **User Story:** As a user, I want diagnostics safe to share so troubleshooting exports never leak secrets or sensitive local paths unnecessarily.
- **Deliverables:**
  - Central redaction policy.
  - Test fixtures for tokens, API keys, credentials and personal file paths.
- **Acceptance Criteria:**
  - [ ] No seeded secret appears in exported diagnostics.
- **Required Evidence:**
  - Redaction test artifact.

### [ ] R2.13 — Release artifact trust

- **Migration:** `EXPAND`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.6
- **User Story:** As a user, I want updates verified against a trusted publisher identity so checksum-valid but attacker-signed releases are rejected.
- **Deliverables:**
  - Define trusted signing keys/rotation.
  - Verify manifest and artifact signatures against configured trust root.
- **Acceptance Criteria:**
  - [ ] Unknown signer rejected; key rotation tested.
- **Required Evidence:**
  - Release verification tests.

# R3 — Model & Resource Hub

## Objective

Make local and cloud intelligence one managed capability plane with quality/privacy/cost-aware routing.

## Hard exit gate

Agent Engine can automatically select and actually invoke the best eligible local or cloud model for a task, and the execution ledger proves the choice.

## Tasks

### [ ] R3.1 — Canonical Provider Registry

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.5
- **User Story:** As a Power User, I want all providers represented through one contract so switching providers does not change product semantics.
- **Deliverables:**
  - Provider capabilities/configuration/health contract.
  - Migrate existing provider config.
- **Acceptance Criteria:**
  - [ ] Existing providers pass common contract suite.
- **Required Evidence:**
  - Provider conformance tests.

### [ ] R3.2 — Model Capability Registry

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.1
- **User Story:** As the router, I need structured model capabilities so I can choose models by requirements rather than hard-coded names.
- **Deliverables:**
  - Track reasoning, coding, vision, tools, structured output, embeddings, context, price, latency, privacy and hardware metadata.
- **Acceptance Criteria:**
  - [ ] Router can query eligible models by capability constraints.
- **Required Evidence:**
  - Registry tests + sample catalog.

### [ ] R3.3 — Resource Manager

- **Migration:** `EXPAND`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As Nadir, I want Agent Engine to understand my CPU/GPU/RAM so it can recommend and schedule local models safely.
- **Deliverables:**
  - Refactor existing hardware telemetry into service/API.
  - Expose available/used memory and accelerator information.
- **Acceptance Criteria:**
  - [ ] Resource data is real and timestamped; UI does not invent throughput.
- **Required Evidence:**
  - Hardware tests on supported OSes.

### [ ] R3.4 — Managed local inference supervisor

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.3
- **User Story:** As Nadir, I want local inference started and stopped by Agent Engine so I do not install/configure a separate runtime for basic use.
- **Deliverables:**
  - Primary managed llama.cpp-compatible runtime lifecycle.
  - Health, logs, port management, graceful shutdown.
- **Acceptance Criteria:**
  - [ ] Fresh install can launch managed local runtime and complete a prompt.
- **Required Evidence:**
  - Clean-machine E2E.

### [ ] R3.5 — Local model catalog and recommendation

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.2, R3.3
- **User Story:** As an Everyday User, I want simple Fast/Balanced/Best Local recommendations so I do not need to understand quantization or model families.
- **Deliverables:**
  - Catalog metadata.
  - Hardware-fit scoring.
  - User-friendly recommendation API/UI.
- **Acceptance Criteria:**
  - [ ] Unsupported model is not recommended for detected hardware.
- **Required Evidence:**
  - Recommendation tests.

### [ ] R3.6 — Managed model download and verification

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.5
- **User Story:** As Nadir, I want Agent Engine to download and verify local models safely so setup is one-stop.
- **Deliverables:**
  - Download manager.
  - Checksum/provenance verification.
  - Resume and storage-location management.
- **Acceptance Criteria:**
  - [ ] Interrupted download resumes; checksum mismatch rejected.
- **Required Evidence:**
  - Download integration test.

### [ ] R3.7 — External local-runtime compatibility

- **Migration:** `INTEGRATE`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.1
- **User Story:** As a Power User, I want to connect an existing OpenAI-compatible/Ollama/LM Studio-style endpoint so Agent Engine can coexist with my preferred runtime.
- **Deliverables:**
  - Generic OpenAI-compatible local adapter.
  - Optional compatibility profiles.
- **Acceptance Criteria:**
  - [ ] External endpoint participates in normal routing/telemetry.
- **Required Evidence:**
  - Adapter conformance test.

### [ ] R3.8 — Privacy classes and data-routing policy

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3, R3.2
- **User Story:** As Nadir, I want sensitive tasks restricted to local or explicitly approved providers so cloud routing respects data sensitivity.
- **Deliverables:**
  - `LOCAL_ONLY`, `APPROVED_CLOUD`, `ANY_CONFIGURED` classes.
  - Profile/project/task overrides.
- **Acceptance Criteria:**
  - [ ] LOCAL_ONLY execution cannot dispatch network model calls.
- **Required Evidence:**
  - Privacy routing tests.

### [ ] R3.9 — Quality/cost/latency routing objective

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.2, R3.8
- **User Story:** As Nadir, I want the system to choose a model that actually succeeds cheaply rather than blindly enforcing a percentage split.
- **Deliverables:**
  - Replace hard 90/9/1 enforcement with constrained optimisation.
  - Use eval scores, cost, latency, privacy and health.
- **Acceptance Criteria:**
  - [ ] Routing choice is explainable from model/task metrics and constraints.
- **Required Evidence:**
  - Router decision fixtures.

### [ ] R3.10 — Cost-per-success integration

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.9
- **User Story:** As a Power User, I want model economics measured by successful task completion so cheap but unreliable models do not look artificially attractive.
- **Deliverables:**
  - Feed existing eval/cost data into routing metrics.
  - Track retries/human correction where available.
- **Acceptance Criteria:**
  - [ ] Dashboard/API can compare expected cost per successful completion by task/model.
- **Required Evidence:**
  - Golden eval report.

### [ ] R3.11 — Provider connection verification

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.1
- **User Story:** As Nadir, I want “Connected” to mean a real completion works so setup status is trustworthy.
- **Deliverables:**
  - Replace shallow health-only setup validation with tiny real completion where appropriate.
  - Distinguish auth, network, model and quota errors.
- **Acceptance Criteria:**
  - [ ] False-positive provider connectivity fixture fails.
- **Required Evidence:**
  - Provider setup E2E.

### [ ] R3.12 — Optional low-cost inference providers

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.1, R3.8, R3.9
- **User Story:** As a Power User, I want optional cost-optimised cloud routes so I can reduce spend without surrendering Agent Engine’s routing and privacy controls.
- **Deliverables:**
  - OpenAI-compatible cost-provider adapter.
  - Routing metadata and privacy disclosure.
- **Acceptance Criteria:**
  - [ ] Provider is optional and never overrides Agent Engine policy.
- **Required Evidence:**
  - Conformance + privacy-routing tests.

# R4 — Durable Jobs, Scheduling & Workflow Convergence

## Objective

Turn the legacy Phase 7 workflow work into a durable, restart-safe automation substrate shared by schedules, workflows, teams and background tasks.

## Hard exit gate

A workflow can execute, pause for approval, survive application restart, resume and finish without duplicate side effects.

## Tasks

### [ ] R4.1 — Canonical Job domain

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.1
- **User Story:** As a developer, I want durable jobs separated from UI/workflow definitions so background work has one reliable lifecycle.
- **Deliverables:**
  - Implement `Job`, `JobAttempt`, `JobEvent`, `JobDependency`, `JobArtifact`, `JobSchedule`.
- **Acceptance Criteria:**
  - [ ] Jobs persist independently of UI process.
- **Required Evidence:**
  - Repository/migration tests.

### [ ] R4.2 — Persistent local job queue

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.1
- **User Story:** As Nadir, I want queued work to survive restart so Agent Engine can handle long and scheduled tasks reliably.
- **Deliverables:**
  - SQLite-backed queue with leasing/claiming semantics.
- **Acceptance Criteria:**
  - [ ] Restart does not lose queued/running metadata.
- **Required Evidence:**
  - Crash/restart integration test.

### [ ] R4.3 — Worker service

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.2
- **User Story:** As a maintainer, I want background execution isolated from the UI process so jobs can continue and recover independently.
- **Deliverables:**
  - Worker loop.
  - Graceful shutdown.
  - Lease heartbeat.
- **Acceptance Criteria:**
  - [ ] Worker crash releases/reclaims jobs according to policy.
- **Required Evidence:**
  - Worker failure tests.

### [ ] R4.4 — Idempotency and retry model

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.3
- **User Story:** As Nadir, I want retries to avoid duplicate external side effects so transient failures do not create duplicate actions.
- **Deliverables:**
  - Idempotency keys.
  - Retry/backoff policy.
  - Non-retryable error classification.
- **Acceptance Criteria:**
  - [ ] Repeated delivery executes protected side effect once.
- **Required Evidence:**
  - Idempotency E2E fixture.

### [ ] R4.5 — Timeout, pause, resume and cancellation

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.3, R1.9
- **User Story:** As a user, I want background work controllable so long-running automation can be safely paused, resumed or stopped.
- **Deliverables:**
  - Job control API/state transitions.
- **Acceptance Criteria:**
  - [ ] Control state persists across restart.
- **Required Evidence:**
  - Job-control tests.

### [ ] R4.6 — Priority and concurrency controls

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.3, R4.3
- **User Story:** As a user, I want interactive work to remain responsive while background tasks run so automation does not monopolize my machine.
- **Deliverables:**
  - Priority queues.
  - Per-resource concurrency limits.
  - Resource Manager integration.
- **Acceptance Criteria:**
  - [ ] Interactive jobs pre-empt or outrank background queue as designed.
- **Required Evidence:**
  - Load tests.

### [ ] R4.7 — Timezone-aware scheduler

- **Migration:** `REFACTOR`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.2
- **User Story:** As Nadir, I want recurring tasks to run at the intended local time and survive restarts.
- **Deliverables:**
  - Persisted schedules.
  - IANA timezone support.
  - Missed-run policy.
- **Acceptance Criteria:**
  - [ ] DST and restart fixtures produce exactly intended occurrences.
- **Required Evidence:**
  - Scheduler time tests.

### [ ] R4.8 — Absorb legacy Phase 7 runtime

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.8, R4.1, R1.3
- **User Story:** As a maintainer, I want the completed workflow implementation reused rather than rewritten while it adopts durable jobs and canonical executions.
- **Deliverables:**
  - Map legacy workflow schema/nodes/runtime into canonical workflow service.
  - Preserve compatible serialization.
- **Acceptance Criteria:**
  - [ ] Legacy workflow can execute through jobs/executions with no shadow telemetry/policy path.
- **Required Evidence:**
  - Workflow compatibility suite.

### [ ] R4.9 — Human-in-the-loop workflow gates

- **Migration:** `INTEGRATE`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.4, R4.8
- **User Story:** As Nadir, I want workflows to pause on consequential decisions and resume only after exact approval.
- **Deliverables:**
  - Map workflow gate to central approval service.
  - Persist suspended state.
- **Acceptance Criteria:**
  - [ ] App restart during approval does not lose gate; changed operation requires new approval.
- **Required Evidence:**
  - HITL restart E2E.

### [ ] R4.10 — Workflow versioning and reproducibility

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8
- **User Story:** As a Power User, I want each run tied to an immutable workflow version so results remain explainable after edits.
- **Deliverables:**
  - Versioned definitions.
  - Draft/published states.
  - Execution references exact version.
- **Acceptance Criteria:**
  - [ ] Editing workflow cannot mutate already-running execution definition.
- **Required Evidence:**
  - Versioning tests.

### [ ] R4.11 — Visual workflow builder as editor only

- **Migration:** `REFACTOR`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8, R4.10
- **User Story:** As a Power User, I want a visual builder without making UI state the execution authority.
- **Deliverables:**
  - Bind React Flow canvas to canonical workflow schema.
  - Lossless import/export.
  - Dry-run path visualization.
- **Acceptance Criteria:**
  - [ ] Schema→canvas→schema round trip is lossless.
- **Required Evidence:**
  - Round-trip golden fixtures.

### [ ] R4.12 — Programmatic tool-execution sandbox

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.8, R4.3
- **User Story:** As a Power User, I want one planned script to perform several deterministic tool operations so complex workflows use fewer model turns.
- **Deliverables:**
  - Restricted Python/JS execution bridge to approved tools.
  - No direct host secret/filesystem access beyond grants.
- **Acceptance Criteria:**
  - [ ] Script can perform approved multi-tool sequence; disallowed tool/network access fails.
- **Required Evidence:**
  - Sandbox-tool RPC tests.

### [ ] R4.13 — ExecutionTarget abstraction

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.8, R4.3
- **User Story:** As a developer, I want tasks to declare runtime requirements independently of location so local, sandbox, Docker and remote execution can share semantics.
- **Deliverables:**
  - `ExecutionTarget` interface.
  - Initial local/sandbox/docker/devcontainer/SSH profiles where feasible.
- **Acceptance Criteria:**
  - [ ] Same simple job passes conformance suite on each supported target.
- **Required Evidence:**
  - Target conformance tests.

# R5 — Agent Engine 0.5 — Nadir Founder Dogfood

## Objective

Freeze breadth and use Agent Engine for real daily work until the MVP-N release gate passes.

## Hard exit gate

Every MVP-N founder journey and release-gate item passes on Nadir’s normal machine without developer intervention.

## Tasks

### [ ] R5.1 — Core Pack MVP

- **Migration:** `EXPAND`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1, R2, R3, R4
- **User Story:** As Nadir, I want one stable Core Pack for projects, chat, files, models, approvals and tasks so everyday use does not depend on unfinished domain packs.
- **Deliverables:**
  - Package Core capabilities and default policies.
- **Acceptance Criteria:**
  - [ ] Core Pack installs/enables as one unit and satisfies MVP-J1/J7/J8/J9/J10/J12.
- **Required Evidence:**
  - Founder acceptance run.

### [ ] R5.2 — Writing Pack MVP

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.12, R4.8
- **User Story:** As Nadir, I want notes transformed into a reviewed article so Agent Engine replaces ad-hoc writing chats for real work.
- **Deliverables:**
  - Outline, draft, style review, claim review workflow/skills.
  - Persistent document artifact.
- **Acceptance Criteria:**
  - [ ] MVP-J2 passes on two real articles.
- **Required Evidence:**
  - Saved founder artifacts + execution traces.

### [ ] R5.3 — Research Pack MVP

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.10, R4.8
- **User Story:** As Nadir, I want deep evidence-aware research so Agent Engine can support decisions and content creation.
- **Deliverables:**
  - Research planner, source collection interface, claim/evidence model, synthesis artifact.
- **Acceptance Criteria:**
  - [ ] MVP-J3 passes with traceable source provenance.
- **Required Evidence:**
  - Founder research report.

### [ ] R5.4 — Developer Pack MVP

- **Migration:** `EXPAND`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.11, R4.8
- **User Story:** As Nadir, I want Agent Engine to safely improve Agent Engine itself so founder dogfooding exercises the hardest execution path.
- **Deliverables:**
  - Diagnose→plan→worktree→implement→test→review workflow.
- **Acceptance Criteria:**
  - [ ] MVP-J4 passes on a real nontrivial repository issue.
- **Required Evidence:**
  - PR/diff, test logs, review artifact.

### [ ] R5.5 — Finance Reader Pack MVP

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.12, R2.6, R3.8
- **User Story:** As Nadir, I want read-only invoice/bank analysis so the architecture is tested on structured, sensitive business data without autonomous money movement.
- **Deliverables:**
  - Invoice field extraction.
  - CSV import.
  - Category/match proposal.
  - Uncertainty display.
- **Acceptance Criteria:**
  - [ ] MVP-J6 passes on sample/redacted documents; no write/payment capability exists.
- **Required Evidence:**
  - Finance-reader evaluation fixture.

### [ ] R5.6 — Founder dogfood telemetry

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.11
- **User Story:** As CTO/Product Owner, I want structured dogfood feedback so roadmap decisions come from failures in real use rather than feature enthusiasm.
- **Deliverables:**
  - Capture task, expected/actual result, manual intervention, satisfaction, cost and failure reason.
- **Acceptance Criteria:**
  - [ ] At least one week of real founder tasks captured before gate review, unless product owner explicitly shortens period.
- **Required Evidence:**
  - Dogfood report.

### [ ] R5.7 — Founder release blocker policy

- **Migration:** `NEW`
- **Target release:** `0.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R5.6
- **User Story:** As CTO, I want P0/P1 dogfood defects to block feature expansion so reliability debt is not buried under new features.
- **Deliverables:**
  - Severity definitions.
  - Release-blocking issue label/workflow.
- **Acceptance Criteria:**
  - [ ] No open P0/P1 against MVP guarantees at release decision.
- **Required Evidence:**
  - Issue query/report.

# R6 — Knowledge & Context Engine

## Objective

Unify fragmented memory/RAG/context mechanisms into an adaptive knowledge system that chooses retrieval automatically.

## Hard exit gate

The user can ask questions over code, notes, long PDFs, CSVs and sessions without selecting a RAG technology; context provenance and strategy are visible.

## Tasks

### [ ] R6.1 — Separate memory domains

- **Migration:** `REFACTOR`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.6
- **User Story:** As a user, I want conversation, personal, project, working, procedural and execution memory separated so retention and retrieval rules match what the data actually is.
- **Deliverables:**
  - Define stores/scopes for Conversation Memory, User Memory, Project Knowledge, Working Memory, Procedural Memory, Execution History.
  - Migrate legacy observational/vector records.
- **Acceptance Criteria:**
  - [ ] Each memory type has explicit scope/retention/provenance.
- **Required Evidence:**
  - Migration + isolation tests.

### [ ] R6.2 — RetrievalRouter

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.1
- **User Story:** As an Everyday User, I want Agent Engine to choose the correct retrieval strategy automatically so I never configure RAG manually.
- **Deliverables:**
  - Strategy interface and routing logic for exact, SQL, FTS, vector, hybrid, tree, code-aware and recent-session retrieval.
- **Acceptance Criteria:**
  - [ ] Fixture set routes each content/task class to an eligible strategy.
- **Required Evidence:**
  - Retrieval routing tests.

### [ ] R6.3 — Full-text and lexical retrieval

- **Migration:** `EXPAND`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2
- **User Story:** As a user, I want exact terms, identifiers and recent notes retrieved reliably so semantic similarity does not hide literal matches.
- **Deliverables:**
  - FTS/index service and ranking.
- **Acceptance Criteria:**
  - [ ] Exact identifier/phrase fixtures rank correctly.
- **Required Evidence:**
  - Retrieval eval.

### [ ] R6.4 — Vector/hybrid retrieval

- **Migration:** `KEEP`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2
- **User Story:** As a user, I want semantic recall over heterogeneous project knowledge so conceptually related information can be found.
- **Deliverables:**
  - Retain/refactor existing Chroma/vector layer.
  - Add hybrid fusion with lexical results.
- **Acceptance Criteria:**
  - [ ] Hybrid eval beats or equals best single strategy on benchmark set.
- **Required Evidence:**
  - RAG eval report.

### [ ] R6.5 — Code-aware retrieval

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2
- **User Story:** As a developer, I want symbol/AST/repository-aware retrieval so coding agents use precise code context instead of embedding entire repositories.
- **Deliverables:**
  - Symbol index, AST metadata, path/module graph and Git-aware signals where useful.
- **Acceptance Criteria:**
  - [ ] Code navigation benchmark retrieves relevant definitions/usages with bounded context.
- **Required Evidence:**
  - Code retrieval eval.

### [ ] R6.6 — Structured data retrieval

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2, R2.8
- **User Story:** As a user, I want CSV/spreadsheet/database questions handled structurally so numerical answers are not produced from lossy text embeddings.
- **Deliverables:**
  - Tabular parser/profile.
  - SQL/DataFrame execution path in sandbox.
- **Acceptance Criteria:**
  - [ ] Numerical fixture answers are computed deterministically.
- **Required Evidence:**
  - Structured-data tests.

### [ ] R6.7 — Hierarchical long-document retrieval

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2, R0.6
- **User Story:** As Nadir, I want contracts, manuals and annual reports navigated by structure so long documents do not need to fit in one context window.
- **Deliverables:**
  - Evaluate/adapt PageIndex-style tree retrieval.
  - Document tree/index abstraction.
- **Acceptance Criteria:**
  - [ ] Long-document QA eval demonstrates bounded context and acceptable accuracy.
- **Required Evidence:**
  - Benchmark vs vector/native-context baselines.

### [ ] R6.8 — ContextEngine expansion

- **Migration:** `REFACTOR`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.7, R6.2
- **User Story:** As the system, I need scope, security, retrieval, deduplication, compression and packing in one context pipeline so model calls receive only justified information.
- **Deliverables:**
  - Refactor existing Context Builder into staged Context Engine.
- **Acceptance Criteria:**
  - [ ] Every context item has provenance and reason.
  - [ ] Sensitive-field rules still apply.
- **Required Evidence:**
  - Context golden tests.

### [ ] R6.9 — Content-aware compression benchmark

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.8, R0.6
- **User Story:** As a Power User, I want token-heavy logs/code/JSON compressed only when quality is preserved so context savings do not silently make agents worse.
- **Deliverables:**
  - Benchmark native context reduction against Headroom-style compression and no compression.
  - Measure quality/cost/latency/information loss.
- **Acceptance Criteria:**
  - [ ] Adopt compression only for task/content classes where eval gate passes.
- **Required Evidence:**
  - Published benchmark report.

### [ ] R6.10 — Reversible compressed context

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.9
- **User Story:** As an agent, I want compressed tool/document content linked to recoverable originals so detail can be fetched on demand without paying for it upfront.
- **Deliverables:**
  - Original-content handle/store.
  - Retrieve tool with permission checks.
- **Acceptance Criteria:**
  - [ ] Original bytes/chunks recover correctly within retention policy.
- **Required Evidence:**
  - Round-trip tests.

### [ ] R6.11 — Context provenance UI

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.8, R1.11
- **User Story:** As Nadir, I want to inspect which sources entered an answer so I can debug wrong or surprising context.
- **Deliverables:**
  - Execution detail panel for source, retrieval strategy, size, compression status.
- **Acceptance Criteria:**
  - [ ] User can trace answer context without reading logs.
- **Required Evidence:**
  - UI E2E screenshot/test.

### [ ] R6.12 — Semantic cache redesign

- **Migration:** `REFACTOR`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.8
- **User Story:** As a user, I want cache hits safe and fresh so semantically similar but stale/high-risk answers are not reused blindly.
- **Deliverables:**
  - Task-specific thresholds.
  - Data/version/context fingerprints.
  - Volatility/high-risk bypass.
- **Acceptance Criteria:**
  - [ ] Cache invalidates on relevant source/skill/model-policy version changes.
- **Required Evidence:**
  - Cache invalidation tests.

# R7 — Skills 2.0, Departments & Capability Packs

## Objective

Transform legacy skill management into a versioned, permission-aware, evidence-backed expertise platform.

## Hard exit gate

A task can automatically select an appropriate skill from a large library without loading all skills into context; skills carry versions, dependencies, permissions and quality evidence.

## Tasks

### [ ] R7.1 — Canonical Skill manifest

- **Migration:** `REFACTOR`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.4
- **User Story:** As a Package Author, I want one skill manifest so instructions, tools, permissions, dependencies and evaluation metadata are portable and inspectable.
- **Deliverables:**
  - Schema for identity, version, description, triggers, permissions, dependencies, tools, models, evals and lineage.
- **Acceptance Criteria:**
  - [ ] Schema validates built-in and imported sample skills.
- **Required Evidence:**
  - Schema tests.

### [ ] R7.2 — Migrate legacy skill registry

- **Migration:** `INTEGRATE`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1
- **User Story:** As a maintainer, I want existing skill discovery/editor/search preserved under the canonical manifest so prior work remains useful.
- **Deliverables:**
  - Adapters/migration for old Phase 6 registry and collections.
- **Acceptance Criteria:**
  - [ ] Existing local skills remain discoverable/editable after migration.
- **Required Evidence:**
  - Migration fixture.

### [ ] R7.3 — Skill versioning and lineage

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1
- **User Story:** As a user, I want to know which skill version produced an outcome and how it evolved so behavior is reproducible.
- **Deliverables:**
  - Immutable published versions.
  - Parent/derived relationships.
- **Acceptance Criteria:**
  - [ ] Execution references exact skill version.
- **Required Evidence:**
  - Version lineage tests.

### [ ] R7.4 — Skill permission and dependency model

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1, R2.3
- **User Story:** As Nadir, I want a skill’s required access visible before use so installing expertise does not silently grant broad tool permissions.
- **Deliverables:**
  - Permission/dependency declarations.
  - Install/run validation.
- **Acceptance Criteria:**
  - [ ] Missing permission/dependency blocks or degrades explicitly.
- **Required Evidence:**
  - Permission tests.

### [ ] R7.5 — Skill retrieval and ranking

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2, R7.3
- **User Story:** As an Everyday User, I want Agent Engine to find the right skill automatically so a large library remains useful.
- **Deliverables:**
  - Lexical/semantic candidate retrieval.
  - Rank by relevance, historical quality, project fit, dependency health, risk and cost.
- **Acceptance Criteria:**
  - [ ] Relevant skill outranks unrelated high-popularity skill on benchmark tasks.
- **Required Evidence:**
  - Skill retrieval eval.

### [ ] R7.6 — Skill execution evidence

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.11, R7.3
- **User Story:** As a Power User, I want to know whether a skill actually works so trust is based on outcomes rather than descriptions.
- **Deliverables:**
  - Record selected/applied/completed/fallback/failure outcome per skill version.
- **Acceptance Criteria:**
  - [ ] Skill detail can aggregate real execution outcomes.
- **Required Evidence:**
  - Evidence aggregation tests.

### [ ] R7.7 — Pattern import compatibility

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1, R0.6
- **User Story:** As a user, I want to import useful reusable prompt/pattern libraries so Agent Engine benefits from mature knowledge without requiring separate runtimes.
- **Deliverables:**
  - Fabric-style pattern importer/converter.
  - Source/provenance retained.
- **Acceptance Criteria:**
  - [ ] Imported sample becomes valid local Skill without executing foreign runtime code.
- **Required Evidence:**
  - Importer fixtures.

### [ ] R7.8 — Agent-skill format interoperability

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1
- **User Story:** As a Package Author, I want common skill-file conventions importable/exportable where semantics match so Agent Engine participates in the wider skill ecosystem.
- **Deliverables:**
  - Compatibility mapper and loss-report for unsupported fields.
- **Acceptance Criteria:**
  - [ ] Round-trip supported subset documented and tested.
- **Required Evidence:**
  - Compatibility tests.

### [ ] R7.9 — Department model

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1
- **User Story:** As Nadir, I want coherent groups of expertise such as Technology, Finance or Marketing so I can add capability at the domain level rather than managing hundreds of prompts.
- **Deliverables:**
  - Department schema with specialist roles, skills, reviewers, policies, templates and recommended models.
- **Acceptance Criteria:**
  - [ ] Department loads only relevant skill metadata/instructions on demand.
- **Required Evidence:**
  - Department activation tests.

### [ ] R7.10 — Reviewer-class roles

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.9
- **User Story:** As Nadir, I want important work independently reviewed so the same agent does not automatically certify its own output.
- **Deliverables:**
  - Producer/reviewer relationship and review result schema.
- **Acceptance Criteria:**
  - [ ] Reviewer receives original requirements + artifact independently and can reject completion.
- **Required Evidence:**
  - Producer/reviewer E2E.

### [ ] R7.11 — Capability Pack format

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.1, R4.10
- **User Story:** As an Everyday User, I want to install “Developer” or “Finance Reader” as one package so complex capability does not require manual assembly.
- **Deliverables:**
  - Pack manifest supporting skills, departments, DSPy programs, workflows, tools, policies, evals, templates and UI metadata.
- **Acceptance Criteria:**
  - [ ] Pack install/disable affects declared components atomically.
- **Required Evidence:**
  - Pack lifecycle tests.

### [ ] R7.12 — Formalize MVP packs

- **Migration:** `INTEGRATE`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11, R5
- **User Story:** As Nadir, I want the 0.5 founder capabilities formalized as versioned packs so they become the foundation for 1.0 distribution.
- **Deliverables:**
  - Convert Core, Personal, Writing, Research, Developer, Finance Reader into canonical packs.
- **Acceptance Criteria:**
  - [ ] MVP journeys still pass using pack packaging.
- **Required Evidence:**
  - Regression suite.

# R8 — Evaluation & Controlled Learning

## Objective

Make real outcomes drive model, retrieval, workflow and skill improvement without uncontrolled self-modification.

## Hard exit gate

Agent Engine can compare versions using real task evidence and promote an improvement only through explicit trust-state gates.

## Tasks

### [ ] R8.1 — Unified Evaluation framework

- **Migration:** `EXPAND`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.10, R7.6
- **User Story:** As a developer, I want one eval framework for models, DSPy programs, retrieval, skills and workflows so quality claims are comparable and automatable.
- **Deliverables:**
  - Generalize existing Model Eval Suite.
  - Dataset/version/metric/result schemas.
- **Acceptance Criteria:**
  - [ ] Same runner can evaluate at least model, skill and retrieval targets.
- **Required Evidence:**
  - Eval framework tests.

### [ ] R8.2 — Task outcome taxonomy

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.11
- **User Story:** As the learning system, I need structured success/failure/fallback/human-correction outcomes so improvement uses meaningful evidence.
- **Deliverables:**
  - Outcome schema and capture points.
- **Acceptance Criteria:**
  - [ ] Executions classify terminal outcome without relying only on model self-report.
- **Required Evidence:**
  - Outcome fixtures.

### [ ] R8.3 — Capability-specific metric packs

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.1
- **User Story:** As a maintainer, I want finance, writing, coding and retrieval evaluated by appropriate metrics so one generic score does not hide important errors.
- **Deliverables:**
  - Metric bundles for MVP domains.
- **Acceptance Criteria:**
  - [ ] Each MVP pack has at least one deterministic or human-grounded metric set.
- **Required Evidence:**
  - Metric documentation + fixtures.

### [ ] R8.4 — Skill effectiveness analytics

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.6, R8.2
- **User Story:** As a Power User, I want to see completion, fallback, correction, cost and latency by skill version so weak expertise becomes visible.
- **Deliverables:**
  - Aggregation and UI/API.
- **Acceptance Criteria:**
  - [ ] Metrics exclude incomparable tasks or label segmentation clearly.
- **Required Evidence:**
  - Analytics tests.

### [ ] R8.5 — Model effectiveness analytics

- **Migration:** `EXPAND`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.1, R3.9
- **User Story:** As Nadir, I want router decisions informed by my real workloads so model choice improves over time.
- **Deliverables:**
  - Join eval and production outcome data carefully.
  - Guard against low-sample overfitting.
- **Acceptance Criteria:**
  - [ ] Router can consume task-specific success/cost estimates with confidence bounds/sample count.
- **Required Evidence:**
  - Routing analytics report.

### [ ] R8.6 — Retrieval effectiveness analytics

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.2, R8.1
- **User Story:** As a developer, I want answer quality linked to retrieval strategy so the system learns when vector, lexical or tree retrieval works best.
- **Deliverables:**
  - Record strategy/context/result eval metrics.
- **Acceptance Criteria:**
  - [ ] Benchmark/report compares strategies by task class.
- **Required Evidence:**
  - Retrieval outcome report.

### [ ] R8.7 — Learning Analyzer

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.2, R7.6
- **User Story:** As Nadir, I want recurring successes and failures converted into proposed reusable improvements so the system becomes better from real work.
- **Deliverables:**
  - Detect repeated procedural patterns/failures.
  - Generate candidate recommendations, not automatic trusted changes.
- **Acceptance Criteria:**
  - [ ] Analyzer can explain evidence supporting a candidate.
- **Required Evidence:**
  - Candidate-generation fixtures.

### [ ] R8.8 — Skill trust lifecycle

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.3, R8.7
- **User Story:** As a user, I want new self-generated expertise to prove itself before replacing trusted behavior.
- **Deliverables:**
  - States: Draft, Candidate, Experimental, Trusted, Deprecated, Blocked.
  - Transition policies.
- **Acceptance Criteria:**
  - [ ] Trusted version cannot be overwritten in-place.
- **Required Evidence:**
  - State-transition tests.

### [ ] R8.9 — Candidate skill generation

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.7, R8.8
- **User Story:** As a Power User, I want reusable lessons captured as candidate skills so successful procedures are not lost in chat history.
- **Deliverables:**
  - Generate candidate manifest/content from evidence with provenance links.
- **Acceptance Criteria:**
  - [ ] Candidate cites source executions and has no trusted status automatically.
- **Required Evidence:**
  - Candidate fixture.

### [ ] R8.10 — DSPy optimisation pipeline

- **Migration:** `EXPAND`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.1, R1.12
- **User Story:** As a developer, I want repeatable intelligent programs optimized against evals so quality/cost improvements are measurable rather than prompt folklore.
- **Deliverables:**
  - DSPy optimizer integration.
  - Versioned candidate program.
- **Acceptance Criteria:**
  - [ ] Optimized candidate compared against baseline on held-out set before promotion.
- **Required Evidence:**
  - DSPy eval report.

### [ ] R8.11 — Canary and promotion workflow

- **Migration:** `NEW`
- **Target release:** `0.6`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.8, R8.9, R8.10
- **User Story:** As a user, I want candidate skills/programs tried safely on limited traffic before becoming trusted defaults.
- **Deliverables:**
  - Canary policy, sample limits, rollback, human promotion UI.
- **Acceptance Criteria:**
  - [ ] Failed canary automatically stops candidate and preserves trusted version.
- **Required Evidence:**
  - Canary E2E.

# R9 — Developer Platform

## Objective

Expose Agent Engine as the same project-aware agent from modern IDEs and provide disciplined software-engineering workflows.

## Hard exit gate

The same Agent Engine project/session can be used from Desktop and an ACP-capable IDE while sharing execution history, context and permissions.

## Tasks

### [ ] R9.1 — ACP server

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.3
- **User Story:** As a Developer, I want IDEs to talk to Agent Engine through a standard agent protocol so each editor does not require a separate intelligence implementation.
- **Deliverables:**
  - ACP server mapped to project/session/execution APIs.
- **Acceptance Criteria:**
  - [ ] Reference ACP client can start/continue a real Agent Engine session.
- **Required Evidence:**
  - Protocol conformance test.

### [ ] R9.2 — Agent Engine MCP server

- **Migration:** `EXPAND`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3, R1.3
- **User Story:** As a Developer, I want tools/resources exposed through MCP so external compatible clients can access Agent Engine capabilities under the same permissions.
- **Deliverables:**
  - MCP tools/resources wrapping safe Agent Engine services.
- **Acceptance Criteria:**
  - [ ] MCP call produces normal execution/policy/audit records.
- **Required Evidence:**
  - MCP integration test.

### [ ] R9.3 — IDE interoperability matrix

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R9.1, R9.2
- **User Story:** As Nadir, I want to work from Zed, VS Code and other compatible IDEs without separate Agent Engine brains.
- **Deliverables:**
  - Test/document ACP/MCP clients including Zed and VS Code ecosystem; add thin UX extensions only where valuable.
- **Acceptance Criteria:**
  - [ ] At least two IDE surfaces use same project/session history.
- **Required Evidence:**
  - Cross-IDE acceptance report.

### [ ] R9.4 — Spec-driven development workflow

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8, R0.6
- **User Story:** As Nadir, I want features developed from explicit requirements through plan, tasks, implementation and convergence so coding agents do not jump straight to code.
- **Deliverables:**
  - Adopt concepts/templates for constitution/specify/clarify/plan/tasks/implement/converge.
  - Provenance/license attribution where adapted.
- **Acceptance Criteria:**
  - [ ] Workflow produces persistent specs/tasks and requires verification before convergence.
- **Required Evidence:**
  - SDD golden project.

### [ ] R9.5 — Bug repair workflow

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8
- **User Story:** As a Developer, I want diagnosis, reproduction, fix and verification separated so agents fix assessed causes rather than symptoms.
- **Deliverables:**
  - Assess→reproduce→diagnose→fix→verify workflow.
- **Acceptance Criteria:**
  - [ ] Known bug fixture cannot reach verified without reproducer and post-fix test.
- **Required Evidence:**
  - Bug workflow fixture.

### [ ] R9.6 — Idea assessment workflow

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8, R5.3
- **User Story:** As Nadir, I want product ideas researched and shaped before implementation so Agent Engine can recommend clarify/stop as well as build.
- **Deliverables:**
  - Intake→research→define→shape→decision artifacts.
- **Acceptance Criteria:**
  - [ ] Workflow records evidence and unresolved assumptions.
- **Required Evidence:**
  - Idea assessment fixture.

### [ ] R9.7 — Git worktree manager

- **Migration:** `EXPAND`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.5, R2.11
- **User Story:** As a Developer, I want parallel coding work isolated so agents cannot corrupt one another’s branches.
- **Deliverables:**
  - Create/list/remove guarded worktrees.
  - Workspace/path policy integration.
- **Acceptance Criteria:**
  - [ ] Parallel feature jobs edit disjoint worktrees.
- **Required Evidence:**
  - Git E2E.

### [ ] R9.8 — Independent code/security review

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.10, R9.4
- **User Story:** As Nadir, I want completed code independently reviewed for correctness and security before it is considered merge-ready.
- **Deliverables:**
  - Reviewer skill/agent workflows with original acceptance criteria.
- **Acceptance Criteria:**
  - [ ] Review rejection returns work to implementation state.
- **Required Evidence:**
  - Review E2E fixture.

### [ ] R9.9 — Release verification workflow

- **Migration:** `NEW`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.8, R15 later enhances packaging
- **User Story:** As a Developer, I want build/test/migration/release checks captured as evidence so “done” is a release claim, not a coding-agent opinion.
- **Deliverables:**
  - Quality gate workflow, packaging hooks, artifact report.
- **Acceptance Criteria:**
  - [ ] Release candidate cannot be marked verified while required checks fail.
- **Required Evidence:**
  - Release gate test.

### [ ] R9.10 — Architecture/diagram capability

- **Migration:** `INTEGRATE`
- **Target release:** `0.7`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11
- **User Story:** As a Developer, I want architecture specs and diagrams generated from project truth so old architecture-visualization work becomes a useful Developer Pack feature rather than a core milestone.
- **Deliverables:**
  - Move/adapt legacy Phase 10 concepts under Developer Pack.
- **Acceptance Criteria:**
  - [ ] Diagram/spec generation is a skill/workflow with normal provenance and artifacts.
- **Required Evidence:**
  - Developer Pack regression.

# R10 — Personal Superhub & Communication

## Objective

Make communication, email, calendar and personal automation additional surfaces over the same Agent Engine state rather than separate assistants.

## Hard exit gate

A conversation begun on desktop can continue through an enabled communication channel with the same project/session permissions and execution history.

## Tasks

### [ ] R10.1 — Communication Gateway

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.6, R4.1
- **User Story:** As Nadir, I want one gateway for external channels so messaging integrations share authentication, sessions and delivery semantics.
- **Deliverables:**
  - Inbound/outbound envelope model.
  - Channel identity mapping.
  - Delivery status/retry.
- **Acceptance Criteria:**
  - [ ] Two adapters pass same gateway conformance tests.
- **Required Evidence:**
  - Gateway tests.

### [ ] R10.2 — Absorb legacy channel adapters

- **Migration:** `INTEGRATE`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R10.1, R1.13
- **User Story:** As a maintainer, I want existing Slack/Teams/Discord/Mattermost code reused behind the gateway instead of maintained as independent runtimes.
- **Deliverables:**
  - Wrap Phase 5C adapters.
  - Remove direct model/tool execution from channel code.
- **Acceptance Criteria:**
  - [ ] Legacy channels create/continue canonical sessions only.
- **Required Evidence:**
  - Adapter regression suite.

### [ ] R10.3 — Optional personal messaging adapters

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R10.1
- **User Story:** As Nadir, I want optional personal channels such as Telegram/WhatsApp-style integrations without making any one external communication product a core dependency.
- **Deliverables:**
  - Connector interface and selected adapters or compatibility modules.
- **Acceptance Criteria:**
  - [ ] Channels can be enabled/disabled independently.
- **Required Evidence:**
  - Connector acceptance tests.

### [ ] R10.4 — Email capability

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3, R10.1
- **User Story:** As Nadir, I want Agent Engine to read/summarize/draft email under explicit permissions so everyday work can happen from the same system.
- **Deliverables:**
  - Email connector/tool set.
  - Read vs send permissions.
  - Draft-first workflow.
- **Acceptance Criteria:**
  - [ ] Send requires configured consequential-action policy/approval.
- **Required Evidence:**
  - Email sandbox/integration tests.

### [ ] R10.5 — Calendar capability

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.3
- **User Story:** As Nadir, I want schedules and meeting context available to Agent Engine so planning and briefs can use real calendar information.
- **Deliverables:**
  - Read/create/update capability split by permissions.
- **Acceptance Criteria:**
  - [ ] Read-only profile cannot create/update events.
- **Required Evidence:**
  - Calendar contract tests.

### [ ] R10.6 — Notifications service

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R10.1, R4.1
- **User Story:** As a user, I want jobs/workflows to notify me through selected channels without embedding channel logic in every workflow.
- **Deliverables:**
  - Notification abstraction, templates, delivery records.
- **Acceptance Criteria:**
  - [ ] Workflow emits channel-independent notification request.
- **Required Evidence:**
  - Notification tests.

### [ ] R10.7 — Personal task system

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.6, R4.7
- **User Story:** As Nadir, I want lightweight tasks linked to projects/executions so actionable follow-ups do not disappear in conversations.
- **Deliverables:**
  - Task CRUD/state/relations.
  - Optional scheduling.
- **Acceptance Criteria:**
  - [ ] Task links back to originating execution/artifact.
- **Required Evidence:**
  - Task E2E.

### [ ] R10.8 — Cross-channel continuity

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R10.1
- **User Story:** As Nadir, I want to continue the same session from desktop or messaging so channel choice does not create fragmented memory.
- **Deliverables:**
  - Session/channel mapping and resume controls.
- **Acceptance Criteria:**
  - [ ] Message on second channel continues authorized session and preserves history.
- **Required Evidence:**
  - Cross-channel E2E.

### [ ] R10.9 — Personal recurring briefs

- **Migration:** `NEW`
- **Target release:** `0.8`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4.7, R10.6
- **User Story:** As Nadir, I want configurable morning/project briefs produced as normal durable workflows so proactive assistance remains inspectable and controllable.
- **Deliverables:**
  - Brief templates using jobs, knowledge and notifications.
- **Acceptance Criteria:**
  - [ ] Brief executes once per schedule and records sources/cost.
- **Required Evidence:**
  - Scheduled brief acceptance.

# R11 — Business Capability Packs

## Objective

Expand domain competence through installable packs rather than core-code growth.

## Hard exit gate

Installing/disabling a pack changes domain capability without modifying the Execution Kernel or bypassing its security/evaluation model.

## Tasks

### [ ] R11.1 — Finance & Bookkeeping Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11, R8, R6.6
- **User Story:** As a small-business user, I want invoice ingestion, reconciliation, budgeting and reporting assistance with explicit review gates so finance work is faster without autonomous money movement.
- **Deliverables:**
  - Invoice ingestion, transaction matching, classification, reconciliation workflow, budgeting/forecasting, financial reviewer, finance policies/evals.
- **Acceptance Criteria:**
  - [ ] Authoritative-system writes remain staged/approval-gated; no payment capability by default.
- **Required Evidence:**
  - Finance eval suite.

### [ ] R11.2 — Marketing & Behavioral Intelligence Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11, R8
- **User Story:** As an entrepreneur, I want marketing output grounded in customer evidence, positioning and behavioral principles so copy is not generic prompt-generated prose.
- **Deliverables:**
  - Customer research, positioning, brand voice, trust/status/ownership/loss/friction/value frameworks, copy workflows, claim reviewer, experiment templates.
- **Acceptance Criteria:**
  - [ ] Pack prohibits fabricated scarcity/testimonials/claims and separates hypotheses from measured conversion evidence.
- **Required Evidence:**
  - Marketing eval + policy tests.

### [ ] R11.3 — Revenue Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11
- **User Story:** As a business owner, I want pricing, sales enablement, retention and revenue-operation skills so Agent Engine can support the revenue lifecycle.
- **Deliverables:**
  - Pricing, outreach, enablement, retention, pipeline/revops workflows.
- **Acceptance Criteria:**
  - [ ] Pack uses connectors only through declared permissions.
- **Required Evidence:**
  - Pack acceptance cases.

### [ ] R11.4 — Product Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11, R8
- **User Story:** As a product leader, I want discovery, requirements, UX review and experimentation workflows so product decisions are evidence-linked.
- **Deliverables:**
  - Discovery, PRD/spec, UX audit, roadmap, experiment skills/workflows.
- **Acceptance Criteria:**
  - [ ] Key decisions retain assumptions/evidence.
- **Required Evidence:**
  - Product cases.

### [ ] R11.5 — Data & Sheets Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.6, R7.11
- **User Story:** As a business user, I want structured spreadsheet/SQL analysis so calculations are deterministic where possible and explanations are model-assisted.
- **Deliverables:**
  - CSV/Excel/SQL analysis, charts, forecasting, export artifacts.
- **Acceptance Criteria:**
  - [ ] Numerical transformations have reproducible code/queries.
- **Required Evidence:**
  - Data benchmark.

### [ ] R11.6 — Operations Pack

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4, R7.11
- **User Story:** As a small business, I want SOP, process, service and recurring-report automation so repetitive operational work can become controlled workflows.
- **Deliverables:**
  - SOP authoring, process analysis, automation templates, service/ops reporting.
- **Acceptance Criteria:**
  - [ ] Automations expose approval/rollback requirements clearly.
- **Required Evidence:**
  - Ops workflow cases.

# R12 — Teams, Multi-Agent Execution & Collaboration

## Objective

Add autonomous collaboration only after single-execution and workflow reliability is proven.

## Hard exit gate

Multiple specialists can work concurrently in isolated scopes, synthesize results and survive partial failure without duplicate or conflicting side effects.

## Tasks

### [ ] R12.1 — Canonical Team model

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.9, R1.1
- **User Story:** As a Power User, I want a Team represented explicitly so collaborative reasoning has roles, goals, budgets and termination rules.
- **Deliverables:**
  - Team, TeamMember, delegation and synthesis schema.
- **Acceptance Criteria:**
  - [ ] Team run is an execution tree, not a separate telemetry universe.
- **Required Evidence:**
  - Team model tests.

### [ ] R12.2 — Specialist instantiation

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R12.1, R7.9
- **User Story:** As Nadir, I want specialists created from departments/skills on demand so expertise is reusable without permanent swarms.
- **Deliverables:**
  - Resolve role→skills/tools/model constraints.
- **Acceptance Criteria:**
  - [ ] Specialist context contains only declared/relevant expertise.
- **Required Evidence:**
  - Instantiation tests.

### [ ] R12.3 — Parallel delegation

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R12.1, R4.6
- **User Story:** As a user, I want independent subtasks run concurrently when useful so complex work can finish faster without losing control.
- **Deliverables:**
  - Parent/child executions/jobs, budgets, cancellation propagation.
- **Acceptance Criteria:**
  - [ ] Partial child failure handled according to team policy.
- **Required Evidence:**
  - Parallel execution E2E.

### [ ] R12.4 — Isolated write surfaces

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.5, R9.7
- **User Story:** As a Developer, I want parallel agents restricted to disjoint workspaces/resources so collaboration cannot create race-driven corruption.
- **Deliverables:**
  - Resource/write-scope declarations and conflict detection.
- **Acceptance Criteria:**
  - [ ] Intentional overlap fixture is blocked or serialized.
- **Required Evidence:**
  - Conflict tests.

### [ ] R12.5 — Independent synthesis and review

- **Migration:** `NEW`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.10, R12.3
- **User Story:** As Nadir, I want team outputs synthesized and optionally reviewed independently so the loudest subagent does not automatically become the final answer.
- **Deliverables:**
  - Synthesis stage and reviewer option.
- **Acceptance Criteria:**
  - [ ] Synthesis includes attribution/conflict notes where members disagree.
- **Required Evidence:**
  - Team review fixture.

### [ ] R12.6 — Absorb legacy Swarm UI

- **Migration:** `INTEGRATE`
- **Target release:** `0.9`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R12.1
- **User Story:** As a maintainer, I want prior swarm/progress UI reused as a Team view so old Phase 7 work is not discarded.
- **Deliverables:**
  - Map swarm strips/cost display to canonical child executions.
- **Acceptance Criteria:**
  - [ ] UI shows real child execution state/cost only.
- **Required Evidence:**
  - UI E2E.

### [ ] R12.7 — Absorb collaborative rooms

- **Migration:** `INTEGRATE`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16 later for true multi-user auth
- **User Story:** As a maintainer, I want old room/project/task governance evolved into shared collaboration instead of remaining a parallel model.
- **Deliverables:**
  - Map rooms to shared workspace/project collaboration concepts.
- **Acceptance Criteria:**
  - [ ] Single-user/local room features do not bypass canonical project/task models.
- **Required Evidence:**
  - Compatibility tests.

# R13 — Marketplace & Ecosystem

## Objective

Enable growth through signed, permission-aware packages rather than continued expansion of core.

## Hard exit gate

A third-party package can be inspected, installed, evaluated, updated and removed without modifying Agent Engine core or bypassing its permission model.

## Tasks

### [ ] R13.1 — Unified package manifest

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7.11
- **User Story:** As a Package Author, I want one package format for skills, departments, workflows, tools, connectors and packs so distribution is coherent.
- **Deliverables:**
  - Manifest schema, package IDs, versions, compatibility ranges.
- **Acceptance Criteria:**
  - [ ] Package can contain multiple supported component types and validate deterministically.
- **Required Evidence:**
  - Schema tests.

### [ ] R13.2 — Package permissions and risk manifest

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.1, R2.3
- **User Story:** As a user, I want to review filesystem/network/secret/tool permissions before installation so marketplace convenience does not hide access risk.
- **Deliverables:**
  - Permission summary and install consent model.
- **Acceptance Criteria:**
  - [ ] Install blocks undeclared privilege escalation.
- **Required Evidence:**
  - Permission escalation tests.

### [ ] R13.3 — Package provenance/signatures

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.1, R0.6
- **User Story:** As a user, I want publisher identity and package integrity verified so I can distinguish trusted updates from tampered code.
- **Deliverables:**
  - Signing, verification, provenance metadata.
- **Acceptance Criteria:**
  - [ ] Tampered package rejected.
- **Required Evidence:**
  - Signature tests.

### [ ] R13.4 — Dependency resolver

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.1
- **User Story:** As a Package Author, I want dependencies resolved predictably so packs can reuse shared tools/skills without manual setup.
- **Deliverables:**
  - Version constraints, conflict reporting, lock representation.
- **Acceptance Criteria:**
  - [ ] Conflicting dependency fixture produces deterministic actionable error.
- **Required Evidence:**
  - Resolver tests.

### [ ] R13.5 — Private/local registry

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.1, R13.2, R13.3
- **User Story:** As Nadir, I want a local/private registry first so package lifecycle is proven before a public ecosystem adds supply-chain risk.
- **Deliverables:**
  - Local package index, install/update/remove.
- **Acceptance Criteria:**
  - [ ] Offline local package install/update/remove works.
- **Required Evidence:**
  - Registry E2E.

### [ ] R13.6 — Marketplace quality evidence

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.4, R13.5
- **User Story:** As a user, I want package/skill reliability based on real outcomes so popularity alone does not imply quality.
- **Deliverables:**
  - Aggregate evals, completion/failure, freshness and security history.
- **Acceptance Criteria:**
  - [ ] Quality display clearly separates local evidence from publisher claims.
- **Required Evidence:**
  - Quality aggregation tests.

### [ ] R13.7 — Public registry

- **Migration:** `NEW`
- **Target release:** `2.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.5, R13.6
- **User Story:** As a Package Author, I want optional public distribution so third parties can extend Agent Engine safely.
- **Deliverables:**
  - Registry service/API, moderation and publisher flows.
- **Acceptance Criteria:**
  - [ ] Private/local use remains fully functional without public service.
- **Required Evidence:**
  - Registry integration tests.

### [ ] R13.8 — Stable SDKs

- **Migration:** `NEW`
- **Target release:** `2.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R13.1, R9.2
- **User Story:** As a Developer, I want Python/TypeScript SDKs only after internal contracts stabilize so extensions are not built on churn.
- **Deliverables:**
  - Versioned SDKs generated/wrapped from stable public APIs.
- **Acceptance Criteria:**
  - [ ] Compatibility policy and semver tests exist.
- **Required Evidence:**
  - SDK examples + tests.

# R14 — Operational Excellence & Advanced Observability

## Objective

Make failures diagnosable, costs attributable and backups/restores trustworthy for sustained use.

## Hard exit gate

A failed execution can be diagnosed from persisted traces/logs/events without reproducing it manually, and backups are proven restorable.

## Tasks

### [ ] R14.1 — Structured event/trace correlation

- **Migration:** `EXPAND`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R1.11, R4.1
- **User Story:** As a maintainer, I want logs, execution events, jobs and model/tool calls correlated by IDs so debugging follows one trace.
- **Deliverables:**
  - Trace/span conventions and propagation.
- **Acceptance Criteria:**
  - [ ] One query can reconstruct cross-service execution chronology.
- **Required Evidence:**
  - Trace fixture.

### [ ] R14.2 — OpenTelemetry-compatible export

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R14.1
- **User Story:** As a Power User/Admin, I want standard telemetry export so advanced installations can use existing observability stacks.
- **Deliverables:**
  - Optional OTLP traces/metrics/logs.
- **Acceptance Criteria:**
  - [ ] Disabled by default local-first; enabled export passes collector test.
- **Required Evidence:**
  - OTLP integration test.

### [ ] R14.3 — Provider/tool/queue health

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.1, R4.2
- **User Story:** As a user, I want degraded dependencies visible so failures are explained before repeated retries waste time/cost.
- **Deliverables:**
  - Health metrics and UI status.
- **Acceptance Criteria:**
  - [ ] Degraded provider/tool alters routing/retry behavior according to policy.
- **Required Evidence:**
  - Health tests.

### [ ] R14.4 — Quality and cost attribution dashboards

- **Migration:** `REFACTOR`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.4, R3.10
- **User Story:** As Nadir, I want cost by project/task/model/skill and cost-per-success so optimization reflects useful outcomes.
- **Deliverables:**
  - Replace legacy 90/9/1 dashboard emphasis.
- **Acceptance Criteria:**
  - [ ] Dashboard numbers reconcile with ledger.
- **Required Evidence:**
  - Reconciliation tests.

### [ ] R14.5 — Backup service

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.1, R7.3, R4.1
- **User Story:** As Nadir, I want projects, sessions, configs and critical metadata backed up so local-first does not mean single-disk fragility.
- **Deliverables:**
  - Backup manifest, encryption option, destination interface.
- **Acceptance Criteria:**
  - [ ] Backup includes documented critical stores and excludes/references large regenerable caches appropriately.
- **Required Evidence:**
  - Backup fixture.

### [ ] R14.6 — Restore verification

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R14.5
- **User Story:** As Nadir, I want backups automatically tested so “backup succeeded” means data can actually be restored.
- **Deliverables:**
  - Automated restore-to-temp verification and report.
- **Acceptance Criteria:**
  - [ ] Corrupt/incomplete backup fails verification.
- **Required Evidence:**
  - Restore drill.

### [ ] R14.7 — Migration and retention policy

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R6.1
- **User Story:** As a maintainer, I want explicit data migrations and retention controls so long-lived installations remain upgradeable and privacy-manageable.
- **Deliverables:**
  - Migration compatibility policy, retention settings, purge workflows.
- **Acceptance Criteria:**
  - [ ] Upgrade from supported prior release and rollback/recovery path tested.
- **Required Evidence:**
  - Migration matrix.

# R15 — Product Quality, Accessibility & Distribution

## Objective

Turn the engineering system into a dependable cross-platform product that non-maintainers can install and operate.

## Hard exit gate

A technically capable user can install Agent Engine on supported platforms, complete onboarding, run local/cloud work, recover from common errors and use core flows with keyboard/screen-reader support.

## Tasks

### [ ] R15.1 — Cross-platform installer and packaging

- **Migration:** `EXPAND`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.13, R3.4
- **User Story:** As an Everyday User, I want a normal installer so Agent Engine does not require cloning a repository or assembling toolchains.
- **Deliverables:**
  - Signed installers/packages for supported OSes.
  - Dependency bundling strategy.
- **Acceptance Criteria:**
  - [ ] Clean-machine installation test passes per supported OS.
- **Required Evidence:**
  - CI release artifacts + VM tests.

### [ ] R15.2 — First-run onboarding

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R3.5, R3.6, R7.12
- **User Story:** As Nadir, I want setup to detect hardware, configure a local model and optionally connect cloud providers so first use is guided and one-stop.
- **Deliverables:**
  - Wizard for profile, storage, local model, cloud provider and initial packs.
- **Acceptance Criteria:**
  - [ ] Fresh user reaches successful first prompt without docs.
- **Required Evidence:**
  - Onboarding E2E.

### [ ] R15.3 — Simple / Power / Developer modes

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R7, R9
- **User Story:** As different users, we want the same engine exposed at appropriate complexity so power does not make basic use intimidating.
- **Deliverables:**
  - UI visibility/preferences only; no divergent backends.
- **Acceptance Criteria:**
  - [ ] Switching modes changes exposure, not execution semantics/data.
- **Required Evidence:**
  - UI tests.

### [ ] R15.4 — Light theme

- **Migration:** `KEEP`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a user in bright environments, I want a carefully tuned light theme so Agent Engine is comfortable outside dark mode.
- **Deliverables:**
  - Light token palette, OS preference, manual toggle.
- **Acceptance Criteria:**
  - [ ] WCAG AA contrast for normal text.
- **Required Evidence:**
  - Automated contrast tests.

### [ ] R15.5 — High-contrast mode

- **Migration:** `KEEP`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a user with visual impairments, I want high-contrast presentation and strong focus indicators.
- **Deliverables:**
  - High-contrast tokens and focus styles.
- **Acceptance Criteria:**
  - [ ] Target AAA contrast where applicable; keyboard focus always visible.
- **Required Evidence:**
  - Accessibility audit.

### [ ] R15.6 — Reduced motion

- **Migration:** `KEEP`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a motion-sensitive user, I want nonessential animation minimized according to OS/user preference.
- **Deliverables:**
  - `prefers-reduced-motion` handling and app setting.
- **Acceptance Criteria:**
  - [ ] No essential information conveyed only by motion.
- **Required Evidence:**
  - Accessibility test.

### [ ] R15.7 — Keyboard and screen-reader system

- **Migration:** `EXPAND`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** None
- **User Story:** As a keyboard/screen-reader user, I want all primary actions accessible without a mouse.
- **Deliverables:**
  - Configurable shortcuts, focus management, ARIA names/roles/status announcements.
- **Acceptance Criteria:**
  - [ ] MVP and core settings flows usable keyboard-only; automated a11y checks pass.
- **Required Evidence:**
  - Playwright/a11y report.

### [ ] R15.8 — Error recovery UX

- **Migration:** `NEW`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R14.3
- **User Story:** As an Everyday User, I want failures explained with safe recovery actions so infrastructure errors do not look like mysterious chat failures.
- **Deliverables:**
  - Error taxonomy and user-facing recovery actions for provider, model, tool, storage and job failures.
- **Acceptance Criteria:**
  - [ ] Known error fixtures render actionable, non-fabricated messages.
- **Required Evidence:**
  - UX error tests.

### [ ] R15.9 — Import/export and local portability

- **Migration:** `EXPAND`
- **Target release:** `1.0`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R14.5, R7.3
- **User Story:** As Nadir, I want to move projects/settings/skills between machines so local-first data remains portable.
- **Deliverables:**
  - Versioned export bundle, selective import, conflict report.
- **Acceptance Criteria:**
  - [ ] Round-trip preserves supported entities and does not export secrets by default.
- **Required Evidence:**
  - Portability test.

# R16 — Team / Business Server

## Objective

Extend the same domain model to authenticated shared work without changing core execution semantics.

## Hard exit gate

Two users with different permissions cannot access each other’s restricted projects through direct APIs, retrieval, tools or indirect execution paths.

## Tasks

### [ ] R16.1 — Canonical User/Organization model

- **Migration:** `NEW`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R0.4
- **User Story:** As a Team Admin, I want users and organizations represented explicitly so shared deployment has durable identity boundaries.
- **Deliverables:**
  - User/org/workspace membership schema.
- **Acceptance Criteria:**
  - [ ] Identity propagates into ExecutionContext.
- **Required Evidence:**
  - Auth integration tests.

### [ ] R16.2 — RBAC and scoped authorization

- **Migration:** `NEW`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.1, R2.3
- **User Story:** As a Team Admin, I want role-based access so projects, tools and administrative actions are limited appropriately.
- **Deliverables:**
  - Roles/permissions and resource checks.
- **Acceptance Criteria:**
  - [ ] Unauthorized direct and indirect access blocked.
- **Required Evidence:**
  - Authorization matrix tests.

### [ ] R16.3 — Shared projects/workspaces

- **Migration:** `EXPAND`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.2, R1.6
- **User Story:** As a team, we want shared projects using the same sessions, knowledge, workflows and artifacts model as local Agent Engine.
- **Deliverables:**
  - Shared ownership/membership and conflict semantics.
- **Acceptance Criteria:**
  - [ ] Local and server project APIs retain common contract.
- **Required Evidence:**
  - Shared-project tests.

### [ ] R16.4 — PostgreSQL production backend verification

- **Migration:** `KEEP`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.3
- **User Story:** As an Admin, I want the existing PostgreSQL abstraction proven under real server concurrency so shared deployments are reliable.
- **Deliverables:**
  - Production migrations, locking/concurrency tests, performance baselines.
- **Acceptance Criteria:**
  - [ ] Canonical repository suite passes on PostgreSQL under concurrent scenarios.
- **Required Evidence:**
  - DB conformance report.

### [ ] R16.5 — Shared workers and admin console

- **Migration:** `NEW`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R4, R16.2
- **User Story:** As a Team Admin, I want shared job capacity and administrative visibility so team automation can be operated centrally.
- **Deliverables:**
  - Worker registration/queues, admin health/policy controls.
- **Acceptance Criteria:**
  - [ ] Worker cannot execute tenant/project work without authorized job scope.
- **Required Evidence:**
  - Worker auth tests.

### [ ] R16.6 — Absorb collaborative-room governance

- **Migration:** `INTEGRATE`
- **Target release:** `1.5`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.2, R12.7
- **User Story:** As a maintainer, I want legacy room roles/tasks migrated into the canonical user/project/task model so no duplicate authorization model survives.
- **Deliverables:**
  - Migration/adapters for old Phase 5B.
- **Acceptance Criteria:**
  - [ ] No room-specific permission bypass remains.
- **Required Evidence:**
  - Migration/security tests.

# R17 — Cloud & Enterprise

## Objective

Deploy Agent Engine at scale while preserving the same execution, package and policy semantics.

## Hard exit gate

Desktop, server and distributed-worker deployments execute the same workflow/package semantics; tenant isolation and enterprise identity are security-tested.

## Tasks

### [ ] R17.1 — Server deployment profile

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16
- **User Story:** As an Enterprise Admin, I want Agent Engine deployable as a server service so organizations can centralize execution and governance.
- **Deliverables:**
  - Container/service deployment, config/secrets model, health endpoints.
- **Acceptance Criteria:**
  - [ ] Server passes same core contract suite as desktop sidecar.
- **Required Evidence:**
  - Deployment conformance tests.

### [ ] R17.2 — Distributed worker protocol

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R17.1, R4.13
- **User Story:** As an Admin, I want CPU/GPU/sandbox workers attachable securely so compute can scale independently of the control plane.
- **Deliverables:**
  - Authenticated worker registration, job lease protocol, capability advertisement.
- **Acceptance Criteria:**
  - [ ] Malicious/untrusted worker cannot claim unauthorized job scope.
- **Required Evidence:**
  - Worker security tests.

### [ ] R17.3 — Object storage and large-artifact model

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R17.1, R1.10
- **User Story:** As an organization, I want large artifacts stored efficiently without changing artifact semantics.
- **Deliverables:**
  - Object-store adapter and signed access references.
- **Acceptance Criteria:**
  - [ ] Artifact API remains consistent across local/filesystem/object storage.
- **Required Evidence:**
  - Storage conformance tests.

### [ ] R17.4 — Hybrid local/cloud execution

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R17.2, R3.8
- **User Story:** As a user, I want selected work to run locally while organizational jobs run centrally so privacy/performance needs can coexist.
- **Deliverables:**
  - Routing/target policy across local and remote workers.
- **Acceptance Criteria:**
  - [ ] LOCAL_ONLY data never routes to remote worker/cloud target.
- **Required Evidence:**
  - Hybrid routing tests.

### [ ] R17.5 — SSO and directory sync

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.1
- **User Story:** As an Enterprise Admin, I want SSO and lifecycle sync so access follows organizational identity rather than local accounts.
- **Deliverables:**
  - OIDC/SAML strategy, directory provisioning/deprovisioning.
- **Acceptance Criteria:**
  - [ ] Disabled user loses new execution access promptly; audit preserved.
- **Required Evidence:**
  - Identity tests.

### [ ] R17.6 — Tenant isolation

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R16.2, R17.2, R17.3
- **User Story:** As an Enterprise Admin, I want hard tenant boundaries so one customer cannot access another customer’s data through retrieval, jobs, tools or logs.
- **Deliverables:**
  - Tenant ID propagation, DB/object-store/worker isolation controls.
- **Acceptance Criteria:**
  - [ ] Cross-tenant adversarial suite passes.
- **Required Evidence:**
  - Isolation test report.

### [ ] R17.7 — Enterprise secrets and policy administration

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.6, R16.2
- **User Story:** As an Enterprise Admin, I want centrally managed secrets and policies so regulated environments can govern providers/tools consistently.
- **Deliverables:**
  - External secret-manager adapters, org/project policy hierarchy.
- **Acceptance Criteria:**
  - [ ] Lower scope cannot override immutable higher-scope deny policy.
- **Required Evidence:**
  - Policy hierarchy tests.

### [ ] R17.8 — Compliance, audit retention and disaster recovery

- **Migration:** `NEW`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R14, R17.6
- **User Story:** As an Enterprise Admin, I want documented controls, retention and recovery so Agent Engine can support regulated operational requirements.
- **Deliverables:**
  - Compliance mapping framework, tamper-evident audit retention, DR runbooks/tests.
- **Acceptance Criteria:**
  - [ ] Restore/failover drill meets documented targets.
- **Required Evidence:**
  - DR/compliance evidence pack.

### [ ] R17.9 — SLA/support tooling

- **Migration:** `INTEGRATE`
- **Target release:** `3.x`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2.12, R14
- **User Story:** As an Enterprise operator, I want support bundles and service health data so incidents can be triaged without exposing unnecessary customer content.
- **Deliverables:**
  - Support bundle, health history, redacted diagnostics, entitlement hooks if commercialized.
- **Acceptance Criteria:**
  - [ ] Support bundle contains required diagnostics and passes redaction suite.
- **Required Evidence:**
  - Support artifact test.

# R18 — Advanced Intelligence & Future Options

## Objective

Pursue higher-order intelligence only after sufficient production/eval data exists; none of these are prerequisites for a trustworthy core product.

## Hard exit gate

Each advanced feature has a demonstrated eval/ROI case and can be disabled without breaking core Agent Engine.

## Tasks

### [ ] R18.1 — Specialist distillation

- **Migration:** `SUPERSEDE`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8, R14.4
- **User Story:** As an operator, I want high-volume stable tasks distilled into smaller specialists when measured ROI justifies it.
- **Deliverables:**
  - Candidate detection from volume/cost/quality data.
  - Training/quantization pipeline only when lawful/data-appropriate.
- **Acceptance Criteria:**
  - [ ] Distilled model meets quality floor and lowers measured cost/latency on held-out eval.
- **Required Evidence:**
  - Distillation report.

### [ ] R18.2 — Fine-tuning/adapters

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.1
- **User Story:** As a developer, I want optional domain adaptation for repeatable workloads where prompting/DSPy is insufficient.
- **Deliverables:**
  - Dataset governance, training/eval registry, rollback to base model.
- **Acceptance Criteria:**
  - [ ] Fine-tune never promotes without held-out improvement and data-governance review.
- **Required Evidence:**
  - Training/eval report.

### [ ] R18.3 — Adaptive routing learning

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.5, R3.9
- **User Story:** As a Power User, I want routing improved from actual outcomes so the system learns the best model for my workload while respecting hard constraints.
- **Deliverables:**
  - Bandit/learned policy experiments with guardrails and baseline fallback.
- **Acceptance Criteria:**
  - [ ] Learned router can be disabled and never violates privacy/risk constraints.
- **Required Evidence:**
  - A/B routing eval.

### [ ] R18.4 — Adaptive retrieval learning

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8.6
- **User Story:** As a user, I want retrieval strategy improve from outcome data so context quality becomes increasingly task-specific.
- **Deliverables:**
  - Strategy-selection learner using R6/R8 evidence.
- **Acceptance Criteria:**
  - [ ] Learned strategy beats baseline on held-out benchmark without larger unacceptable cost.
- **Required Evidence:**
  - Retrieval A/B eval.

### [ ] R18.5 — Workflow optimisation suggestions

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R8, R14
- **User Story:** As a Power User, I want Agent Engine to identify bottlenecks and propose safer/cheaper workflow variants so automation improves from operations data.
- **Deliverables:**
  - Trace analysis, candidate variant generation, simulation/eval.
- **Acceptance Criteria:**
  - [ ] Suggestions are proposals; production workflow unchanged until promotion.
- **Required Evidence:**
  - Workflow optimization report.

### [ ] R18.6 — Ambient proactive intelligence

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R10, R8
- **User Story:** As Nadir, I want Agent Engine to surface meaningful upcoming work and anomalies without constant prompting while remaining bounded by policies and notification preferences.
- **Deliverables:**
  - Condition/event watchers, relevance thresholds, proactive-notification budgets.
- **Acceptance Criteria:**
  - [ ] No consequential action occurs solely because of ambient detection without normal authorization.
- **Required Evidence:**
  - Proactive assistant eval.

### [ ] R18.7 — Computer-use capability

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R2, R4.13
- **User Story:** As a user, I want Agent Engine to operate software without APIs as a fallback so legacy desktop workflows can still be automated.
- **Deliverables:**
  - Accessibility-tree/vision/input capability with sandbox/policy controls.
- **Acceptance Criteria:**
  - [ ] Structured API/tool remains preferred when available; high-risk UI actions require approval.
- **Required Evidence:**
  - Computer-use safety suite.

### [ ] R18.8 — Personal distributed compute

- **Migration:** `NEW`
- **Target release:** `Future`
- **Initial maturity:** `S0` unless `docs/STATUS.md` verifies a higher level from legacy work.
- **Dependencies:** R17.2
- **User Story:** As Nadir, I want trusted home/work machines to contribute compute optionally so large local workloads can run without mandatory cloud infrastructure.
- **Deliverables:**
  - Trusted-node pairing, capability advertisement, encrypted job transport.
- **Acceptance Criteria:**
  - [ ] Node cannot access unrelated project data; revocation stops new jobs.
- **Required Evidence:**
  - Node security tests.


---

# PART IV — LEGACY ROADMAP ABSORPTION MATRIX

This appendix prevents accidental rewrites. The **legacy status is not automatically trusted as current maturity**; R0 verifies it. Legacy Phase 7 is marked “reported complete” based on the product owner’s latest update even where the uploaded old roadmap still shows unchecked sub-items.

| Legacy task | Legacy capability | Canonical destination | Action |
|---|---|---|---|
| 0.1 | Repository Restructure | Platform foundation | KEEP |
| 0.2 | Local API Contract | R1/R0 contracts | REFACTOR + KEEP compatibility |
| 0.3 | SQLite/PostgreSQL Repository Pattern | R1/R16 data layer | KEEP + VERIFY |
| 0.4 | Feature Flags | Capability/release configuration | KEEP + EXPAND |
| 0.5 | CI/CD Baseline | Cross-cutting release gates | REFACTOR |
| 1.1 | Model Router Hardening | R3 Model Hub | KEEP + EXPAND |
| 1.2 | DSPy Pipeline Registry | R1/R8 DSPy Program Layer | KEEP + INTEGRATE |
| 1.3 | Observational/Vector Memory | R6 memory domains | REFACTOR + MIGRATE |
| 1.4 | Guardrail Policy Engine | R2 mandatory policy boundary | KEEP + INTEGRATE |
| 1.5 | Cost Tracker | R1 ledger + R14 attribution | KEEP + INTEGRATE |
| 1.6 | Unified Session Store | R1 canonical sessions | KEEP + EXPAND scoping |
| 1.7 | Semantic Cache | R6 context/cache | KEEP + REFACTOR policy |
| 1.8 | Context Builder | R6 Context Engine | KEEP + EXPAND |
| 1.9 | Model Eval Suite | R8 unified eval framework | KEEP + EXPAND |
| 1.10 | Execution Router | R1/R3 routing | REFACTOR; remove rigid 90/9/1 enforcement |
| 2.1 | Tauri Shell | Desktop product | KEEP |
| 2.2 | Sidecar Bundling & Signing | R15/R2 distribution trust | KEEP + EXPAND |
| 2.3 | Secure Credential Storage | R2 Secrets Service | KEEP + INTEGRATE |
| 2.4 | Auto-Update Channel | R15 distribution | KEEP + harden trust |
| 3.1 | Chat Shell & Home | MVP/Desktop | KEEP UI + REWIRE |
| 3.2 | Skill Selector & Slash Commands | R7 Skills 2.0 | KEEP + INTEGRATE |
| 3.3 | Inline Approval Cards | R2 approval UX | KEEP + bind to backend auth |
| 3.4 | Model & Agent Switcher | R3/R12 | KEEP UI + make execution-real |
| 3.5 | Session Sidebar & Search | R1 Sessions | KEEP + INTEGRATE |
| 3.6 | Document Drop & RAG Ingestion | R6 Knowledge Engine | KEEP UI + REFACTOR backend strategy |
| 3.7 | My Agent Screen | R6/R8 Personal memory/learning UX | RECLASSIFY + REFACTOR |
| 3.8 | Scheduled Tasks Screen | R4 durable scheduler | KEEP UI + REWIRE |
| 3.9 | Universal Chat Input | Experience layer | KEEP |
| 3.10 | Mode Landing Page | Experience layer / packs | KEEP + evolve |
| 3.11 | Featured Cases | Packs/onboarding | KEEP content, verify claims |
| 4.0 | Foundation hardening | R0–R2 | VERIFY; retain fixes |
| 4.1 | Projects & Workspaces | R1 Project model | REFACTOR backend ownership |
| 4.2 | Provider Setup | R3 Model Hub | KEEP + INTEGRATE |
| 4.3 | Real Execution Engine | R1 Execution Kernel | REFACTOR/ABSORB |
| 4.4 | Approval Queue/Safety | R2 | KEEP UI/data; make mandatory |
| 4.5 | Cost Dashboard | R14 | KEEP UI concepts; truthful ledger only |
| 4.6 | Policy Editor/Audit | R2/R14 | KEEP + harden coupling/immutability |
| 4.7 | Hardware Telemetry | R3 Resource Manager | KEEP + REFACTOR fabricated metrics |
| 4.8 | Settings & Diagnostics | R2/R15 | KEEP + complete + redact |
| 4.9 | Streamlit Demotion | Developer diagnostics | KEEP demotion; ARCHIVE duplicate product UI |
| 5.1 | Adapter Interface & Registry | Compatibility connectors | REFACTOR around ACP/MCP/Execution APIs |
| 5.2 | Claude Code Adapter | External-agent compatibility | OPTIONAL connector; no core dependency |
| 5.3 | Codex Adapter | External-agent compatibility | OPTIONAL connector; no core dependency |
| 5.4 | OpenClaw Adapter | R10 communication compatibility | OPTIONAL connector |
| 5.5 | Goose Adapter | Generic ACP compatibility path | SUPERSEDE dedicated dependency with ACP support |
| 5.6 | Hermes/Cursor/Windsurf Adapters | R9/R10 compatibility | SUPERSEDE one-offs with ACP/MCP where practical |
| 5B.1 | Room ↔ Project Mapping | R12/R16 collaboration | REFACTOR |
| 5B.2 | Room Roles & Governance | R16 RBAC | REFACTOR; remove duplicate auth model |
| 5B.3 | Room Tasks | R10 tasks / R4 jobs | REFACTOR concepts |
| 5C.1 | Slack Adapter | R10 Gateway | KEEP + INTEGRATE |
| 5C.2 | Teams Adapter | R10 Gateway | KEEP + INTEGRATE |
| 5C.3 | Discord Adapter | R10 Gateway | KEEP + INTEGRATE |
| 5C.4 | Mattermost Adapter | R10 Gateway | KEEP + INTEGRATE |
| 6.1 | Multi-Tool Skill Discovery | R7 Skills 2.0 | KEEP + EXPAND |
| 6.2 | Skill Editor | R7 Skills 2.0 | KEEP |
| 6.3 | Collections & Search | R7 skill retrieval | KEEP + EXPAND with quality ranking |
| 6.4 | Skill Registry Integration | R7/R13 | REFACTOR to canonical manifest |
| 6.5 | Remote Skill Discovery | R13 marketplace | DEFER public path; preserve connectors |
| 7.1 | Workflow Schema & Runtime | R4 Workflow Runtime | KEEP + ABSORB |
| 7.2 | Visual Workflow Builder | R4.11 | Reported complete; VERIFY + REWIRE |
| 7.3 | Human-in-the-Loop Gates | R4.9 / R2 | Reported complete; VERIFY + bind central approval |
| 7.4 | Swarm Screen | R12 Team UI | Reported complete; RECLASSIFY + later integrate |
| 7.5 | Workflow Builder Screen | R4.11 | Reported complete; VERIFY schema/runtime authority |
| 8.x | Advanced RAG/Memory | R6 | SUPERSEDED by Knowledge & Context Engine |
| 9.x | Observability/Distillation/GPU | R14/R18/R4 | SPLIT; move core telemetry earlier, distillation later |
| 10.x | Architecture Visualization | R9 Developer Pack | RECLASSIFY |
| 11.x | Multi-user/Tenant | R16/R17 | DEFER until local product stable |
| 12.x | Registry/SDK/Marketplace | R13 | REDESIGN around unified package format |
| 13.x | Cloud SaaS | R17 | FUTURE deployment profile |
| 14.1 | Compliance Pack | R17 | DEFER enterprise |
| 14.2 | Sandboxed Tool Execution | R2 | MOVE EARLY |
| 14.3 | SLA/Support | R17 | DEFER enterprise |
| 15.x | Accessibility/Theme | R15 + cross-cutting | MOVE FORWARD into release quality |

---

# PART V — EXTERNAL CONCEPT ADOPTION TRACK

External innovation is absorbed through **concept adoption, code/library adoption, protocol compatibility, importers, or optional connectors**. The user should not have to install separate frameworks to obtain core Agent Engine functionality.

| Capability concept | Adoption into Agent Engine | Roadmap destination |
|---|---|---|
| Structured spec-driven software development | Adopt specify/plan/tasks/implement/converge and bug/idea-assessment process concepts; adapt permissible templates with provenance. | R9 |
| Reusable real-world AI patterns | Build importer/compatibility; strong patterns become Skills and later DSPy programs. | R7/R8 |
| Content-aware context compression | Benchmark and selectively integrate/adapt only where quality-adjusted cost improves. | R6 |
| Reversible compressed context | Preserve original content handles for on-demand recovery. | R6 |
| Hierarchical/vectorless long-document retrieval | Add as a retrieval strategy alongside vector/hybrid/structured retrieval. | R6 |
| Closed learning loop from completed work | Turn reusable lessons into candidate skills, never silently trusted mutations. | R8 |
| Evidence-driven skill lineage and evolution | First-class skill versions, quality evidence, candidate/trusted lifecycle. | R7/R8 |
| Programmatic tool calling | Sandboxed script can make multiple approved tool calls between model turns. | R4 |
| Multiple execution backends | `ExecutionTarget` abstraction for local/sandbox/container/remote workers. | R4/R17 |
| Flow vs autonomous team separation | Workflows for controlled automation; Teams for ambiguity benefiting from specialist collaboration. | R4/R12 |
| Departments / company-style specialists | Installable domain expertise with reviewer-class roles. | R7/R11 |
| Low-cost inference aggregation | Optional provider route governed by Agent Engine router/privacy policy. | R3 |
| Communication gateways | Native Agent Engine gateway + optional compatibility connectors; channels remain surfaces over canonical sessions. | R10 |
| IDE interoperability | ACP for agent clients, MCP for tools/resources; thin IDE-specific UX only where useful. | R9 |

---

# PART VI — CROSS-CUTTING DEFINITION OF DONE

Every task/PR must satisfy all applicable sections below.

## Architecture
- [ ] Uses canonical domain entities and boundaries.
- [ ] No new shadow execution, permission, session, memory or telemetry system.
- [ ] Architecture change has ADR where required.

## Behavior
- [ ] Real behavior replaces demos/stubs in production paths.
- [ ] Failure/cancellation/timeout states are explicit.
- [ ] No success claim without corresponding state/evidence.

## Security
- [ ] Permissions and trust boundaries documented.
- [ ] Secrets are redacted and injected only where required.
- [ ] Protected action fails closed.
- [ ] External/untrusted content cannot grant authority.

## Observability
- [ ] Execution/job IDs propagate through logs/events.
- [ ] Relevant model/tool/skill/workflow usage is recorded.
- [ ] Errors are diagnosable without UI-only state.

## Cost
- [ ] Real provider usage is recorded where available.
- [ ] Estimates are labeled estimates.
- [ ] Routing changes evaluated on quality-adjusted cost, not token price alone.

## Testing
- [ ] Unit tests for local logic.
- [ ] Contract tests for shared interfaces.
- [ ] Integration tests for real subsystem composition.
- [ ] Behavioral E2E for user-visible guarantees.
- [ ] Negative/failure tests for safety/reliability claims.
- [ ] Clean-install/release verification when release-facing.

## Persistence and migration
- [ ] Persistent changes include migration.
- [ ] Restart behavior is tested where applicable.
- [ ] Rollback/recovery path exists for consequential migrations.

## UX/accessibility
- [ ] Loading, empty, success, failure and cancellation states implemented as applicable.
- [ ] Keyboard operation supported for primary actions.
- [ ] Screen-reader names/roles/status semantics present.
- [ ] UI never fabricates telemetry or execution state.

## Documentation
- [ ] `STATUS.md` maturity/evidence updated.
- [ ] User docs describe actual released behavior, not planned capability.
- [ ] External code/concept adoption retains required attribution/license metadata.

---

# PART VII — IMPLEMENTATION PRIORITY FROM CURRENT BASELINE

Gemini should execute in this order unless `docs/STATUS.md` proves a task already satisfies its acceptance criteria:

```text
R0  Truth Reset
 ↓
R1  Execution Kernel
 ↓
R2  Security & Recovery
 ↓
R3  Model & Resource Hub
 ↓
R4  Durable Jobs + Legacy Phase 7 Workflow Convergence
 ↓
R5  Nadir Founder MVP / dogfood gate
 ↓
R6  Knowledge & Context Engine
 ↓
R7  Skills 2.0 / Departments / Packs
 ↓
R8  Evaluation & Controlled Learning
 ↓
R9  Developer Platform
 ↓
R10 Personal Superhub & Communication
 ↓
R11 Business Packs
 ↓
R12 Teams / Multi-Agent Collaboration
 ↓
R13 Marketplace
 ↓
R14 Operational Excellence
 ↓
R15 Product Quality & Distribution
 ↓
R16 Team / Business Server
 ↓
R17 Cloud / Enterprise
 ↓
R18 Advanced Intelligence
```

### Parallelism allowed

After R5 passes, some work may proceed in parallel when code ownership is isolated:

- R6 and R9 protocol scaffolding can overlap.
- R7 manifest design can begin during late R6, but skill ranking should wait for retrieval/eval foundations.
- R14 observability improvements can be pulled forward whenever they support active debugging.
- R15 accessibility improvements are cross-cutting and should be applied continuously, not saved for the end.

### Parallelism not allowed

Do not prioritize these before the corresponding foundation is reliable:

- Public marketplace before R7/R8 package quality/security foundations.
- Multi-user before R2 project/tool authorization is mature.
- Autonomous multi-agent Teams before R4 durable jobs and R2 safety are proven.
- Distillation/fine-tuning before R8 eval datasets and production evidence exist.
- Cloud/enterprise deployment before local execution semantics stabilize.

---

# PART VIII — ROADMAP GOVERNANCE

## Monthly architecture review

Review:

1. Which roadmap tasks changed maturity?
2. Which P0/P1 defects threaten release guarantees?
3. Which legacy components were preserved vs replaced?
4. Which new external concepts deserve evaluation?
5. Did any integration introduce a second execution/session/memory/security model?
6. What does founder/user evidence say about priority?
7. What tasks should be removed or deferred rather than added?

## Quarterly product review

Evaluate:

- daily active founder/user workflows;
- task success rate;
- manual intervention rate;
- median and P95 latency;
- quality-adjusted cost per task class;
- provider/local model mix;
- tool/skill failure rates;
- security incidents/denials;
- successful backup/restore drills;
- pack adoption and usefulness;
- roadmap items that exist only because they sounded interesting.

Remove or defer capabilities that do not justify their operational complexity.

---

# FINAL DELIVERY PRINCIPLE

The roadmap exists to make one statement increasingly true:

> **Agent Engine is one trustworthy local-first AI operating environment where models, skills, tools, workflows, knowledge and automation are installed and governed once, can be used from every surface, and improve from verified outcomes without sacrificing user control.**

The next task is always the earliest unmet prerequisite for that statement—not the newest interesting AI feature.
