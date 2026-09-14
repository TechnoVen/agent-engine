# Agent Engine — detailed project review

Review date: 14 September 2026 (Europe/Berlin). Reviewed commit: `2a3ba86`, branch `chore/canonical-workspace-path`.

## Executive assessment

Agent Engine is a substantial local-first agent platform prototype with useful, implemented backend components and a polished desktop interface. It is not yet a reliable end-to-end agent studio: the main conversation interface simulates execution, several client/server contracts disagree, and critical controls are disconnected from the operations they are intended to protect.

The strongest next investment is completing and testing one real execution path—prompt, provider call, tool approval, result, session persistence, and measured cost—before expanding the dashboard or adding more integrations.

The most urgent findings are unauthenticated access to credential and mutation endpoints, a native startup deadlock, simulated success in the main UI, and patch application that can overwrite newer user edits. Successful compilation and numerous tests do not establish operational readiness for these paths.

## Scope and method

- Used the workspace registry to confirm the canonical repository at `~/code/agent_engine`.
- Inspected Git state, README, roadmap, engineering memory, build manifests, CI/release workflows, Python API and core modules, storage implementations, desktop client/components, native supervisor, packaging, and representative tests.
- Initial working tree was clean. No implementation changes were made for this review.
- Inventory: 211 tracked files; 86 Python files; 27 TypeScript/TSX files; 6 Rust files. Static inspection found 243 test functions; this is not a test execution count and excludes any expansion from parametrization.
- Ran local lint/format checks, frontend compilation, and Rust checking. Python tests were attempted in a temporary copy of tracked files, without copying `.env`, local databases, or installed project artifacts. The existing Python environment was reused.
- Used a temporary file and in-memory SQLite database to reproduce stale-patch data loss. Inspected generated OpenAPI and invoked the chat handler directly to verify contract and stub behavior.
- This is a source and local verification review, not a penetration test, dependency vulnerability scan, live cloud-provider evaluation, or cross-platform release certification. No real provider credentials were read or printed.

## Architecture and implementation maturity

```text
React desktop UI ── HTTP ── FastAPI sidecar ── core modules
       │                         │                  │
   Tauri/Rust              templates/pipelines   storage/memory
   process supervisor          DSPy/models       SQLite/Chroma

CLI / Streamlit / MCP ─────────── core modules
```

The intended layering is sensible: reusable Python logic, transport adapters, a desktop shell, and repository abstractions. The implementation is unevenly integrated.

| Area | What exists | Assessment |
|---|---|---|
| Dynamic agents | Pydantic blueprint configuration, dynamic DSPy signatures, tool registry, pipeline registration | Useful foundation; tools and declared guardrails need an enforced execution boundary |
| Provider routing | Configurable priority, health probes, circuit breaker, fallback support | Substantial implementation; direct API pipeline calls do not automatically inherit every execution-router guarantee |
| Cost discipline | Tier classifier, context budget builder, cache, evaluation and cost modules | Useful components; UI cost displays and some API results remain fabricated |
| Persistence | SQLite WAL, repository interfaces, SQLAlchemy backend, migrations, unified sessions | Real functionality; patch consistency and tenant authorization need work |
| Memory | Chroma persistence, observations, preference extraction, scoring | Implemented backend; desktop ingestion contract is broken |
| Safety | YAML policies, risk scoring, audit records, approval UI | Partial integration; approval records are not an execution authorization mechanism |
| Desktop | React components, mode pages, tasks, upload UI, Tauri IPC and supervisor | Compiles; major interaction paths are demonstrations |
| Distribution | Launcher generation, optional PyInstaller path, signing helpers, update manifests | Development scaffolding; release portability and trust verification are incomplete |
| SDKs / enterprise / orchestration | Workspace manifests, planned APIs, roadmap entries | Largely future work; should be explicitly described as such |

## Findings

Priority meanings: **P1** should be addressed before relying on the affected capability or distributing it to users; **P2** is important reliability or engineering work; **P3** is documentation or maintainability work. Findings marked source-confirmed were established by code inspection, without an exploit against a running user service.

### F01 — P1: Sidecar endpoints have no effective authentication

**Evidence:** `services/python/server/api.py:64`, `:1225`, `:1877`, `:1999`, `:2025`; `apps/desktop/src-tauri/src/sidecar.rs:243`.

The API configures wildcard CORS. `--token` merely stores `AGENT_ENGINE_IPC_TOKEN` in the environment; there is no request validation using it. The supervisor does not establish an authenticated IPC session. `/auth/session` always returns a local Owner identity.

