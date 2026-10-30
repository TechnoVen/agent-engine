# Agent Engine — project assessment and delivery recommendations

**Reviewed:** 15 September 2026. **Baseline:** commit `e60ea54`, branch `chore/canonical-workspace-path`, plus the existing uncommitted settings/diagnostics work.

## 1. Executive assessment

Agent Engine aims to be a local-first desktop control center for creating, running, supervising, and eventually coordinating AI agents. Its distinguishing goals are reusable skills, interchangeable providers and agent tools, persistent project memory, explicit human approvals, and measurable control over inference costs.

There is substantial working infrastructure: DSPy agents and pipelines, storage repositories, session persistence, vector and observational memory, routing components, policy evaluation, credential storage, a React/Tauri desktop shell, and dashboard APIs. Recent commits also repaired several concrete defects from the previous review.

**The project is still a development prototype, with an incomplete end-to-end execution path.** The main issue is the gap between implemented components and enforced product behavior. Some tasks marked complete are demonstrators or partial integrations. Chat still fabricates success when no provider is available; model selection and history do not reach inference; streaming happens after inference; approval tokens remain optional on patch execution; scheduled execution and distillation do not actually dispatch work.

The best next milestone is a trustworthy single-user local release: one real conversation and tool-execution path with persistence, cancellation, approvals, measured usage, and reliable packaging. Adding more adapters and enterprise screens before that milestone would increase the number of incomplete paths to maintain.

## 2. Scope and evidence

- Confirmed the canonical project through `~/code/_workspace/WORKSPACE.toml`.
- Reviewed README, roadmap, engineering memory, prior review, architecture documents, recent Git history, Python core/API/storage/safety, frontend client and representative screens, Rust supervision, CI/release configuration, and representative tests.
- Preserved existing changes to `core/config/__init__.py`, `services/python/server/api.py`, and the untracked `core/config/settings.py` and `core/diagnostics.py`.
- Tested a temporary copy of tracked source plus those untracked modules, without copying the repository's `.env`, databases, or private runtime state. Reused the installed virtual environment; this was not a clean dependency installation.
- Findings below are source-confirmed unless explicitly described as a runtime observation. A passing source-inspection test is not treated as proof of a working user interaction.
- This review does not certify live provider inference, native GUI behavior, production PostgreSQL, Windows/macOS installers, accessibility compliance, dependency vulnerabilities, or adversarial sandbox isolation.

## 3. What the plan is trying to achieve

The plan has three expanding product layers:

1. **Personal agent studio:** local desktop UI, provider configuration, chat, reusable templates, coding assistance, projects, memory, approvals, and costs.
2. **Agent and workflow hub:** external agent adapters, skill discovery, collaborative rooms, messaging integrations, durable workflows, and parallel agent execution.
3. **Commercial platform:** observability, multi-user authorization, tenant isolation, public registry, SDKs, marketplace, cloud hosting, synchronization, and enterprise operations.

The architecture supports this direction in principle: React talks to FastAPI; Tauri manages the local service; Python core modules contain agent functionality; repository abstractions separate storage backends. CLI, MCP, and Streamlit provide additional entry points.

### Roadmap interpretation

| Roadmap area | Intended result | Current assessment |
|---|---|---|
| Phases 0–1: foundations/core | Shared contract, storage, flags, CI, routing, memory, policy, cost, sessions | Substantial implemented components; integration and verification gaps remain |
| Phases 2–3: desktop alpha | Native shell, sidecar, credentials, updates, chat and mode UI | Shell and frontend compile; release trust and real execution are incomplete |
| Phase 4: dashboard beta | Projects, provider setup, real execution, approvals, costs, policy editor, telemetry, settings | Tasks 4.0–4.7 marked done, but several acceptance criteria are not met; 4.8 and 4.9 open |
| Phases 5/5B/5C–6 | Agent adapters, collaborative rooms, Slack/Teams/Discord/Mattermost, skill management | Primarily planned |
| Phases 7–8 | Workflow runtime, visual builder, parallel agents, advanced RAG | Primarily planned; listing a sample workflow is not an execution engine |
| Phases 9–10 | Observability, distillation, scheduling, architecture visualization | Primarily planned; current distillation button is a stub |
| Phases 11–14 | Auth/RBAC, tenant isolation, SDKs/registry, SaaS, enterprise hardening | Future product scope, not current deployment readiness |
| Phase 15 | Themes, accessibility, reduced motion, keyboard controls | Planned; basic accessibility should also be part of current acceptance |

