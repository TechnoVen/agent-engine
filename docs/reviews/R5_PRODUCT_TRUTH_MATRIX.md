# Agent Engine — R5 Product Truth & GUI Regression Matrix

> **Document Type:** Product Truth & GUI Regression Contract  
> **Milestone:** R5 (Founder Dogfood & Capability Packs) — Product Truth & Dogfood UI Gate  
> **Status:** Canonical & Enforced  
> **Governing Principles:** Zero unlabeled demo data, local-first operational truth, real backend bindings, and fail-honest error states.

---

## 1. Governing Invariants

Across the desktop shell, every visual element, statistic, list, and control must conform to the following invariants:
1. **Product Truth Rule:** Every visible datum is strictly one of:
   - **Real backend / persisted state** (retrieved from canonical Sidecar REST API, SQLite, or local filesystem).
   - **Truthful empty state** (clearly communicating that zero user records exist, with an actionable primary button).
   - **Explicit unavailable / error state** (clearly communicating when a subsystem is offline or unconfigured).
2. **Zero Unlabeled Demo Data:** Demo fixtures or mock rows are completely banned from default founder operation. Any optional demo fixture must be gated behind explicit configuration and visibly labeled as `Demo data`.
3. **Local-First System Status:** Agent Engine is an autonomous, local-first engine. Missing optional cloud provider credentials (OpenAI, Anthropic, Google Gemini) do **not** mark the product as globally `Degraded`. The global status indicator remains `Ready` whenever the local runtime, SQLite database, and Execution Coordinator are operational.
4. **No Stale Milestone Language:** All user-facing text reflects the current operating reality. Stale preview banners ("Coming in R4") are removed from user interfaces; durable workflows and background jobs are live substrates.
5. **Button Functionality Truth:** Every clickable button executes a real API operation, opens a functional dialog, or is explicitly disabled with an accessible reason. Clickable no-ops and simulated spinners are strictly prohibited.

---

## 2. Screen-by-Screen Product Truth Matrix

