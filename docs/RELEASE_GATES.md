# Agent Engine — Canonical Release Gates & Behavioral Verification

> **Status:** Canonical Architecture Specification  
> **Audience:** Developers, Maintainers, QA, CTO  
> **Related Documents:** [`ROADMAP.md`](ROADMAP.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`EXECUTION_MODEL.md`](EXECUTION_MODEL.md), [`STATUS.md`](STATUS.md)  
> **Task Reference:** `R0.2`, `R0.7`

---

## 1. Principles of Behavioral Verification

1. **Behavior Over Numbers:** Fixed numerical test counts (e.g. `240 -> 247`) are explicitly abolished. A milestone or task is verified only when its required behavioral contracts, state transitions, security bounds, and failure modes pass named test suites.
2. **Failure-Path Testing is Mandatory:** Every suite must test not only the happy path, but also provider timeouts, rate limits, network disconnects, invalid arguments, tamper attempts, and unexpected cancellations.
3. **No Fabricated Assertions:** Tests must assert against real outputs, truthful error structures, and verifiable state transitions. Mock providers are permitted only when explicitly acting as realistic test spies or fault injectors.
4. **Clean Packaging Verification:** A release gate cannot be satisfied by passing tests in a dirty development checkout. It requires successful clean installation, binary startup, and execution of the core user journeys from packaged artifacts.

---

## 2. Named Behavioral Test Suites

The test suite structure is organized by architectural responsibility and execution tier:

| Suite Identifier | Target Scope | Command / Runner | Blocking Gate |
|---|---|---|---|
| `suite:unit:core` | Core domain models, state machines, serializers | `pytest tests/unit/` | All PRs / Gates |
| `suite:behavior:execution` | Universal Execution Pipeline, state transitions, context assembly | `pytest tests/behavior/execution/` | Gate 0.5+ |
| `suite:behavior:routing` | Model router, provider fallback, quality-adjusted cost | `pytest tests/behavior/routing/` | Gate 0.5+ |
| `suite:security:approval` | Cryptographic argument hashing, replay rejection, vault crypto | `pytest tests/security/` | Gate 0.5+ |
| `suite:jobs:durable` | Background job queues, retry backoff, worker crash recovery | `pytest tests/jobs/` | Gate 0.5+ |
| `suite:workflow:runtime` | DAG Kahn's ordering, branching, gate pausing, subworkflows | `pytest tests/workflows/` | Gate 0.5+ |
| `suite:integration:storage` | SQLite WAL concurrency, Alembic upgrade/downgrade | `pytest tests/integration/storage/` | Gate 0.5+ |
| `suite:integration:channels` | Native WebSocket/webhook channel adapters (Slack, Teams, Discord, Mattermost) | `pytest tests/integration/adapters/` | Gate 0.8+ |
| `suite:desktop:build` | Tauri v2 Rust compilation, TypeScript build, Vite bundle | `pnpm --filter @agent-engine/desktop build` | All PRs / Gates |
| `suite:desktop:a11y` | Desktop shell keyboard navigation, ARIA semantics, high-contrast | `pnpm --filter @agent-engine/desktop test:a11y` | Gate 0.5+ |
| `suite:release:clean-install` | Packaged binary installation and smoke test on clean machine | `scripts/ci/verify-clean-install.sh` | Release Releases |

---

## 3. Definition of Done (DoD)

Before any feature, task, or release can be marked `S3 (Behavior Verified)` or higher in `docs/STATUS.md`, it must satisfy the 9-dimensional Definition of Done:

### 3.1 Architecture & Invariants
- Execution flows through `ExecutionCoordinator`. No bypasses to raw LLM APIs or detached tool runners.
- Visual workflow layout metadata (`layout: {position: {x, y}}`) is completely decoupled from execution semantics.
- Adheres to single-user local-first architecture with optional feature-flagged multi-user/cloud sync.

### 3.2 Behavioral Verification
- Happy path, edge cases, and failure modes are explicitly verified.
- Error codes and messages are structured and deterministic.
- Downstream cancellation reliably aborts in-flight upstream processes.

### 3.3 Security & Authorization Boundary
- Consequential tools (shell commands, file modifications, git operations) fail-closed.
- Approval requests use SHA-256 canonical argument hashing; modified arguments immediately invalidate authorization.
- Zero plaintext API keys or credentials on disk or in logs. Credentials stored in OS Keyring or encrypted vault (`data/credentials.vault`).

### 3.4 Observability & Telemetry
- Every step emits events to the append-only `execution_events` ledger.
- Token counts, latencies, and costs reflect actual provider usage or are explicitly flagged `is_estimated: true`.
- Zero fabricated telemetry.

### 3.5 Cost & Budget Controls
- Per-request and per-session cost ceilings enforced before execution begins.
- Routing optimizes for quality-adjusted cost per successful task (replacing rigid 90/9/1 with pragmatic adaptive routing).