### Problems in the plan itself

- The introduction says 10 milestones and phases 0–14, but the table extends through M11/Phase 15 and includes additional Phase 5 branches.
- M2 remains marked pending even though its detailed phase tasks are checked complete.
- Task 4.5's title says it merges 4.9, while Task 4.9 now describes Streamlit demotion and launcher cleanup. Give tasks stable identities.
- README still advertises phases 0–3 and 240 tests while subsequent implementation has landed.
- The cost rule is ambiguous: a 90/9/1 goal appears alongside a permitted 10% frontier ceiling. Define whether this measures calls, steps, tokens, or spend, and distinguish a target from an enforced ceiling.
- Cost optimization is described as universally mandatory, but the primary execution paths do not use those controls.
- Cloud, enterprise, omnichannel, adapter, and SDK claims in overview documentation exceed current implementation.
- No single local-release acceptance gate clearly separates working product features from future scope.

**Recommended planning change:** track each task as implemented, integrated, behavior-tested, and release-verified. A checkbox should require evidence for its stated acceptance criteria, rather than file existence or a fixed test count.

## 4. What has actually been done

### Useful foundations

- Dynamic DSPy signatures, declarative agent configuration, templates, tool registration, and a pipeline registry.
- Provider configuration, health checks, circuit breakers, and fallback machinery.
- SQLite WAL storage, a SQLAlchemy/PostgreSQL implementation, migrations, unified sessions, message conversion, branching, search, and import/export.
- Chroma-backed knowledge memory and semantic cache, observational memory, context budgeting, model evaluation, and execution-tier classification.
- YAML policy/risk evaluation, persisted audit records, pending-operation objects with expiration and single-use token checks.
- Credential backends, provider connectivity tests, sidecar artifact/signing helpers, update manifest handling.
- React/Tauri navigation, mode pages, projects, settings, policies, cost dashboard, hardware telemetry, and an HTTP/SSE client.

These are real assets. Their existence should be retained and built upon; the immediate need is to connect them consistently.

### Recent progress verified in source

| Commit/task | Delivered improvement | Remaining qualification |
|---|---|---|
| `8e773ee` / 4.0 | Restricted CORS, token-check helper, health/ingestion aliases, response parsing fixes, shorter native lock scopes, stale-patch comparison, improved Makefile checks | Authentication remains conditional and incomplete; CI still has gaps; patch writes are not atomic |
| `6841717` / 4.1 | Projects and detail screens, local project persistence | Backend project scoping and prompt injection are not implemented |
| `c6d2841` / 4.2 | Provider setup cards and credential/connectivity integration | Chat selection is not tied to the chosen provider/model |
| `bcbf1cd` / 4.3 | Frontend uses chat endpoint; user/assistant messages persist; provider call branch exists | Stub success, ignored history/model, post-completion streaming, incomplete cancellation |
| `2c664fa` / 4.4 | Pending registry, argument-bound tokens, approvals UI, fail-closed evaluation errors | Execution can bypass approval; stage decisions are not suspended |
| `1d31872` / 4.5 | Cost dashboard, ledger aggregation, budget controls, exports | Chat costs are not recorded there; tier fallback and distillation are misleading |
| `a44bb77` / 4.6 | Policy YAML editing/hot reload, dry-run, audit filtering/pagination/export | Does not establish immutable storage or mandatory audit/execution coupling |
| `e60ea54` / 4.7 | Hardware tracker and telemetry UI | Chat throughput uses invented elapsed time |
| Existing working tree / 4.8 | Encrypted settings data model and diagnostics builder started | No settings/diagnostics routes wired in the reviewed API; new imports unused; validation/redaction incomplete |

