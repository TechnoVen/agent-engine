# Agent Engine — Milestone & Task Roadmap Tracker

> **Master Single Source of Truth**  
> Tracks implementation progress across all 10 milestones and 15 phases (Phase 0 through Phase 14).

---

## Milestone Summary

| Milestone | Phases | Scope | Status |
|---|---|---|---|
| **M0 — Foundations** | Phase 0 | Monorepo layout, API contract, storage repo, feature flags, CI/CD | 🟢 COMPLETED |
| **M1 — Hardened Core** | Phase 1 | Router, pipelines, memory, policy, cost tracker, session store | ⚪ PENDING |
| **M2 — Desktop Alpha** | Phases 2–3 | Tauri shell + Kimi-style chat interface | ⚪ PENDING |
| **M3 — Dashboard Beta** | Phase 4 | Control dashboard, approvals queue, live telemetry | ⚪ PENDING |
| **M4 — Agent Hub** | Phases 5–6 | Agent adapters + multi-tool skill management | ⚪ PENDING |
| **M5 — Orchestration** | Phases 7–8 | Mastra-style workflows + advanced RAG & memory scoring | ⚪ PENDING |
| **M6 — Observability** | Phases 9–10 | Audit event telemetry + architecture diagram generator | ⚪ PENDING |
| **M7 — Enterprise** | Phase 11 | Multi-user, RBAC, tenant isolation, audit log, SSO | ⚪ PENDING |
| **M8 — Ecosystem** | Phase 12 | Agent packaging, public registry, JS/Python SDKs, marketplace | ⚪ PENDING |
| **M9 — Cloud** | Phase 13 | Kubernetes SaaS, web UI, hybrid E2E sync | ⚪ PENDING |
| **M10 — Hardening** | Phase 14 | Compliance pack, sandbox execution, support tooling | ⚪ PENDING |

---

## Phase 0 — Foundations & Conflict Freeze (Milestone M0)

- [x] **Task 0.1 — Repository Restructure**
  - **User Story:** As P5, I want a clean repo layout so I can contribute modules independently.
  - **Deliverables:** Monorepo with `pnpm-workspace.yaml`, `uv` workspaces (`pyproject.toml`), `packages/shared-schema/` (OpenAPI + SSE JSON Schema), root `Makefile`, `README.md`.
  - **Acceptance Criteria:** `make bootstrap` sets up toolchains; `make verify` passes lint + test.
  - **Status:** ✅ DONE

- [x] **Task 0.2 — Local API Contract (Freeze)**
  - **User Story:** As P5, I want a stable API contract so my UI and sidecar can evolve independently.
  - **Deliverables:** `packages/shared-schema/openapi.yaml`, `packages/shared-schema/events.schema.json`, `services/python/server/api.py`.
  - **Acceptance Criteria:** Sidecar exposes all endpoints via FastAPI matching frozen schema.
  - **Dependencies:** 0.1
  - **Status:** ✅ DONE

- [x] **Task 0.3 — Repository Pattern for Storage**
  - **User Story:** As P4, I want the same code to run on SQLite locally and PostgreSQL in the cloud.
  - **Deliverables:** `core/storage/base.py`, `core/storage/sqlite.py`, `core/storage/postgres.py`, Alembic migrations.
  - **Acceptance Criteria:** Tests pass against both backends via `STORAGE_BACKEND=sqlite|postgres`.
  - **Dependencies:** 0.2
  - **Conflicts Resolved:** C3
  - **Status:** ✅ DONE

- [x] **Task 0.4 — Feature Flag System**
  - **User Story:** As P4, I want enterprise features gated so personal builds stay lightweight.
  - **Deliverables:** `core/config/flags.py`, `.env.example`.
  - **Acceptance Criteria:** Flags documented; disabled flags hide UI + API endpoints.
  - **Dependencies:** 0.2, 0.3
  - **Conflicts Resolved:** C7
  - **Status:** ✅ DONE

- [x] **Task 0.5 — CI/CD Baseline**
  - **User Story:** As P5, I want every PR verified automatically.
  - **Deliverables:** `.github/workflows/ci.yml`, `.github/workflows/release.yml`.
  - **Acceptance Criteria:** PRs run lint, tests, schema diff; releases produce signed artifacts.
  - **Dependencies:** 0.1
  - **Status:** ✅ DONE