Credential retrieval accepts `reveal=true` and returns plaintext without authorization. Credential mutation, patch application, session mutation, flag overrides, and approvals are also unprotected. Any process able to reach the API can exercise these capabilities. Wildcard CORS additionally permits cross-origin access where the browser allows local-network requests; exact browser behavior was not tested. The default loopback bind reduces remote exposure but does not establish caller identity.

**Remediation:** Generate a per-launch secret, enforce it on privileged routes, carry it through trusted desktop requests, and restrict allowed origins. Separate liveness from privileged APIs. Remove plaintext credential retrieval from the renderer unless there is a concrete need, and require explicit authorization for it.

**Acceptance:** Missing/incorrect credentials receive 401/403, arbitrary origins are rejected, and the authenticated desktop still works. Use fake secrets in regression tests.

### F02 — P1: Native sidecar startup reacquires a mutex it already holds

**Evidence:** `apps/desktop/src-tauri/src/sidecar.rs:261` and `:288`.

`start()` acquires `self.resolved_path.lock().await` into `path_guard`, updates the path, and retains the guard while calling `check_health()`. `check_health()` then awaits that same mutex. The original guard is not dropped until the enclosing scope exits, so startup cannot complete after a successful spawn. The HTTP timeout does not bound this mutex wait. The child-process lock is also held during startup, which can impede stop requests while startup is stuck.

This is source-confirmed; Rust compilation passes because the lock-order defect is a runtime problem.

**Remediation:** Limit the path guard to a small block or explicitly drop it before health polling. Review lock scope around process startup and shutdown.

**Acceptance:** A native test starts a controlled child and completes within a timeout; status and stop calls remain responsive.

### F03 — P1: Main UI and chat API report simulated execution as real work

**Evidence:** `apps/desktop/src/renderer/screens/Home.tsx:409`, `apps/desktop/src/renderer/components/ModePage.tsx:409`, `services/python/server/api.py:717`, `:867`.

Home builds canned response text and streams it with `requestAnimationFrame`. It claims cache hits, dispatched work, successful checks, and execution results without calling the backend execution path. Mode pages append a local “Executing … pipeline” message without running the pipeline. The chat API emits fixed greeting tokens or echoes the prompt; workflow execution returns a new ID and `queued` without queueing work.

A direct handler call asking “What is 2+2?” returned `Response from Agent Engine to: What is 2+2?`. Separate skill and pipeline endpoints do contain real DSPy calls, so this finding concerns the disconnected primary experience, not the absence of all agent execution.

**Remediation:** Connect one real conversation path to backend execution and persisted sessions. Drive result, failure, cancellation, usage, and approval UI from actual events. Put demonstrations behind an explicit demo mode. Unsupported workflows should return an honest unavailable response.

**Acceptance:** A controlled provider stub receives the user's prompt through the UI, its output appears in the conversation, session history survives reload, and a provider failure produces a visible error rather than a success narrative.

### F04 — P1: Desktop/API contract drift breaks basic operations

**Evidence:** `apps/desktop/src/renderer/api/client.ts:30`, `:70`, `:81`, `:120`; `apps/desktop/src-tauri/src/sidecar.rs:290`; `services/python/server/api.py:874`, `:999`, `:1388`, `:1970`.

| Consumer expectation | Implemented API | Consequence |
|---|---|---|
| `GET /v1/health` | `GET /healthz`, with different response shape | Both desktop health clients target a missing route |
| `POST /v1/memory/ingest` | `POST /v1/memory` | Document ingestion fails |
| Pipeline response `{ pipelines: [...] }` | Bare array | Client discards valid pipeline data |
| Session response `{ sessions: [...] }` | Bare array | Client discards valid session data |

Generated OpenAPI inspection confirmed the missing routes. The API has 53 documented paths in this environment.

**Remediation:** Choose one canonical contract and generate or validate client types against it. Correct the health payload mapping as well as the URL. Make errors visible instead of silently returning empty arrays.

**Acceptance:** Exercise these exact client methods against the real application in integration tests, including nonempty responses and failed requests.

### F05 — P1: Applying a staged patch silently destroys newer edits

**Evidence:** `core/storage/sqlite.py:259`; `core/storage/postgres.py:289`.

Both backends overwrite the target file with the stored patched content without comparing the current file with `original_code`. A user can stage a patch, continue editing, and then lose those intervening edits when applying it. File writing also occurs before the database transaction completes, leaving a consistency gap if persistence fails.

**Reproduced:** Stage `original → patched`, change the file to `new user edit`, then apply. The operation returns `True` and the file contains `patched`.