The prior native startup mutex finding is corrected in source: child/path locks are released before health polling. Ordinary stale edits are now compared against the original before patch application. These improvements should not be reported as if nothing changed since 14 September.

## 5. Bugs and important gaps

Priority definitions: **P1** blocks trusting the affected behavior or distributing it with the advertised guarantee; **P2** is important reliability/integration work; **P3** is maintainability or documentation work. Priority is specific to this project, not a formal vulnerability score.

### R01 — P1: Chat can claim execution without a provider

**Evidence:** `services/python/server/api.py:996–1165`, especially the fallback near line 1089.

With no configured/available LM, the endpoint returns `Agent Engine executed your instruction: ...`. Any prompt containing `ping` returns `Pong`; this also matches ordinary words such as `shipping`. Any prompt containing `2+2` returns `4`, regardless of the rest of the requested task. Test-trigger strings fabricate provider failures.

**Impact:** A user can receive a success-like response for work that never happened. Tests exercise these branches and therefore do not demonstrate real inference.

**Fix:** Remove test-specific behavior from production execution. Return a clear provider-unavailable error. If deterministic tools are intended, route narrowly defined operations explicitly and label their actual execution source.

**Acceptance:** A provider stub receives arbitrary prompts unchanged; no-provider requests fail honestly; `Explain shipping constraints` reaches the provider.

### R02 — P1: Model choice, history, projects, and memory do not reach chat inference

**Evidence:** `ChatRequest` at `api.py:198`; provider invocation near `api.py:1066`; `Home.tsx:486`; `Projects.tsx:146`; `ProjectDetail.tsx:386`.

Chat calls the already-configured LM with only `req.prompt`. It does not resolve `req.model` to a provider/model configuration or supply persisted messages. A session is loaded for existence checking, not conversation context. The chat schema has no project identifier. Project instructions, file attachments, scoped policies, and budgets are presented in the UI, but are not connected to this request path. Project data is stored in browser localStorage, with sample projects and threads.

**Impact:** Follow-up questions lack prior context; changing models can change labels without changing inference; project-specific assurances are misleading. RAG storage alone does not ground chat.

**Fix:** Introduce a backend project model and request-scoped execution context. Resolve provider/model, load authorized history, inject instructions, retrieve project-scoped knowledge, then apply a bounded context builder. Pass explicit project/session identities throughout.

**Acceptance:** A two-turn test proves recall; two model selections invoke different configured targets; project A instructions/files do not appear in project B; reload preserves the same backend records.

### R03 — P1: Streaming and cancellation do not control provider execution

**Evidence:** `api.py:1066–1156`; `apps/desktop/src/renderer/api/client.ts:128–204`.

The synchronous LM call completes before the SSE response is returned. The full answer is persisted before chunks are emitted, then split into whitespace chunks with artificial sleeps. Client abort stops response consumption, but there is no cancellation propagation to the model call. The client also calls `onDone` for a done event and again at EOF; EOF after an error can still invoke completion.

**Impact:** Long calls block the event loop; cancel cannot stop inference or its cost; a cancelled visible response can already exist in full in storage. Completion/error callbacks have ambiguous semantics.

**Fix:** Use provider-native asynchronous streaming or a bounded worker with cancellation support. Persist an explicit execution state and partial result. Emit exactly one terminal outcome: completed, failed, or cancelled.

**Acceptance:** A delayed streaming stub emits its first chunk before completion; cancelling signals the provider; concurrent health requests remain responsive; error/EOF never reports success.

### R04 — P1: The mandatory approval boundary is bypassable

**Evidence:** `api.py:1551–1580`; `core/pipelines/registry.py:76–107`; `core/safety/pending.py`.

Patch application consumes an approval token only if one is supplied. Omitting it proceeds to `apply_staged_patch`, without requiring a risk decision. Registry execution blocks `block`/`deny`, but a `stage` decision proceeds to instantiate and run the pipeline. Token verification is mostly exposed as a separate endpoint rather than an unavoidable tool-execution boundary.

**Impact:** A valid IPC client can execute without the required human approval. Working token replay tests do not establish mandatory enforcement.

