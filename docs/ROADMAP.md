# Agent Engine — Milestone & Task Roadmap Tracker

> **Master Single Source of Truth**  
> Tracks implementation progress across all 10 milestones and 15 phases (Phase 0 through Phase 14).

---

## Milestone Summary

| Milestone | Phases | Scope | Status |
|---|---|---|---|
| **M0 — Foundations** | Phase 0 | Monorepo layout, API contract, storage repo, feature flags, CI/CD | 🟢 COMPLETED |
| **M1 — Hardened Core** | Phase 1 | Router, pipelines, memory, policy, cost tracker, session store | 🟢 COMPLETED |
| **M2 — Desktop Alpha** | Phases 2–3 | Tauri shell + Kimi-style conversational interface (universal ChatInput, mode pages, empty states) | ⚪ PENDING |

| **M3 — Dashboard Beta** | Phase 4 | Unified Tauri dashboard, projects, approval queue, telemetry, settings (Streamlit demoted to dev tool) | ⚪ PENDING |
| **M4 — Agent Hub** | Phases 5–6 | Agent adapters + multi-tool skill management | ⚪ PENDING |
| **M5 — Orchestration** | Phases 7–8 | Mastra-style workflows + Swarm + advanced RAG & memory scoring | ⚪ PENDING |
| **M6 — Observability** | Phases 9–10 | Audit event telemetry + architecture diagram generator | ⚪ PENDING |
| **M7 — Enterprise** | Phase 11 | Multi-user, RBAC, tenant isolation, audit log, SSO | ⚪ PENDING |
| **M8 — Ecosystem** | Phase 12 | Agent packaging, public registry, JS/Python SDKs, marketplace | ⚪ PENDING |
| **M9 — Cloud** | Phase 13 | Kubernetes SaaS, web UI, hybrid E2E sync | ⚪ PENDING |
| **M10 — Hardening** | Phase 14 | Compliance pack, sandbox execution, support tooling | ⚪ PENDING |
| **M11 — Polish & Accessibility** | Phase 15 | Light theme, high-contrast, reduced motion, full keyboard shortcut system | ⚪ PENDING |

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

- [x] **Task 1.1 — Model Router Hardening** (Health checks, circuit breaker, fallback chain)
  - **User Story:** As P1, I want the system to keep working if my cloud provider goes down.
  - **Deliverables:** `core/router/circuit_breaker.py`, `core/router/health.py`, `core/router/config.yaml`, `core/router/config.py`, updated `core/router/model_router.py`.
  - **Acceptance Criteria:** Outage triggers fast fallback (<2s); circuit breaker fast-fails; logs show traversal chain.
  - **Dependencies:** 0.3
  - **Status:** ✅ DONE
- [x] **Task 1.2 — DSPy Pipeline Registry** (Modular agent pipeline registration)
  - **User Story:** As P5, I want to register new agent pipelines without touching core code.
  - **Deliverables:** `core/pipelines/registry.py` with `@register_pipeline`, `core/pipelines/standard.py` (6 standard pipelines), API endpoints `GET /v1/pipelines`, `GET /v1/pipelines/{name}`, `POST /v1/pipelines/{name}/run`.
  - **Acceptance Criteria:** New pipelines register via decorator; discoverable via API `/v1/pipelines`.
  - **Dependencies:** 1.1
  - **Status:** ✅ DONE
- [x] **Task 1.3 — Memory Upgrade (Observational Memory)** (Cross-session importance scoring)
  - **User Story:** As P3, I want my agent to remember my preferences across sessions.
  - **Deliverables:** `core/memory/observational.py` (session summarization, importance scoring, preference extractor), `core/memory/vector.py`, `core/memory/__init__.py`, API endpoints `POST /v1/memory/observe` and `GET /v1/memory/observations`.
  - **Acceptance Criteria:** Memory retrieves relevant facts from sessions 7+ days old; scores decay gracefully according to Stanford Generative Agents formula.
  - **Dependencies:** 0.3
  - **Status:** ✅ DONE
- [x] **Task 1.4 — Guardrail Policy Engine** (Central YAML rules, risk scoring, tool interception)
  - **User Story:** As P4, I want one place to define what agents may and may not do.
  - **Deliverables:** `core/safety/policy.py` (rule matcher: glob, regex, semantic), `core/safety/risk.py` (dynamic risk scorer), `core/safety/audit.py` (persistent storage audit logs), `policies/default.yaml`, API endpoints `POST /v1/safety/evaluate`, `GET /v1/safety/policies`, `GET /v1/safety/audit`.
  - **Acceptance Criteria:** Policy blocks `kubectl delete namespace production`; suggests `kubectl rollout restart`.
  - **Dependencies:** 0.3
  - **Conflicts Resolved:** C6 (auto-apply vs staged patches).
  - **Status:** ✅ DONE