### 3.6 Testing
- All relevant named suites pass with 100% success.
- New capabilities introduce automated regression tests.
- Zero flaky or time-dependent race condition tests.

### 3.7 Persistence & Durability
- Database schema changes have corresponding reversible Alembic migrations.
- Interrupted or crashed jobs resume gracefully from SQLite state without duplicate side-effects.

### 3.8 User Experience & Accessibility
- Desktop UI provides distinct visual states: Loading, Empty, Progress/Streaming, Success, Error, and Paused/Approval.
- Full keyboard navigability (Tab, Enter, Space, Escape, Arrows).
- Screen-reader accessible labels on interactive elements and canvas nodes.

### 3.9 Documentation & ADRs
- Any architectural change or divergence is recorded in an ADR in `docs/ADR/`.
- User documentation and API contracts updated synchronously.

---

## 4. Release Verification Gates

### Gate 0.5 — Agent Engine “Nadir Edition” (Founder MVP)
*The system must pass all 16 acceptance criteria on Nadir's primary machine from a clean installation:*

1. [ ] **Clean App Launch:** Application installs and launches cleanly without manual developer repair or terminal workarounds.
2. [ ] **Local Model Execution:** At least one managed local model (e.g. Ollama Qwen / Llama) completes a real prompt end-to-end.
3. [ ] **Cloud Model Execution:** At least one cloud provider (e.g. Gemini / Anthropic) completes a real prompt end-to-end.
4. [ ] **Dynamic Model Switching:** Changing the model in the desktop UI dropdown dynamically redirects subsequent executions to the selected provider.
5. [ ] **Context Bounding:** Multi-turn conversation proves bounded history reaches inference without unbounded token runaway.
6. [ ] **Project Context Isolation:** Knowledge and files in Project A do not leak into Project B retrieval or context.
7. [ ] **Real File Ingestion & RAG:** Real file ingestion (Markdown, PDF, code) indexes into SQLite/ChromaDB and answers queries with traceable citations.
8. [ ] **Writing Workflow Artifact:** Writing Pack workflow runs through outline, draft, and review, producing a persistent Markdown artifact.
9. [ ] **Isolated Developer Workflow:** Developer Pack workflow creates an isolated Git worktree, applies a change, runs tests, and pauses for review before merging.
10. [ ] **Protected Tool Approval:** Shell execution and destructive file operations pause for user approval; tampering with command arguments causes rejection.
11. [ ] **Real Cancellation:** Pressing "Stop" halts upstream streaming and cancels in-flight child processes; status records `CANCELLED`.
12. [ ] **Truthful Telemetry:** Execution records show actual token counts and provider-reported costs; missing data is explicitly flagged `is_estimated: true`.
13. [ ] **Crash & Restart Recovery:** Closing or restarting the application preserves session history, queued background jobs, and paused approvals.
14. [ ] **Durable Scheduled Automation:** A scheduled project review job executes exactly once at its scheduled interval and survives application restarts.
15. [ ] **Graceful Provider Outage:** When an API key is missing or an upstream provider is down, the system surfaces a clear diagnostic error without crashing or faking success.
16. [ ] **Accessibility Baseline:** All primary flows (chat, approval, settings, workflow canvas) support keyboard navigation and standard screen-reader semantics.

---

### Gate 0.6 — Personal Alpha
*Focus: Knowledge Engine, Skills 2.0, evaluation and controlled learning.*
- [ ] Automated chunking, hybrid BM25 + dense vector search across multi-format personal documents.
- [ ] Skills 2.0 dynamic discovery, validation, and sandbox isolation.
- [ ] DSPy compilation and metric-driven prompt optimization running locally.
- [ ] Automated daily backup and export of local SQLite database and credential vault.

---

### Gate 0.7 — Developer Alpha
*Focus: ACP/MCP and structured software-engineering workflows.*
- [ ] Full bi-directional Model Context Protocol (MCP) client and server support.
- [ ] Agent Communication Protocol (ACP) peer-to-peer execution with cryptographic mutual TLS.
- [ ] Multi-file AST refactoring with test-driven patch verification.
- [ ] Native IDE extension support (VS Code / Neovim) connecting to Agent Engine execution daemon.

---

### Gate 1.0 — Local-First Stable
*Focus: Production stability, cross-platform packages, full accessibility.*
- [ ] Native signed installers for macOS (Universal DMG / PKG), Linux (.deb, .rpm, AppImage), and Windows (MSI).
- [ ] WCAG 2.1 AA accessibility compliance across the entire Tauri desktop shell.
- [ ] Sub-50ms local UI response time for all state transitions.
- [ ] Zero critical or high-severity CVEs in dependency supply chain.