**Fix:** Make one executor own policy evaluation, pause/resume, argument binding, token consumption, and actual invocation. Treat `stage` as suspended, and distinguish non-overridable denial from approvable work. Bind patch approval to immutable content/path/version, not only a numeric patch ID.

**Acceptance:** Every actual tool path refuses missing, expired, replayed, or mismatched approval; no `stage` decision invokes a tool; an approved operation executes once.

### R05 — P1: IPC authentication is still optional and inconsistently applied

**Evidence:** `api.py:69–86`, router creation at line 127 and inclusion near 2993; `sidecar.rs:251–257`.

The helper explicitly returns success if `AGENT_ENGINE_IPC_TOKEN` is unset. Native startup forwards an existing token but does not generate one. Only selected endpoints call the helper. Chat, pipeline/skill execution, session changes, budget changes, and flag overrides have no blanket authentication dependency. Credential reveal is checked only under the same optional-token design.

**Impact:** The normal no-token configuration remains accessible to any caller able to reach the service. Restricting CORS improves browser behavior but does not authenticate local processes.

**Fix:** Generate a per-launch secret, deliver it through trusted native IPC, and apply a default authentication dependency to privileged APIs. Keep a minimal unprivileged liveness route. Avoid plaintext credential exposure to the renderer where unnecessary.

**Acceptance:** Missing/wrong token is denied on every privileged route; the desktop gets its token automatically and remains usable.

### R06 — P1: Cost and throughput figures are not reliable execution accounting

**Evidence:** `api.py:1091–1130`, `1695–1839`; `core/telemetry/cost.py`; calls to `ExecutionRouter` near `api.py:2774`.

Chat estimates tokens by word/whitespace splitting and charges fixed rates regardless of model. It stores costs in message metadata but does not record the call through the cost ledger used by the dashboard. Throughput uses `completion_tokens * 0.016` as elapsed time instead of measuring execution. Empty tier data produces an apparent 90/9/1 split. Tier classification is inferred from model-name substrings rather than recorded execution tiers. Main chat/skill/pipeline paths do not consistently use the cost router or a budget admission check.

**Impact:** Displayed spend, model choice, budget alerts, and speed cannot be relied upon to describe actual execution. Budgets can be exceeded without an execution block.

**Fix:** Record provider usage, actual model/provider/tier, elapsed time, project/session/execution IDs, and measured versus estimated status in one ledger. Reserve budget before dispatch and reconcile afterward. Show no-data states as no data.

**Acceptance:** One controlled completion produces exactly one matching ledger entry; a local call is not priced as an arbitrary cloud model; an exhausted hard budget blocks before dispatch; throughput reflects measured duration.

### R07 — P1: Scheduled runs, workflows, and distillation return success without dispatch

**Evidence:** `api.py:1275–1279`, `1509–1518`, `1652–1691`, `1828–1839`; `core/storage/sqlite.py:1203`.

Workflow execution returns an ID and `queued` without creating a queue job. Scheduled “run now” updates the existing status and returns a display timestamp without executing its prompt. Distillation uses hardcoded candidates and changes an in-memory status to `distilling`; no training pipeline is launched. Empty scheduled-task storage is seeded with demonstration entries.

**Fix:** Return explicit unimplemented/unavailable results until a durable job runtime exists, and isolate demo data behind an explicit demo mode. Then implement job identity, state transitions, retries, time zones, restart recovery, and cancellation.

**Acceptance:** Every accepted run has a durable job record and observable worker execution; restart preserves state; no demo activity appears as real history.

### R08 — P1 before release: Artifact verification does not establish publisher trust

**Evidence:** `apps/desktop/src-tauri/src/sidecar.rs:165–225`; `core/updater/manager.py:437–444`; `.github/workflows/release.yml`; `scripts/bundle_sidecar.py`.

Native sidecar verification compares a hash from adjacent metadata but does not verify the signature in the signed manifest. Replacing both binary and metadata can satisfy that check. Update manifests are verified only when a signature field is present. Development launchers depend on a Python environment/check-out; the release workflow builds Python artifacts on Ubuntu rather than verified native installers for all advertised platforms.