- [x] **Task 1.5 — Cost Tracker** (Per-request, per-agent, per-model spend ledger)
  - **User Story:** As P2, I want to see how much my agents cost me per month.
  - **Deliverables:** `core/telemetry/cost.py` (`CostTracker`, `ModelPricing`, `BudgetConfig`, `BudgetAlert`), storage repo breakdown queries (`get_cost_breakdown`), FastAPI endpoints `GET /v1/telemetry/cost`, `POST /v1/telemetry/cost/record`, `GET/POST /v1/telemetry/budget`, Streamlit Tab 5 ("💰 Cost Tracker & Budgets"), and OpenAPI spec.
  - **Acceptance Criteria:** Dashboard shows cost breakdown; budget alerts fire (warning at 80%, critical at 100%+); all unit/integration tests pass.
  - **Dependencies:** 0.3
  - **Status:** ✅ DONE
- [x] **Task 1.6 — Session Store Unification** (Cross-agent unified session model)
  - **User Story:** As P1/P5, I want a single cross-agent session store so that multi-agent interactions, tool invocations, tokens, costs, and branch points are tracked consistently across providers.
  - **Deliverables:** `core/session/model.py` (`ToolCall`, `AgentParticipant`, `UnifiedMessage`, `UnifiedSession`), `core/session/converters.py` (OpenAI, Anthropic, DSPy, Markdown, JSONL), `core/session/store.py` (`UnifiedSessionStore`, CRUD, branching/forking, keyword search, import/export), SQLite/Postgres repository enhancements with automatic column migrations, Alembic migration `002_unified_session_store.py`, 10 FastAPI endpoints under `/v1/sessions`, OpenAPI specification, Streamlit Tab 6 ("💬 Unified Session Store"), and test suite `tests/test_session_store.py`.
  - **Acceptance Criteria:** Cross-agent sessions persist participants, tool calls, and per-message token/cost metrics; session branching creates isolated child sessions preserving ancestor lineage; bi-directional format converters round-trip accurately; 100% backwards compatibility maintained; all 127 unit and integration tests pass.
  - **Dependencies:** 0.3, 1.5
  - **Status:** ✅ DONE
- [x] **Task 1.7 — Semantic Cache** (Chroma-backed 0.95 similarity cache, 0 tokens)
  - **User Story:** As P2/P4, I want repeated queries, classifications, and extractions to return instantly from a semantic cache so that I consume 0 tokens and pay $0.00 for previously answered questions.
  - **Deliverables:** `core/cache/semantic_cache.py` (`SemanticCache`, `CacheEntry`, `CacheLookupResult`, `CacheStats`, `@cached_step`), `core/cache/__init__.py`, dual-layer index (L1 exact-match hash + L2 Chroma cosine similarity `>= 0.95`), per-task TTL policies (7d classification, 48h extraction, 24h QA, 12h code), 4 FastAPI endpoints under `/v1/cache` (`lookup`, `store`, `stats`, `clear`), OpenAPI specification, and test suite `tests/test_semantic_cache.py`.
  - **Acceptance Criteria:** Exact queries hit L1 in <2ms; paraphrased queries match L2 at cosine similarity ≥ 0.95; dissimilar queries reject (<0.95); expired entries evict cleanly; 0 tokens consumed on cache hits; all 139 repository tests pass.
  - **Dependencies:** 0.3, 1.5
  - **Status:** ✅ DONE
- [x] **Task 1.8 — Context Builder** (`core/context/builder.py` - ContextSpec budget enforcement, <8k target)
  - **User Story:** As an Agent Developer, I want declarative context budgeting, field whitelisting, and priority truncation so LLM calls stay under 8k tokens with 0 token waste.
  - **Deliverables:** `core/context/builder.py`, `core/context/__init__.py`, `POST /v1/context/build`, `tests/test_context_builder.py`.
  - **Acceptance Criteria:** `BuiltContext` satisfies dict interface; whitelisting drops sensitive fields; priority truncation enforces <8k target; RAG gating conditional; 14/14 tests pass.
  - **Status:** ✅ DONE