---

## Phase 1 — Core Engine Hardening (Milestone M1)

- [ ] **Task 1.1 — Model Router Hardening** (Health checks, circuit breaker, fallback chain)
- [ ] **Task 1.2 — DSPy Pipeline Registry** (Modular agent pipeline registration)
- [ ] **Task 1.3 — Memory Upgrade (Observational Memory)** (Cross-session importance scoring)
- [ ] **Task 1.4 — Guardrail Policy Engine** (Central YAML rules, risk scoring, tool interception)
- [ ] **Task 1.5 — Cost Tracker** (Per-request, per-agent, per-model spend ledger)
- [ ] **Task 1.6 — Session Store Unification** (Cross-agent unified session model)
- [ ] **Task 1.7 — Semantic Cache** (`core/cache/semantic_cache.py` - Chroma-backed 0.95 similarity cache, 0 tokens)
- [ ] **Task 1.8 — Context Builder** (`core/context/builder.py` - ContextSpec budget enforcement, <8k target)
- [ ] **Task 1.9 — Model Eval Suite (Cost per Success)** (`core/eval/suite.py` - success-adjusted cost rankings)
- [ ] **Task 1.10 — Execution Router Integration** (`core/router/execution_router.py` - 90/9/1 step profiling and routing)

---

## Phase 2 — Cross-Platform Shell (Milestone M2)

- [ ] **Task 2.1 — Tauri Shell Skeleton**
- [ ] **Task 2.2 — Sidecar Bundling & Signing**
- [ ] **Task 2.3 — Secure Credential Storage**
- [ ] **Task 2.4 — Auto-Update Channel**

---

## Phase 3 — Kimi-Style Conversational GUI (Milestone M2)

- [ ] **Task 3.1 — Chat Shell**
- [ ] **Task 3.2 — Skill Selector & Slash Commands**
- [ ] **Task 3.3 — Inline Approval Cards**
- [ ] **Task 3.4 — Model & Agent Switcher**
- [ ] **Task 3.5 — Session Sidebar & Search**
- [ ] **Task 3.6 — Document Drop & RAG Ingestion**

---

## Phase 4 — Control Dashboard (Milestone M3)

- [ ] **Task 4.1 — Dashboard Shell**
- [ ] **Task 4.2 — Provider Setup Panel**
- [ ] **Task 4.3 — Agent Status Panel**
- [ ] **Task 4.4 — Approval Queue**
- [ ] **Task 4.5 — Cost Dashboard**
- [ ] **Task 4.6 — Policy Editor**
- [ ] **Task 4.7 — Hardware Telemetry Panel**

---

## Phase 5 — Agent Adapter Layer (Milestone M4)

- [ ] **Task 5.1 — Adapter Interface**
- [ ] **Task 5.2 — Claude Code Adapter**
- [ ] **Task 5.3 — Codex Adapter**
- [ ] **Task 5.4 — OpenClaw Adapter** (WhatsApp & Telegram personal messaging)
- [ ] **Task 5.5 — Goose Adapter (ACP)**
- [ ] **Task 5.6 — Hermes, Cursor, Windsurf Adapters (MCP fallback)**

---

## Phase 5B — Native Collaborative Rooms (Milestone M4)

- [ ] **Task 5B.1 — Room ↔ Project Mapping** (`core/rooms/mapper.py` - collaborative multi-agent overlay on projects)
- [ ] **Task 5B.2 — Room Roles & Governance** (`core/rooms/roles.py` - admin, member, viewer room permissions)
- [ ] **Task 5B.3 — Task Objects as Workflow Steps** (`core/rooms/tasks.py` - persistent task queue for humans and agents)

---

## Phase 5C — Native Team Collaboration Channels (No Switch) (Milestone M4)

- [ ] **Task 5C.1 — Slack Adapter** (`core/adapters/slack.py` - native Slack Socket Mode bridge)
- [ ] **Task 5C.2 — Microsoft Teams Adapter** (`core/adapters/teams.py` - native Bot Framework HTTP listener)
- [ ] **Task 5C.3 — Discord Adapter** (`core/adapters/discord.py` - native Discord Gateway WebSocket)
- [ ] **Task 5C.4 — Mattermost Adapter** (`core/adapters/mattermost.py` - native Mattermost WebSocket client)

---

## Phase 6 — Skill Management (Milestone M4)