**Remediation:** Validate the expected original hash before application, report conflicts, enforce workspace path boundaries, and use an atomic replacement with a recoverable journal or backup strategy for file/database consistency.

**Acceptance:** A stale patch is rejected without changing the file; interrupted writes and database errors leave a recoverable state.

### F06 — P1: Safety evaluation fails open and approvals are only audit records

**Evidence:** `apps/desktop/src/renderer/api/client.ts:299`; `services/python/server/api.py:1322`; `core/pipelines/registry.py:76`; `services/python/server/api.py:1084`.

`evaluateToolSafety()` returns `decision: 'allow'` on HTTP errors and exceptions. The approval endpoint records client-supplied tool arguments, decision, risk, and operator text without binding them to a server-side pending operation. The pipeline registry stores guardrail metadata but its `run()` directly instantiates and invokes the module. Patch application does not consult a verified approval record.

These components do not yet create a mandatory policy boundary. The simulated UI limits what some current interactions actually execute, but connecting real operations to this design would preserve the gap.

**Remediation:** Enforce policy at the backend tool boundary; fail closed when policy evaluation is unavailable; bind approval to an operation ID, immutable argument digest, authenticated actor, expiry, and one-time consumption. Apply declared guardrails as executable checks.

**Acceptance:** Denied actions never execute; forged, expired, replayed, or argument-mismatched approvals fail; safety-service failure does not authorize work.

### F07 — P1: The Streamlit “sandbox” executes code with host privileges

**Evidence:** `server/dashboard.py:1230–1321`.

The sandbox runs `exec()` in the Streamlit process and explicitly exposes unrestricted `__import__`. A temporary working directory and a builtins list do not prevent code from importing `os`, reading absolute paths, creating processes, or using the network. There is no separate process timeout or resource boundary in this execution block. `os.chdir()` also changes the working directory for the entire process.

This path requires the dashboard's Run action; no remote exploit was attempted. The problem is the mismatch between a sandbox claim and actual host-level execution of generated code.

**Remediation:** Use a separately supervised restricted worker with explicit filesystem/network policy and resource limits. Until then, label this as trusted local code execution and keep it out of ordinary user flows.

**Acceptance:** Attempts to access a designated forbidden test path, import disallowed capabilities, or run indefinitely are blocked or terminated without affecting the UI process.

### F08 — P1: Sidecar trust checks verify a hash but not the manifest signature

**Evidence:** `apps/desktop/src-tauri/src/sidecar.rs:165–225`; `core/updater/manager.py:437`.

The native supervisor reads a signed manifest but only extracts its SHA-256 field. It never verifies the Ed25519 signature and also accepts plain manifests or a checksums file. Replacing both binary and adjacent hash metadata defeats this authenticity check. The Python update checker verifies signatures only when `_manifest_signature` is present, allowing unsigned manifests through the update-discovery path.

Python signing utilities are useful, but they do not make a separate native consumer verify authenticity. Update discovery acceptance is not proof of automatic code execution; installation was not exercised.

**Remediation:** Pin a trusted public key in the release client, verify signed metadata before trusting hashes, reject unsigned release feeds, and confine bypasses to explicit development builds.

**Acceptance:** A modified binary plus recomputed unsigned metadata is rejected; missing, invalid, and untrusted signatures fail in the actual consuming client.

### F09 — P2: Scheduled-task actions can falsely report success

**Evidence:** `apps/desktop/src/renderer/api/client.ts:388–468`.

The client calls `/v1/tasks`, but the server has no task routes. Listing falls back to demonstration tasks; creation fabricates an active task after failure; toggling ignores HTTP status; run/delete report success on network exceptions. A user can believe a job is scheduled even though nothing will run.

**Remediation:** Clearly separate demonstration data, persist actual schedules before reporting success, and propagate failures. Until a scheduler exists, mark the controls unavailable or explicitly demonstrative.

**Acceptance:** Creating a task survives restart and produces a real scheduled run, or the interface clearly states scheduling is unavailable. Offline failures never produce a success state.

### F10 — P2: Synchronous work blocks asynchronous API handlers

**Evidence:** `services/python/server/api.py:830`, `:894`, `:989`, `:1108`, `:1660`, `:1917`, `:1949`.

Several `async def` routes call synchronous model execution, vector operations, provider probes, evaluation, or update requests directly. A slow call can block the event loop serving unrelated requests and SSE delivery. Startup also constructs persistent services during module import.

**Remediation:** Use synchronous route functions or a bounded worker pool for blocking work, and background jobs for long evaluations. Define timeouts and cancellation semantics. Initialize state through an explicit application lifecycle.