- [x] **Task 1.9 — Model Eval Suite (Cost per Success)** (`core/eval/suite.py` - success-adjusted cost rankings)
  - **User Story:** As an Agent Engineer, I want to evaluate models by cost-per-success rather than cost-per-token (Law 2), ranking models accurately on golden eval tasks and detecting cost regressions > 10%.
  - **Deliverables:** `core/eval/suite.py`, `core/eval/__init__.py`, golden eval sets, benchmark storage recording, REST API (`POST /v1/eval/run`, `GET /v1/eval/rankings`, `GET /v1/eval/benchmarks`), `tests/test_model_eval_suite.py`.
  - **Acceptance Criteria:** Cost-per-success calculated as Total Cost / Successes; ranking recommends cheapest qualified model meeting quality threshold; regressions > 10% detected; API endpoints in OpenAPI 3.1; all tests pass.
  - **Status:** ✅ DONE

- [x] **Task 1.10 — Execution Router Integration** (`core/router/execution_router.py` - 90/9/1 step profiling and routing)
  - **User Story:** As an Agent Engineer, I want every step classified across 6 execution tiers (CODE, CACHE, SMALL_MODEL, MID_MODEL, FRONTIER_MODEL, HUMAN) adhering to Law 1 (The 90/9/1 Rule) so that expensive frontier models never exceed 10% of pipeline steps, with full integration into SemanticCache, ContextBuilder, and ModelEvalSuite.
  - **Deliverables:** `core/router/execution_router.py`, `core/router/__init__.py`, `@profiled_step` decorator, `audit_pipeline()` ratio checker, REST API (`POST /v1/router/route`, `POST /v1/router/audit`, `GET /v1/router/tiers`), OpenAPI 3.1 specification, `tests/test_execution_router_integration.py`.
  - **Acceptance Criteria:** 6-tier routing resolution; exact and semantic cache hits routed to CACHE tier ($0 token cost); ContextBuilder budget enforced; ModelEvalSuite dynamically resolves optimal tier models; `audit_pipeline()` flags workflows where frontier steps > 10%; REST endpoints integrated and tested; 14/14 router tests pass; 177/177 total tests pass.
  - **Status:** ✅ DONE


---

## Phase 2 — Cross-Platform Shell (Milestone M2)

- [x] **Task 2.1 — Tauri Shell Skeleton**
  - **User Story:** As an Agent Engine user, I want a fast, native desktop application (Tauri v2 + React 18 + TypeScript + Vite) with a unified 3-zone shell and automated sidecar process supervision, so I can collaborate with local-first agents directly from my desktop.
  - **Deliverables:** `apps/desktop/` initialized with Tauri v2, Vite 5, React 18, Tailwind CSS design tokens (`--bg-base: #0a0a0a`), `src-tauri/` Rust backend (`main.rs`, `lib.rs`, `sidecar.rs`, `tauri.conf.json`), 3-zone sidebar (`Sidebar.tsx`), `TopBar.tsx`, `Home.tsx`, `Layout.tsx`, `api/client.ts`, `Makefile` desktop targets, and `tests/test_desktop_shell.py`.
  - **Acceptance Criteria:** Frontend builds cleanly with zero TypeScript errors via `pnpm --filter @agent-engine/desktop build`; Rust backend passes `cargo check` with WebKitGTK/GTK3; 3-zone sidebar with `Ctrl+K` shortcut; sidecar healthcheck monitoring; 7/7 desktop shell tests pass; all 184 repo tests pass.
  - **Status:** ✅ DONE
- [x] **Task 2.2 — Sidecar Bundling & Signing**
  - **User Story:** As an operator and security-conscious user, I want the Python sidecar packaged into standard target-triple executables (`externalBin`) and cryptographically signed (Ed25519) with SHA-256 integrity verification (ADR-008), so that the Tauri desktop shell supervises, spawns, and validates trusted sidecar processes with zero-trust local security.
  - **Deliverables:** `scripts/bundle_sidecar.py` (cross-platform packaging, portable executable launcher + PyInstaller support, SHA-256 manifest generation), `scripts/sign_artifacts.py` (Ed25519 keypair generation, digital signing, and tamper verification), `services/python/server/api.py` CLI parser hardening (`--port`, `--host`, `--token`, `--version`, `--verify`), `services/python/server/__main__.py` entrypoint, `apps/desktop/src-tauri/tauri.conf.json` (`externalBin`), capabilities (`shell:allow-execute`), Rust supervisor lifecycle management in `sidecar.rs` & `lib.rs` (start, stop, health polling, SHA-256 pre-execution validation, graceful exit handler), `Makefile` targets (`desktop-bundle-sidecar`, `desktop-sign-sidecar`, `desktop-verify-sidecar`), CI workflow verification job in `.github/workflows/ci.yml`, and test suite `tests/test_sidecar_bundling.py`.
  - **Acceptance Criteria:** Sidecar bundles to `apps/desktop/src-tauri/binaries/agent-engine-sidecar-${TARGET_TRIPLE}` with `0o755` permissions; SHA-256 checksums and `manifest.signed.json` generated; Ed25519 digital signatures verified; bit-flip tampering detected and rejected; Tauri Rust supervisor checks integrity before spawn; graceful exit terminates child process; 10/10 bundling tests pass; all 194 repo tests pass.
  - **Status:** ✅ DONE