| Screen / Surface | Visible Control / Element | Canonical Data Source | Loading State | Empty State | Error / Unavailable State | Demo Data Allowed? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Home / Chat** (`Home.tsx`) | Session list & active conversation | `GET /v1/sessions`<br>`GET /v1/sessions/{id}` | Skeleton session loader | "Start your first conversation with Nadir's Agent" + Quick Prompts | "Failed to connect to local session store" | **NO** |
| | Prompt input & streaming chat | `POST /v1/chat/completions` (SSE tokens, cost update, done) | Real token-by-token streaming with live token counter | Clean empty input box | HTTP 502 / Error banner with exact upstream exception | **NO** |
| | Project selector | `GET /v1/projects` via `ProjectService` | Muted dropdown skeleton | "No project selected" | Dropdown disabled, falls back to default workspace | **NO** |
| **2. Writing Pack** (`Writing.tsx`) | Document title & notes | Local editor state + `GET /v1/writing/workflows` | Empty editor initialization | Initialized to "Untitled Article" + empty notes | Error notification on save/run failure | **NO** |
| | Full Pipeline Execution | `POST /v1/writing/workflows` (canonical WorkflowService + JobService) | Progress indicator tied to active stage | "No active workflow run" | Stage error card with retry/inspect action | **NO** |
| | Stage Controls (Plan, Draft, Edit, Review, Polish) | Canonical Workflow Run node statuses | Step spinner reflecting real Job lifecycle | Clean stage outline waiting for initiation | Highlighted red badge with exact failure reason | **NO** |
| **3. Research** (`Research.tsx`) | Research query & synthesis | `POST /v1/chat/completions` (local synthesis engine) | Streaming synthesis output | "Enter a topic to generate synthesized research" | "Local synthesis engine unavailable" | **NO** |
| | Grounding sources panel | Canonical Knowledge & Project artifacts (`GET /v1/knowledge`) | Source item loading skeleton | "No grounded sources linked yet" | "Grounding store disconnected" | **NO** |
| | Web Deep Crawler badge | Static capability descriptor | Instant | "Web research unavailable" (Research Pack R5.3 not started) | Disabled toggle with uninstalled explanation | **NO** |
| **4. Automations & Workflows** (`Workflows.tsx`) | Saved Workflows list | `GET /v1/workflows` via `WorkflowService` | List skeleton | "No workflows created yet. Author a new pipeline." | "Workflow storage unavailable" | **NO** |
| | Visual DAG Designer & JSON Editor | `WorkflowDefinition` parser & validator | Canvas loader | Blank canvas with drag-to-start node palette | Syntax error banner with exact line/column | **NO** |
| | Execute Workflow button | `POST /v1/workflows/{id}/run?canonical=true` | Spinner + Run ID notification banner | Disabled when workflow has syntax errors | Error alert dialog with execution exception | **NO** |
| **5. Scheduled Tasks** (`Tasks.tsx`) | Scheduled tasks list | `GET /v1/tasks` (SQLite `scheduled_tasks`) | Table skeleton | "No scheduled tasks. Create a scheduled task to run work automatically." | "Scheduler offline: Tasks persisted but will not trigger" | **NO** |
| | Trigger On-Demand button | `POST /v1/tasks/{id}/run` (dispatches to JobService queue) | Action toast notification | N/A | Toast error if job enqueue fails | **NO** |
| | Curated Templates modal | Built-in template definitions (Executive Drafter, etc.) | Instant | N/A | Form validation errors inline | **NO** |
| **6. Data** (`Data.tsx`) | Data grid & dataset table | User-uploaded CSV / persisted session data | Grid skeleton | "No execution records or dataset loaded. Upload a CSV to begin analysis." | Parse error toast on malformed CSV | **NO** |
| | Telemetry & Cost breakdown | `GET /v1/telemetry/cost` | Loading badge | Real empty stats ($0.00 spend, 0 tokens) | "Telemetry unavailable" | **NO** |
| | Formula Engine status | Formula capability banner | Instant | "Formula Runtime: Planned" | Clearly labeled as planned / unavailable | **NO** |
| **7. Developer** (`Developer.tsx`) | Traces & Executions table | `GET /v1/executions`<br>`GET /v1/executions/{id}/trace` | Table skeleton | "No execution traces logged yet. Execute prompt or workflow to record traces." | "Execution ledger unreachable" | **NO** |
| | MCP & Adapters catalog | `GET /v1/adapters` | Cards skeleton | "No active MCP adapters registered." | "Adapter service disconnected" | **NO** |
| | Provider verification statuses | `GET /v1/providers` | Badges skeleton | Real verified providers (e.g. Local Llamacpp, Ollama) | Red "Unconfigured" or "Failed" badge | **NO** |
| **8. Projects** (`Projects.tsx`) | Workspaces list | `GET /v1/projects` (`ProjectService`) | Cards skeleton | "No projects found. Create a project to scope memory, files, and rules." | "Project service unavailable" | **NO** |
| | Security Policy preset | `Zero-Trust Protected` / `Strict Zero-Trust` | Instant | Selected policy badge | N/A | **NO** |
| | Create Project modal | `POST /v1/projects` | Submit button spinner | Form inputs cleared | Inline error if directory invalid or duplicate | **NO** |
| **9. Project Detail** (`ProjectDetail.tsx`) | Threads, Files, Active Agents | Scoped project properties (`GET /v1/projects/{id}`) | Tab skeleton | Empty threads list ("No scoped threads yet"), empty files list | Error toast on save failure | **NO** |
| | Scoped Instructions & Policies | Project settings stored in SQLite | Save button state indicator | Empty text area with placeholder guidelines | Save failure banner | **NO** |
| **10. Approvals** (`Approvals.tsx`) | Pending Human Approvals | `GET /v1/policies/approvals/pending` | Queue skeleton | "Approval queue empty. All execution gates cleared." | "Policy engine disconnected" | **NO** |
| | Approve / Reject actions | `POST /v1/policies/approvals/{id}/resolve` | Action button spinner | Queue item removes upon resolution | Resolution conflict error toast | **NO** |
| **11. Activity** (`Activity.tsx`) | Audit ledger & system events | `GET /v1/executions` (SQLite ExecutionLedger) | Timeline skeleton | "No audit events recorded yet." | "Audit store unavailable" | **NO** |
| **12. Settings** (`Settings.tsx`) | Providers & Models configuration | `GET /v1/models`<br>`GET /v1/providers` | Settings tab loader | Empty API keys with safe masked inputs | Provider test failure badge with status code | **NO** |
| | Storage, Security, Appearance | Local settings & system configuration | Instant | Default preferences applied | Error message on keychain write failure | **NO** |
| **13. TopBar & Popover** (`TopBar.tsx`) | Global Status dot & label | `GET /v1/health` + `sidecarClient.getHardwareTelemetry()` | Instant (`Ready` default) | N/A | `Offline` (red) if sidecar unreachable; `Busy` (pulse) during runs | **NO** |
| | System Status Popover | Subsystem health checks (Execution, Worker, Scheduler, DB, Local runtime, Sandbox, Cloud) | Instant | Detailed itemized breakdown of subsystem health | Specific subsystem marked Offline/Stopped; cloud marked Local-first (Optional) | **NO** |
| | Hardware Telemetry | `/v1/telemetry/hardware` (RAM, CPU, GPU, VRAM) | Polled every 2s-5s | "Standby" when local runtime inactive | Grayed out when telemetry tracker unavailable | **NO** |
| **14. Layout & Sidebar** (`Layout.tsx`, `Sidebar.tsx`) | Sidebar Projects list | Canonical `GET /v1/projects` store | Instant | "No projects yet" (synchronized with Projects screen) | Offline notice | **NO** |
| | Recent Chats list | Canonical `GET /v1/sessions` store | Instant | Empty chat history list | Offline notice | **NO** |
| | Navigation buttons & New Chat | Hash routing (`#home`, `#writing`, etc.) | Instant route transition | N/A | N/A | **NO** |

---

## 3. Subsystem Health & Degraded Rules

In accordance with Phase D of the CTO directive:
1. **Ready:** All required local services are operational:
   - FastAPI Sidecar HTTP server (`http://127.0.0.1:8765` or `:8000`)
   - SQLite persistent storage engine (`agent_engine.db` with migrations 001–009)
   - Canonical `ExecutionCoordinator` and `JobService`
   - Local execution runtime / LLM provider (Ollama / LlamaCPP / deterministic code)
2. **Busy:** Active execution underway in the foreground (chat streaming or workflow execution running).
3. **Degraded:** A **required** local subsystem is in an unhealthy state (e.g. database locked, disk full, corrupted local runtime). Missing optional cloud API keys (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) **must not** degrade the engine.
4. **Offline:** Sidecar process is unreachable or crashed.

---

## 4. Regression Verification Suite

Compliance with this matrix is continuously enforced via automated tests in:
- `tests/test_desktop_shell.py`: Validates screen elements, local streaming, session persistence, and truthful empty states.
- `tests/test_product_truth_ui.py`: Verifies cross-surface consistency, zero default demo projects, zero synthetic scheduled tasks, zero fake economics rows, and truthful popover statuses.
- `tests/test_r5_2_writing_pack.py`: Validates canonical WorkflowService and JobService convergence for multi-stage writing pipelines.