**Fix:** Pin a trusted public key and require signatures in production; fail closed on missing signatures. Separate development launcher output from release binaries and fail release packaging if freezing fails. Test installation on clean supported systems.

**Acceptance:** Modified binary plus modified checksum metadata is rejected; unsigned releases are rejected; installers run without the source checkout or preinstalled Python environment.

### R09 — P1 for untrusted execution: The Streamlit sandbox is in-process execution

**Evidence:** `server/dashboard.py:1305–1341`; `core/engine.py:87`; `start_studio.sh`.

The dashboard executes submitted/generated Python with `exec` inside the host process. Its available builtins include filesystem access. Restricted globals and AST repair are not process/filesystem/network isolation. The calculator restricts characters, but expensive arithmetic can still consume resources.

**Fix:** Run untrusted code in a separate restricted worker with time, memory, output, filesystem, and network limits. Demote Streamlit to an explicitly internal developer tool as already planned in 4.9. Bound calculator syntax and operation sizes.

**Acceptance:** Worker timeout/termination leaves the main app responsive; unauthorized filesystem/network access is denied; generated code cannot access host credentials.

### R10 — P2: Patch consistency is improved but incomplete

**Evidence:** `core/storage/sqlite.py:280–319`; `core/storage/postgres.py:289`.

The new original-content comparison protects ordinary intervening edits. However, writes still use direct truncating file output before the database commit. There is no atomic replacement/recovery journal, canonical workspace restriction, symlink protection, or exclusion of concurrent filesystem edits between comparison and write. A missing target skips the existing-file comparison.

**Fix:** Define expected create/update/delete state, validate canonical paths, reject unexpected target changes, write atomically, and retain a recovery record for filesystem/database failure.

**Acceptance:** Conflicting edits, deletion, path escape, and interrupted application preserve or recover user data.

### R11 — P2: Launcher shutdown cleanup is unreachable

**Evidence:** `start_studio.sh:50–75`.

The script starts child processes, then `exec`s Streamlit before defining cleanup or installing its signal trap. The cleanup code never runs after successful replacement.

**Fix:** Install traps before starting children, supervise the foreground process without replacing the supervisor, and stop only children started by this launcher.

**Acceptance:** Closing the launcher stops its watcher/newly started runtimes while leaving previously running inference services untouched.

### R12 — P2: Verification still gives stronger confidence than its coverage supports

**Evidence:** `tests/test_desktop_shell.py:156`, `:877–1083`; `apps/desktop/package.json`; `.github/workflows/ci.yml`; `Makefile`.

- Desktop test/lint scripts print success instead of executing tests/lint.
- Many GUI tests inspect source strings. The “real execution” test uses the exact hardcoded math and failure-trigger branches in production.
- Python tests expect generated frontend output, but the Python CI job does not build/download it. This failure was reproduced in the isolated checkout.
- Workspace CI reads package metadata without installing/building the frontend; no native check is present there.
- Contract tests largely assert path/method presence rather than complete payload and client behavior.
- PostgreSQL tests do not establish behavior against a production PostgreSQL service.
- Bootstrap now attempts `uv sync --frozen`, but falls back to an editable installation on failure; that weakens lockfile reproducibility.
- Current working-tree lint and formatting fail; see verification record.

**Fix:** Add behavior tests using controlled provider/tool doubles, frontend interaction tests, client/server contracts, native lifecycle tests, isolated storage fixtures, and correctly ordered build artifacts. Fail locked installation honestly. Test a real PostgreSQL service before claiming backend parity.

### R13 — P2: Settings/diagnostics work is unfinished and has privacy gaps

**Evidence:** uncommitted `core/config/settings.py`, `core/diagnostics.py`, API imports at lines 27–28.

The API imports settings/diagnostics but does not expose their routes. Dataclasses do not validate acceptable ranges/enumerations for budgets, limits, and security settings, and settings are not integrated into runtime behavior. Diagnostics redaction misses a short credential-bearing `postgres_url` because the field name is not classified as sensitive and the string is under its length heuristic. System diagnostics include host name and full executable/prefix paths. Schema versions and table names are hardcoded rather than inspected; the claimed migration version is 1 despite a second migration file.