- [x] **Task 2.3 — Secure Credential Storage**
  - **User Story:** As a developer and privacy-conscious operator, I want my API keys and sensitive tokens stored securely in the native OS Keychain (or AES-256-GCM encrypted vault fallback in headless environments) with automatic secret masking across logs, APIs, and UI responses, so that secrets are never stored in plaintext `.env` files or exposed in runtime logs.
  - **Deliverables:** `core/security/credentials.py` (`CredentialBackend`, `KeyringBackend` via OS Keychain, `EncryptedVaultBackend` via AES-256-GCM with PBKDF2-SHA256 100k rounds key derivation, `CredentialManager` with hybrid fallback, secret masking `mask_secret`, and provider test connectivity `test_provider_key`), `core/security/__init__.py`, `core/router/health.py` (`_check_api_key` integration), `core/models.py` (`get_model_provider` credential resolution), `services/python/server/api.py` (5 FastAPI endpoints: `GET /v1/credentials`, `POST /v1/credentials`, `GET /v1/credentials/{service}/{key}`, `DELETE /v1/credentials/{service}/{key}`, `POST /v1/credentials/test`), `packages/shared-schema/openapi.yaml`, Tauri Rust helpers in `apps/desktop/src-tauri/src/credentials.rs` & `lib.rs`, React client in `apps/desktop/src/renderer/api/client.ts` & `types/index.ts`, and comprehensive test suite `tests/test_credential_storage.py`.
  - **Acceptance Criteria:** Zero plaintext secrets in storage; OS Keychain used when available with seamless AES-256-GCM encrypted vault fallback for headless CI/CD; vault files enforce `0o600` permissions and tamper rejection (GCM auth tag verification); secret masking (`sk-...xxxx`) enforced across APIs, logs, and list endpoints; `reveal=true` strictly gated on individual item GET; ModelRouter and HealthProber resolve keys from secure storage; all 10 credential storage tests pass; 100% of monorepo tests pass (204/204).
  - **Status:** ✅ DONE
- [x] **Task 2.4 — Auto-Update Channel**
  - **User Story:** As an end user or developer, I want to subscribe to release distribution channels (`stable`, `beta`, `nightly`) and receive cryptographically verified, zero-trust auto-updates (ADR-008) via Tauri v2 update manifests and sidecar endpoints, so that the desktop shell and bundled backend can be upgraded securely without manual installations.
  - **Deliverables:** `core/updater/manager.py` (`SemVer` parser & comparator compliant with SemVer 2.0.0, `UpdateChannel` enum, `UpdateInfo`, `UpdateManager` with persistent channel subscription, feed resolution, and Ed25519 signature verification), `core/updater/__init__.py`, `scripts/generate_update_manifest.py` (CLI for generating and Ed25519-signing multi-channel manifests matching Tauri v2 schema), `services/python/server/api.py` (3 FastAPI endpoints: `GET /v1/updater/status`, `POST /v1/updater/channel`, `POST /v1/updater/check`), `packages/shared-schema/openapi.yaml`, Tauri Rust helpers (`apps/desktop/src-tauri/src/updater.rs`, `lib.rs`), React client (`apps/desktop/src/renderer/api/client.ts`, `types/index.ts`), mock feed server `infra/update-server/serve_feed.py`, Makefile targets (`desktop-update-manifest`, `desktop-update-server`), `.github/workflows/ci.yml` validation job, and unit/integration test suite `tests/test_auto_updater.py`.
  - **Acceptance Criteria:** SemVer 2.0.0 comparison accurately reflects pre-release precedence; Ed25519 digital signatures ensure manifest integrity; tampered manifests/payloads are rejected with zero tolerance (ADR-008); channel switching persists across restarts; Tauri Rust shell and React frontend can inspect status, switch channels, and trigger updates; 16/16 updater tests pass; 100% of monorepo tests pass (220/220).
  - **Status:** ✅ DONE