- [ ] **Task 6.1 — Multi-Tool Skill Discovery**
- [ ] **Task 6.2 — Skill Editor**
- [ ] **Task 6.3 — Collections & Search**
- [ ] **Task 6.4 — Skill Registry Integration**
- [ ] **Task 6.5 — Remote Skill Discovery**

---

## Phase 7 — Workflow Engine (Milestone M5)

- [ ] **Task 7.1 — Workflow Schema & Runtime**
- [ ] **Task 7.2 — Visual Workflow Builder**
- [ ] **Task 7.3 — Human-in-the-Loop Gates**

---

## Phase 8 — Memory & RAG Deepening (Milestone M5)

- [ ] **Task 8.1 — Advanced RAG**
- [ ] **Task 8.2 — Memory Importance Scoring**
- [ ] **Task 8.3 — Context Window Manager**

---

## Phase 9 — Cost, Telemetry, and Observability (Milestone M6)

- [ ] **Task 9.1 — Observability Backend**
- [ ] **Task 9.2 — Prometheus/Grafana Export**
- [ ] **Task 9.3 — Distillation Pipeline** (`core/distillation/pipeline.py` - fine-tune/quantize specialists for >10k/mo tasks)
- [ ] **Task 9.4 — GPU Load Balancer** (`core/scheduler/load_balancer.py` - off-peak scheduling for background/eval work)
- [ ] **Task 9.5 — Cost Attribution Dashboard** (`apps/desktop/src/renderer/dashboard/CostAttribution.tsx` - 90/9/1 breakdown)

---

## Phase 10 — Architecture Visualization (Milestone M6)

- [ ] **Task 10.1 — Spec Generator**
- [ ] **Task 10.2 — Renderer Integration**
- [ ] **Task 10.3 — Roast Mode**
- [ ] **Task 10.4 — Diagram UI**

---

## Phase 11 — Multi-User & Multi-Tenant (Milestone M7)

- [ ] **Task 11.1 — Auth & RBAC**
- [ ] **Task 11.2 — Tenant Isolation**
- [ ] **Task 11.3 — Audit Log**
- [ ] **Task 11.4 — SSO & Directory Sync**

---

## Phase 12 — Registry, SDK, and Marketplace (Milestone M8)

- [ ] **Task 12.1 — Agent Packaging Format**
- [ ] **Task 12.2 — Public Registry**
- [ ] **Task 12.3 — SDKs (Python + TypeScript)**
- [ ] **Task 12.4 — Marketplace UI**
- [ ] **Task 12.5 — Licensing & Billing Hooks**

---

## Phase 13 — Cloud SaaS (Milestone M9)

- [ ] **Task 13.1 — Cloud Deployment**
- [ ] **Task 13.2 — Web UI**
- [ ] **Task 13.3 — Hybrid Sync**

---

## Phase 14 — Enterprise Hardening (Milestone M10)

- [ ] **Task 14.1 — Compliance Pack**
- [ ] **Task 14.2 — Sandboxed Tool Execution**
- [ ] **Task 14.3 — SLA & Support Tooling**

---

## Cross-Cutting User Stories (Cost Optimization)

- **US-017** As P2, I want repeated customer questions answered instantly without paying for a model call.
- **US-018** As P4, I want my monthly AI bill to grow slower than my usage.
- **US-019** As P5, I want to know the true cost-per-success of each model on my tasks.
- **US-020** As P4, I want background AI work to run at night so daytime users get full capacity.
- **US-021** As P4, I want my most repetitive tasks handled by a specialist model at 10× lower cost.
- **US-022** As P1, I want my local model to handle 90% of my daily tasks without cloud calls.
- **US-023** As P5, I want the router to automatically pick the cheapest model that works for each step.

---

## Definition of Done (Cost Optimization Discipline)

Every task and PR must satisfy:
- [ ] PR declares the 90/9/1 split in docstring (≤10% frontier).
- [ ] Every step profiled with `StepProfile` and routed via `ExecutionRouter`.
- [ ] Context budget respected (< 8,000 tokens target, 32,000 ceiling via `ContextSpec`).
- [ ] Semantic cache consulted before classification, extraction, or Q&A.
- [ ] Background tasks scheduled off-peak.
- [ ] Cost-per-success logged; no cost regression > 10% on golden eval set.