**Fix:** Treat this as work in progress. Add validated schemas and explicit runtime application semantics. Redact URL userinfo and structured secret fields, test nested/list/string cases, and offer a preview of exported host/path information. Derive schema metadata from actual application/storage state.

**Acceptance:** Settings survive restart and actually change the intended subsystem; synthetic secrets never appear in exported bundles; diagnostics report the actual schema version.

### R14 — P2: Credential vault fallback is machine-bound, not protected by a secret by default

**Evidence:** `core/security/credentials.py:138–170`.

Without an explicit vault key, key derivation uses machine/user identifiers such as MAC address, hostname, machine ID, and username. These are not secret key material. A party with the vault and those identifiers can reconstruct the seed. This concerns the fallback vault, not OS keychain security. Machine changes can also affect recoverability.

**Fix:** Use a randomly generated key protected by the OS credential store or an explicit passphrase with a supported recovery procedure. Document backup/restore and machine migration behavior accurately.

### R15 — P2: Operational state needs stronger boundaries

**Evidence:** API singleton initialization near `api.py:126`; unbounded SSE queues near `api.py:1168`; `core/__init__.py:9`; storage session operations; `core/safety/audit.py`.

- API import creates runtime services and persistent resources, complicating startup, testing, and failure recovery.
- Several async handlers execute blocking provider/storage/network work directly.
- SSE subscriber queues and the pending-operation registry have no retention/size bounds; completed/expired operations remain stored.
- A global monkey patch disables a private DSPy configuration restriction, increasing coupling and concurrency risk.
- Tenant IDs are data fields, not authenticated authorization; do not deploy this as an isolated multi-tenant service yet.
- Audit records are useful local persistence, but do not establish tamper-evident immutable logging. Logging failures are swallowed with `-1`, so successful execution is not necessarily backed by a durable audit record.

**Fix:** Explicit application lifecycle, request-scoped model context, bounded workers/queues, retention policies, tested shutdown, authenticated scope enforcement, and an explicit audit-failure policy. Add tamper evidence only when that guarantee is required, and avoid calling ordinary local records immutable.

## 6. Enhancements worth adding, in order

### A. Finish the trustworthy local product

1. A shared execution service used by chat, skills, pipelines, MCP, and the watcher.
2. Explicit execution lifecycle with durable IDs and completed/failed/cancelled states.
3. Real provider selection, history, project instructions, and scoped retrieval.
4. Mandatory tool policy/approval enforcement.
5. Usage ledger, budget admission, truthful errors, and no-data states.
6. Provider setup flow that proves a real small completion works, not just a connectivity endpoint.
7. Clear distinction between chat answers, generated artifacts, queued work, and applied changes; show actual output locations and diffs.

### B. Reliability and usability

- Background job runtime with retry policy, idempotency, restart recovery, and time-zone-aware schedules.
- Backup and restore verification, schema migration/rollback policy, export/import checks, and retention controls.
- Accessible labels, visible focus, keyboard-only primary flows, reduced-motion support, and actionable error/empty/loading states.
- Lazy-load large screens; the current production JS chunk is approximately 520 kB before compression and triggers Vite's size warning.
- Consolidate API schemas and generate/check client types. Split the roughly 3,000-line API module into domain routers plus services after behavior is covered.
- Record request/execution IDs in structured logs, capture provider latency and failures, and expose queue health.

### C. Extend the platform after the foundation is proven

- Implement one external agent adapter end to end before expanding to all named tools.
- Add durable workflows before a sophisticated visual workflow editor.
- Add collaborative rooms/channels once project authorization and task state are well defined.
- Publish SDKs only after implementation, package-content checks, and consumer smoke tests; current package scaffolding should remain labeled as future work.
- Introduce cloud/enterprise features with real authentication, tenant-scoped storage access, PostgreSQL integration tests, migration tests, and operational ownership.

## 7. Recommended next delivery plan