---

## Phase 3 — Kimi-Style Conversational GUI (Milestone M2)

> **Architectural Standard:** Implements the Kimi-inspired unified shell with mode-based navigation (`apps/desktop/src/renderer/`). Universal `ChatInput.tsx` reusable component across all screens, 3-zone sidebar (Global Actions, Mode Navigation, Context), rich empty states with featured inspiration cases for all 8 modes, inline approvals, and pre-execution cost estimates. See full specification in [`docs/GUI.md`](file:///home/nadir/agent_engine/docs/GUI.md).

- [x] **Task 3.1 — Chat Shell & Home Mode**
  - **User Story:** As a user, I want a clean, responsive chat canvas with universal input and inspiration chips so I can immediately collaborate with my agent.
  - **Deliverables:** `apps/desktop/src/renderer/shell/Layout.tsx`, `Sidebar.tsx`, `TopBar.tsx`, `screens/Home.tsx` (Route `/`), universal `ChatInput.tsx` component, 60fps streaming token renderer (`Message.tsx`), mode-switching state, global `Ctrl+K` autofocus handler, and test suite `tests/test_desktop_shell.py`.
  - **Acceptance Criteria:** `Ctrl+K` focuses input from any screen; greeting and featured case cards appear on empty state; streaming tokens render at 60fps; 11/11 desktop shell tests pass; 100% of monorepo tests pass (224/224).
  - **Status:** ✅ DONE
- [x] **Task 3.2 — Skill Selector & Slash Commands**
  - **User Story:** As a power user, I want to invoke skills and plugins via `/` slash commands directly in the universal input.
  - **Deliverables:** `SlashCommandPopup.tsx` in `ChatInput.tsx`, fuzzy-searchable skill menu, structured interactive parameter chips, plugin icons row with quick toggles, sidecar `/v1/skills` client integration (`api/client.ts`), and unit/integration tests in `tests/test_desktop_shell.py`.
  - **Acceptance Criteria:** Typing `/` shows fuzzy-searchable skill menu; selecting a skill inserts structured parameter chips; keyboard navigation (`↑`/`↓`/`Enter`/`Esc`) works seamlessly; 14/14 desktop shell tests pass; 100% of monorepo tests pass (227/227).
  - **Status:** ✅ DONE
- [x] **Task 3.3 — Inline Approval Cards**
  - **User Story:** As an operator, I want dangerous or high-impact agent tool calls to prompt for explicit inline approval before execution.
  - **Deliverables:** `apps/desktop/src/renderer/components/ApprovalCard.tsx`, tool call interceptor in `Home.tsx`, diff preview (code, command, SQL, JSON), risk score badges, Approve / Reject / Edit action buttons, audit ledger logging via `POST /v1/safety/approval`, and unit/integration tests in `tests/test_desktop_shell.py`.
  - **Acceptance Criteria:** High-risk actions render inline approval card; execution pauses until user decides; decision executes in <500ms and logs to tamper-evident audit ledger; 17/17 desktop shell tests pass; 100% of monorepo tests pass.
  - **Status:** ✅ DONE
- [ ] **Task 3.4 — Model & Agent Switcher**
  - **User Story:** As a user, I want to toggle between instant, balanced, and deep reasoning models (or switch primary agents) without leaving the chat.
  - **Deliverables:** Model tier selector in `ChatInput.tsx` (`Instant High`, `K3 Swarm High`, `K3 High`), agent persona picker, cost per 1k token display.
  - **Acceptance Criteria:** Changing model updates active pipeline immediately; estimated cost per run preview updates dynamically.
- [ ] **Task 3.5 — Session Sidebar & Search**
  - **User Story:** As a user, I want a 3-zone sidebar to manage global actions, modes, projects, and searchable chat history.
  - **Deliverables:** `Sidebar.tsx` with Zone A (Logo, collapse, New Chat `Ctrl+K`), Zone B (Modes list), Zone C (Projects, Recent Chats, User profile footer), real-time search filter over `/v1/sessions/search`.
  - **Acceptance Criteria:** Sidebar collapses to icon strip; search finds keywords across titles and message contents; active session highlights cleanly.
- [ ] **Task 3.6 — Document Drop & RAG Ingestion**
  - **User Story:** As a researcher/writer, I want to drag-and-drop PDFs, CSVs, and code files directly onto the chat canvas for immediate grounding.
  - **Deliverables:** Canvas drag-and-drop target, upload progress bar, multi-file chip attachments in `ChatInput.tsx`, sidecar `/v1/memory/observe` integration.
  - **Acceptance Criteria:** Dragging files highlights canvas; files attach and index into session memory; preview snippets viewable before send.
- [ ] **Task 3.7 — My Agent Screen (Identity, Memory, Growth)**
  - **User Story:** As a user, I want to view my agent's personalized growth, interaction streak, observational memories, and cost savings.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Agent.tsx` (Route `/agent`), GitHub-style 365-day contribution heatmap, Closeness / Growth / Memory / Cost tabs, observational memory search/edit table, self-growth toggle, subtle animated memory network dots.
  - **Acceptance Criteria:** Heatmap loads in <200ms; memories searchable and editable inline; self-growth toggle persists per-user; stats update real-time.
- [ ] **Task 3.8 — Scheduled Tasks Screen**
  - **User Story:** As an operator, I want to configure cron-style recurring background agent tasks with off-peak execution and channel notifications.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Tasks.tsx` (Route `/tasks`), plain-English cron builder, task table with status, last run, next run, cost-per-run estimate, create modal ("Manually", "Via chat", "From template").
  - **Acceptance Criteria:** Plain-English cron preview; tasks default to off-peak scheduling; failures notify channel bridge; cost metrics displayed per task.
- [ ] **Task 3.9 — Universal Chat Input Component (`ChatInput.tsx`)**
  - **User Story:** As a developer, I want a single, bulletproof, highly reusable chat input component across all 14 screens.
  - **Deliverables:** `apps/desktop/src/renderer/components/ChatInput.tsx`, dynamic textarea, `+` file attachment button, mode chip, model dropdown, send arrow, project selector row, plugin toggle icons, token cost preview, `Ctrl+K` focus handler.
  - **Acceptance Criteria:** 60fps responsiveness on 10,000+ char input; handles paste image and drag-drop; token cost preview accurate to ±5%; zero duplication across screens.
- [ ] **Task 3.10 — Mode Landing Page Template (`ModePage.tsx`)**
  - **User Story:** As a user exploring different capabilities, I want rich empty states with curated example cases rather than blank screens.
  - **Deliverables:** `apps/desktop/src/renderer/components/ModePage.tsx`, reusable header with tagline, embedded `ChatInput`, category filter tabs, `FeaturedGrid.tsx` for example cards.
  - **Acceptance Criteria:** Shared across all 8 modes (`/modes/{mode}`); switching modes preserves chat history; loads mode-specific skills automatically.
- [ ] **Task 3.11 — Featured Cases Content Curation**
  - **User Story:** As a new user, I want inspirational, one-click prompts for Code, Deep Research, Docs, Sheets, Slides, Websites, Design, and Diagrams.
  - **Deliverables:** Curated case templates in `configs/cases/` and `apps/desktop/src/renderer/screens/Modes/` covering all 8 modes with realistic prompts, expected tool chains, and sample outputs.
  - **Acceptance Criteria:** Clicking any featured card populates `ChatInput` with one-click runnable prompt; teaches features friction-free.

---

## Phase 4 — Control Dashboard (Milestone M3)

> **Architectural Decision — Streamline to ONE:** Ship the Tauri shell as the **only user-facing dashboard**. Demote Streamlit to a hidden developer tool (`tools/dev_dashboard.py`, `make dev-dashboard`) never shipped to end users. All control operations (projects, approvals, telemetry, cost, settings) live natively in the desktop shell.

- [ ] **Task 4.1 — Projects & Workspaces (Organiser)**
  - **User Story:** As a user, I want dedicated workspaces that group threads, persistent instructions, attached files, active agent adapters, and scoped policies.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Projects.tsx` (Route `/projects`), `ProjectDetail.tsx` with thread list and right inspector (Instructions, Files, Agents, Scoped Policy, Scoped Cost), Centered Create Project modal with icon carousel.
  - **Acceptance Criteria:** Project scopes conversation context and file attachments; instructions injected into prompt prefix; thread list loads instantly.
- [ ] **Task 4.2 — Provider Setup Panel**
  - **User Story:** As an operator, I want to configure LLM providers and test API connectivity with keychain-backed credential storage.
  - **Deliverables:** Provider configuration cards in `Settings.tsx` (OpenAI, Anthropic, Google Gemini, Ollama, vLLM, Custom OpenAI-compatible), keychain integration, 1-click connection test button.
  - **Acceptance Criteria:** Credentials securely stored in OS keychain; latency and status badge rendered in real-time.
- [ ] **Task 4.3 — Agent Status Panel**
  - **User Story:** As an operator, I want to see which agents and adapters are active, idle, or encountering errors.
  - **Deliverables:** Agent status grid, health indicators, active sessions count, model bindings, and circuit breaker status.
  - **Acceptance Criteria:** Real-time polling via `/v1/pipelines` and `/v1/adapters`; shows degraded or tripped circuit breakers.
- [ ] **Task 4.4 — Approval Queue**
  - **User Story:** As a security auditor, I want a centralized queue of pending high-risk tool calls across all sessions.
  - **Deliverables:** Centralized queue view in `screens/Policies.tsx` (`/policies`), risk score badges, diff viewers, batch approve/reject actions.
  - **Acceptance Criteria:** Pending calls resolve in <500ms upon approval; rejections return explicit reason to waiting agent.
- [ ] **Task 4.5 — Cost Dashboard (React Native in Desktop Shell)**
  - **User Story:** As P2, I want to view monthly spend, 90/9/1 tier splits, and budget ceilings directly in my desktop app.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Cost.tsx` (Route `/cost`), Recharts donut (90/9/1 CODE/CACHE/SMALL/MID/FRONTIER), cost-per-task bar chart, cache hit rate line chart, distillation candidate list (>10k calls/mo) with 1-click distill trigger, budget ceiling inputs.
  - **Acceptance Criteria:** Numbers match `/v1/telemetry/cost`; alerts trigger warning at 80% and block/alert at 100%; CSV/JSON export works.
- [ ] **Task 4.6 — Policy Editor & Audit Log**
  - **User Story:** As P4, I want to edit YAML guardrail policies with a test playground and browse immutable audit logs.
  - **Deliverables:** Monaco YAML editor in `screens/Policies.tsx`, rule dry-run playground, paginated audit log table with filter by risk level and tool name.
  - **Acceptance Criteria:** Validates YAML syntax before save; hot-reloads policies without restarting sidecar; audit logs exportable as CSV/JSON.
- [ ] **Task 4.7 — Hardware Telemetry Panel**
  - **User Story:** As a local model user, I want to see VRAM, RAM, CPU, and tokens/sec for local runtimes (Ollama/llama.cpp).
  - **Deliverables:** Local telemetry widget in `Settings.tsx` and status bar, VRAM gauge, generation speed gauge, GPU model detection.
  - **Acceptance Criteria:** Updates every 2 seconds when local models run; warns when VRAM reaches 95%.
- [ ] **Task 4.8 — Settings Screen**
  - **User Story:** As a user, I want a single settings page to control Providers, Models, Local Runtime, Adapters, Channels, Storage, Security, Appearance, and Diagnostics.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Settings.tsx` (Route `/settings`), tabbed configuration layout, diagnostics bundle export (`.zip`).
  - **Acceptance Criteria:** Settings persist to local encrypted config; diagnostics export includes redacted logs, schema versions, and system info.
- [ ] **Task 4.9 — Cost Dashboard Migration to React (Replaces Streamlit Tab 5)**
  - **User Story:** As an enterprise user, I want the cost dashboard built directly into the desktop app rather than opening a browser tab.
  - **Deliverables:** React component `apps/desktop/src/renderer/screens/Cost.tsx` connected to `/v1/telemetry/cost`, matching Streamlit Tab 5 functionality.
  - **Acceptance Criteria:** Replaces Streamlit Tab 5 with full feature parity, responsive Recharts charts, and budget ceiling management.
- [ ] **Task 4.10 — Streamlit Demotion to Developer Tool**
  - **User Story:** As a maintainer, I want Streamlit reserved purely for internal development and CI benchmarks, cleanly removed from user packaging.
  - **Deliverables:** Move `server/dashboard.py` to `tools/dev_dashboard.py`, add developer warning banner ("Developer tool — not for end users"), update `Makefile` target `make dev-dashboard`, remove port 8501 references from user-facing docs, update `start_studio.sh`.
  - **Acceptance Criteria:** Production builds contain zero Streamlit code; `make dev-dashboard` launches internal tool for debugging; user guides reference only desktop app.

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
- [ ] **Task 7.4 — Swarm Screen (Multi-Agent Parallel Execution)**
  - **User Story:** As a team lead, I want to dispatch a prompt to a parallel swarm of specialized agents and see their live progress strips and aggregated output.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Swarm.tsx` (Route `/swarm`), `Swarm High` model selector, live multi-agent progress strips, aggregated output view with agent attribution, cost estimator before execution.
  - **Acceptance Criteria:** Parallel execution respects cost router; partial agent failures handled gracefully; total cost calculated across all agents.
- [ ] **Task 7.5 — Workflow Builder Screen (React Flow Canvas)**
  - **User Story:** As an automation engineer, I want an interactive visual canvas to drag, drop, connect, and inspect pipeline nodes, approval gates, and conditions.
  - **Deliverables:** `apps/desktop/src/renderer/screens/Workflows.tsx` (Route `/workflows`), React Flow canvas, node palette (Pipelines, Skills, Agents, Gates, Conditions, Merge), inspector panel, round-trip YAML exporter/importer, dry-run simulation mode.
  - **Acceptance Criteria:** Round-trip YAML ↔ canvas is 100% lossless; dry-run visualizes execution path; human gates render as interactive pause nodes.

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

## Phase 15 — Light Theme & Accessibility Polish (Milestone M11)

- [ ] **Task 15.1 — Light Theme**
  - **User Story:** As a user in bright environments, I want an accessible, carefully tuned light mode theme that adheres to our design tokens.
  - **Deliverables:** Light theme CSS token palette in `tokens.css`, theme toggle in `Settings.tsx` and header, auto-detect OS theme preference.
  - **Acceptance Criteria:** Contrast ratios meet WCAG 2.1 AA (≥ 4.5:1 for normal text); seamless transition without visual artifacts.
- [ ] **Task 15.2 — High-Contrast Mode**
  - **User Story:** As a user with visual impairments, I want a high-contrast mode with prominent borders and saturated action indicators.
  - **Deliverables:** High-contrast CSS token overrides, clear focus outlines (≥ 2px solid), enhanced text contrast (≥ 7:1).
  - **Acceptance Criteria:** Meets WCAG 2.1 AAA contrast requirements; verified with automated a11y testing.
- [ ] **Task 15.3 — Reduced Motion Mode**
  - **User Story:** As a user sensitive to motion, I want all animations and transitions disabled or minimized.
  - **Deliverables:** CSS `@media (prefers-reduced-motion: reduce)` rules across all transitions, panels, and streaming indicators.
  - **Acceptance Criteria:** Eliminates all non-essential motion, bouncy springs, and sliding drawer transitions when enabled.
- [ ] **Task 15.4 — Full Keyboard Shortcut System**
  - **User Story:** As a power user, I want comprehensive keyboard shortcuts for every primary action so I never have to leave the keyboard.
  - **Deliverables:** Global shortcut manager, shortcut cheat sheet modal (`?` or `Ctrl+/`), bindings for `Ctrl+K` (New Chat / Search), `Ctrl+N` (New Session), `Ctrl+1..9` (Mode Switch), `Esc` (Close / Unfocus), `Ctrl+Enter` (Send).
  - **Acceptance Criteria:** All shortcuts configurable; no collisions with OS standard shortcuts; cheat sheet modal accessible anywhere.

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

---

## Definition of Done (GUI Task Standards)

Every GUI task and PR in `apps/desktop/src/renderer/` must satisfy:
- [ ] Screen implemented at the correct route matching [`docs/GUI.md`](file:///home/nadir/agent_engine/docs/GUI.md).
- [ ] Strict adherence to design system tokens (`--bg-base`, `--border-subtle`, `--accent`, etc.).
- [ ] Reuses `ChatInput.tsx`, `Message.tsx`, `Sidebar.tsx`, `ApprovalCard.tsx` (zero component duplication).
- [ ] Loading, empty, error, and populated states all implemented.
- [ ] Keyboard navigation fully functional (`Ctrl+K`, `Ctrl+N`, `Ctrl+/`, `Esc`).
- [ ] Screen reader labels and ARIA semantics present on all icons and controls.
- [ ] Playwright E2E test passes.
- [ ] Cost estimate shown before any model call is dispatched.
- [ ] Approval card shown inline for dangerous or high-risk actions.
- [ ] Screenshot added to [`docs/GUI.md`](file:///home/nadir/agent_engine/docs/GUI.md) with 3-line description.
- [ ] No console errors or warnings.
- [ ] Cross-platform desktop build passes (Win / macOS / Linux).