**Acceptance:** During a deliberately slow model/evaluation call, health, cancellation, and unrelated read requests remain responsive.

### F11 — P2: Tenant fields do not enforce tenant isolation

**Evidence:** `core/storage/postgres.py:389`, `:406`, `:444`, `:507`; `services/python/server/api.py:1368–1530`.

Session lookup, update, and deletion use only a session ID. Tenant filters are optional on listings, and the API has no trusted authenticated tenant context. Tenant columns and indexes therefore do not establish cross-tenant authorization. PostgreSQL parity tests use SQLAlchemy with SQLite rather than a real PostgreSQL service (`tests/test_storage_repository.py:283`).

Enterprise work is correctly listed as future roadmap work; the present README's multi-tenant isolation claim is stronger than the implementation.

**Remediation:** Keep multi-user deployment gated. Derive tenant identity from authentication, enforce it on every operation, and add real PostgreSQL integration tests, including migrations and cross-tenant access attempts.

### F12 — P2: Bootstrap, verification, and CI can give misleading confidence

**Evidence:** `Makefile:31–58`; `.github/workflows/ci.yml`; `apps/desktop/package.json`; `tests/test_api_contract.py:152`; `tests/test_desktop_shell.py`; `tests/test_ci_workflows.py`.

- `make bootstrap` creates a virtual environment and lists packages; it does not install the declared dependencies.
- The lint recipe uses `... || ... || echo`, so a real lint failure can end in a successful warning and a zero exit code.
- Desktop `test` and `lint` scripts only print success messages.
- The JS workspace CI job reads package metadata without installing dependencies or building the frontend. There is no native Rust check in that workflow.
- The Python suite requires `apps/desktop/dist/index.html`, but its CI job never builds or downloads that artifact. The isolated run reproduced this missing-build failure; copying the successfully built frontend into the test checkout made that test pass.
- Frozen-schema tests verify path/method presence, not complete schema compatibility or desktop-client behavior.
- Many desktop tests inspect source strings and configuration rather than running the interactions they describe.
- Tests initialize global services and some use persistent defaults. They should not depend on a developer's databases, installed sidecar artifacts, or live services.

**Remediation:** Make bootstrap install from existing lockfiles; preserve command failures; add real frontend/client/native checks; isolate test state; require behavior-based acceptance tests for critical paths. Keep structural tests, but do not use them as evidence that runtime features work.

### F13 — P2: Release packaging is not yet a standalone desktop distribution

**Evidence:** `scripts/bundle_sidecar.py:52–165`; `.github/workflows/release.yml`; `packages/sdk-js/package.json`; `packages/sdk-python/pyproject.toml`.

The default sidecar build is a launcher depending on a Python environment and repository modules. Freezing is opt-in and can fall back to launcher mode. On Windows the launcher path uses an `.exe` filename for batch-style content, which does not establish a native executable. CI bundles the default launcher. The release workflow runs `uv build` on Ubuntu and publishes `dist/*`, without producing and verifying native desktop installers for the supported platforms.

The JS SDK declares `dist/index.js` but has only metadata/README files and placeholder scripts; the Python SDK similarly contains no implemented client package in tracked files. SDKs are roadmap work, not usable libraries today.

**Remediation:** Distinguish development launchers from release binaries, fail release builds if freezing fails, and test installation on clean machines without the checkout. Publish SDKs only once package contents and consumer smoke tests pass.

### F14 — P2: Launcher cleanup is unreachable after `exec`

**Evidence:** `start_studio.sh:50–75`.

The script starts a watcher and possibly inference daemons, then replaces itself with Streamlit via `exec`. The cleanup function and signal trap are defined afterward and will never run when `exec` succeeds. Closing the dashboard therefore does not execute the intended cleanup of processes this launcher started.

**Remediation:** Install traps before starting children and supervise the foreground process without replacing the supervising shell, or use a dedicated process supervisor. Preserve the existing distinction between processes started here and already-running services.

**Acceptance:** Exiting the launcher terminates its own children while leaving previously running inference services untouched.

## Additional maintainability observations