| Sequence | Deliverable | Completion gate |
|---|---|---|
| 1 | Correct claims and remove implicit simulation | Unsupported actions fail explicitly; demo content is labeled; roadmap tasks reopened where necessary |
| 2 | Close authentication/approval bypasses | All privileged routes authenticated; every protected tool invocation requires valid authorization |
| 3 | Complete chat execution | Selected provider receives bounded history/project context; true streaming/cancel; no fabricated success |
| 4 | Connect measured costs and budgets | Exactly-once ledger writes; real usage/timing; budget rejection before execution |
| 5 | Strengthen persistence and process lifecycle | Atomic/recoverable patches; durable jobs; clean shutdown; bounded queues |
| 6 | Repair acceptance evidence | Behavioral frontend/API/native tests and correctly ordered CI build/test jobs |
| 7 | Finish settings and release packaging | Validated runtime settings, redacted diagnostics, signed standalone artifacts, clean-machine smoke tests |
| 8 | Resume adapters/workflows roadmap | One complete adapter and one durable workflow, then expand |

Do not infer a trustworthy percentage-complete estimate from checked tasks. Feature counts, integration maturity, and release readiness are different measurements.

## 8. Verification record

| Check | Observed result |
|---|---|
| `.venv/bin/ruff check . --output-format concise` | **Failed:** four unused imports, all in the existing settings/diagnostics work or its API integration |
| `.venv/bin/ruff format --check .` | **Failed:** six files require formatting; 101 already formatted |
| `pnpm --filter @agent-engine/desktop build` | **Passed:** TypeScript + Vite; 1,621 modules; approximately 520 kB JS chunk, with size warning |
| `cargo check --locked --offline` | **Passed** in `apps/desktop/src-tauri` |
| Isolated Python suite | **253 passed, 1 failed, 3 warnings in 52.34s** |
| Failing test | `test_built_distribution_bundle`: generated `apps/desktop/dist/index.html` missing from source-only temporary checkout |
| Focused rerun after copying verified frontend build | **1 passed in 0.03s** |

Additional controlled probes ran against the temporary copy with a fake provider and fake patch executor. They made no live inference calls and applied no real patches:

| Probe | Observed result |
|---|---|
| No provider, `Explain photosynthesis` | Returned `Agent Engine executed your instruction: Explain photosynthesis` |
| Configured stub, `Explain shipping constraints` | Provider called zero times because the substring shortcut matched |
| Two-turn session with different requested models | Second LM invocation received only `('What code did I provide?',)` and no keyword configuration/history |
| Direct patch handler call with no approval token | Fake executor reached and handler returned success |
| Redact `postgres_url` containing synthetic `fakepass` | Credential-bearing URL remained unchanged |

These probes validate handler/control-flow behavior, not a browser exploit or live provider integration. The probe process also reported a dependency disk-cache initialization failure and fell back to an in-memory cache; it completed successfully.

Thus all **254 collected cases passed across the full run plus the focused rerun**. A second complete suite run was not performed. This does not negate the behavioral gaps: several tests assert the stub behavior itself.

The suite reused the installed Python 3.14 environment. Its warnings concern FastAPI/Starlette testing dependencies and Chroma's deprecated coroutine-function check. This does not establish compatibility for every advertised Python version or the CI matrix.

The first sandboxed suite attempt stalled and was stopped. The completed suite ran with approved escalation in `/tmp/agent-engine-review-20260915-o6_pd8ag`. The initial frontend build was blocked by package-manager registry verification in the sandbox; the authorized retry completed. No source fixes, commits, workspace restructuring, or user-service launches were performed for this review. Frontend verification regenerated ignored build output.

## 9. Documentation maintenance

Update README, `MEMORY.md`, and the roadmap together after remediation. Mark old architecture snapshots as historical; keep one current architecture/status summary. Align API/README/package versions, supported Python versions, task numbering, current acceptance evidence, and current-versus-planned features. Confirm the intended license and include its text before publishing with an MIT badge.

This report supplements the 14 September review rather than replacing its historical record. Source fixes since that review are credited above; unresolved guarantees are restated against the current implementation.