- The API module is 2,031 lines, the Streamlit dashboard 1,914, the SQLite/PostgreSQL backends 1,063/1,017, and Home 1,136. Group routes by domain and move execution orchestration into explicit services after the critical behavior is fixed.
- `core/__init__.py` imports a broad dependency graph and replaces DSPy's private `_ensure_configure_allowed` method. This weakens the library's configuration safeguards and complicates concurrent model selection. Prefer scoped model configuration rather than a global monkey patch.
- Global SSE subscriber queues are unbounded (`services/python/server/api.py:760`). Define queue limits, slow-client handling, and heartbeat behavior before depending on them for sustained telemetry.
- `core/engine.py:81` restricts calculator characters, which rules out a straightforward arbitrary-name `eval` injection. However, it permits arbitrarily expensive arithmetic such as large exponentiation; add bounded parsing and operation limits. This review does not classify that calculator as an unrestricted code-execution vulnerability.
- Directly imported runtime dependencies should be declared directly. For example, root code imports `cryptography` and `numpy` while relying on the transitive dependency graph to provide them.
- Python metadata advertises 3.10+, Ruff targets 3.12, and CI covers 3.11/3.12. Verify the supported minimum against a clean locked installation and align the documentation.
- README version `1.0.0` conflicts with package/native version `0.1.0`. README and memory claim 240 passing tests, while the roadmap summary still marks M2 pending despite completed phase entries. Replace fixed claims with dated verification evidence and distinguish interface completion from execution completion.
- README contains stale machine-specific absolute `file://` links and references a `LICENSE` file that is absent from tracked files. Use relative links and add the intended license text through a normal project decision.

## Recommended delivery sequence

### 1. Make the existing local experience trustworthy

Fix F01–F06 first: authenticate privileged APIs, repair startup locks and health contracts, remove simulated success from normal flows, and protect patch application. Clearly mark unavailable scheduling/workflow features. These are prerequisites for relying on the application to perform work.

### 2. Deliver one complete agent interaction

Use a deterministic provider stub initially, then a local model. Implement prompt submission, true streamed output, cancellation, persisted conversation, real usage accounting, policy interception, and approval resumption. Add a reload test and explicit provider/error-path tests. Confirm that model choice actually changes backend behavior.

### 3. Make verification reflect the product

Repair bootstrap and lint exit codes. Add client/server contract tests, native supervisor runtime tests, and an isolated backend fixture. Run frontend build and native checking in CI. Add a real PostgreSQL job only when claiming PostgreSQL behavior. Use clean-machine packaging smoke tests before release.

### 4. Harden and expand

Complete restricted code execution, signed release verification, process supervision, and bounded background work. Then resume broader dashboard, adapter, orchestration, enterprise, and SDK roadmap items. Track implementation, integration, and tested behavior separately.

## Verification record

Environment: Python 3.12.14, Ruff 0.16.6, Node 22.22.2, pnpm 9.15.0, Cargo 1.98.1. Results apply to the existing local environment, not a freshly installed dependency set.

| Check | Result |
|---|---|
| `.venv/bin/ruff check . --output-format concise` | Passed |
| `.venv/bin/ruff format --check .` | Failed: `tests/test_api_contract.py` and `tests/test_sidecar_bundling.py`; 98 files already formatted |
| `pnpm --filter @agent-engine/desktop build` | Passed TypeScript and Vite production build; 1,616 modules transformed |
| `cargo check --locked --offline` in `apps/desktop/src-tauri` | Passed |
| Generated OpenAPI inspection | Confirmed missing `/v1/health`, `/v1/memory/ingest`, and `/v1/tasks`; `/healthz` and `/v1/memory` exist |
| Direct non-streaming chat handler invocation | Confirmed prompt echo rather than inference |
| Temporary-file stale patch reproduction | Confirmed newer contents overwritten; application returned success |
| Python suite in isolated tracked-file copy, outside sandbox | **239 passed, 1 failed, 2 warnings in 45.03 seconds**. The failure was `test_built_distribution_bundle`, because the isolated checkout had no generated frontend build |
| Failed test rerun after supplying the verified frontend build | **1 passed in 0.03 seconds**. All 240 collected cases therefore passed across the suite run and focused rerun; a second full-suite run was not performed |

Sandboxed API-test runs stalled; they were stopped, and the suite completed outside the sandbox with authorization. A bounded diagnostic attempt also timed out. The isolated test directory was `/tmp/agent-engine-review-gue2pnox`. The missing frontend artifact is a test setup/CI dependency issue, not evidence that the frontend cannot compile. The recorded 240 collected cases also illustrates why a static count of 243 function definitions must not be reported as 243 executed tests.

Only this report was added to the source working tree. Verification regenerated ignored frontend build output and used existing Rust build caches. No fixes were applied, no commits were created, and no workspace structure or launcher configuration was changed.

No live model inference, actual malicious-origin browser request, native GUI launch, signed installer installation, production PostgreSQL instance, or restricted-code-worker test was performed. Source-confirmed findings should receive the focused regression tests described above during remediation.
