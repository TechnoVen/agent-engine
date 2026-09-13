# 📘 Agent Engine User Guide & Operational Manual

Welcome to **Agent Engine** — the sovereign, local-first multi-agent desktop studio and control plane. This guide provides end-to-end instructions for launching, navigating, and getting the most out of your Agent Engine experience.

---

## 📑 Table of Contents

1. [Architecture & System Overview](#1-architecture--system-overview)
2. [Quickstart & Running the Application](#2-quickstart--running-the-application)
3. [Tour of Screens & Navigation](#3-tour-of-screens--navigation)
   - [Home Screen & Chat](#home-screen--chat)
   - [3-Zone Sidebar & Session Search](#3-zone-sidebar--session-search)
   - [Document Ingestion & RAG](#document-ingestion--rag)
   - [My Agent (Identity, Growth & Memory)](#my-agent-identity-growth--memory)
   - [Scheduled Tasks & Cron Engine](#scheduled-tasks--cron-engine)
   - [Capability Modes & Curated Cases](#capability-modes--curated-cases)
4. [Power Features & Shortcuts](#4-power-features--shortcuts)
   - [Universal Chat Input](#universal-chat-input)
   - [Slash Commands & Skills](#slash-commands--skills)
   - [Zero-Trust Inline Approvals](#zero-trust-inline-approvals)
   - [Keyboard Shortcuts](#keyboard-shortcuts)
5. [The Governing Laws of Agent Engine](#5-the-governing-laws-of-agent-engine)
6. [Sidecar API & Backend Services](#6-sidecar-api--backend-services)
7. [Troubleshooting & FAQ](#7-troubleshooting--faq)

---

## 1. Architecture & System Overview

Agent Engine is designed from the ground up as a **local-first desktop studio**:
- **Desktop Shell (`apps/desktop/`):** Built with Tauri v2, React 18, Vite 5, TypeScript, and Tailwind CSS. Provides a 60fps responsive desktop GUI with dark-theme design tokens (`--bg-base: #0a0a0a`).
- **Python Sidecar (`services/python/server/api.py`):** Supervised by the Tauri Rust core (`apps/desktop/src-tauri/`), exposing local FastAPI REST and SSE endpoints for DSPy dynamic signature compilation, ChromaDB vector memory, semantic caching, and execution routing.
- **Storage Layer:** Embedded SQLite with WAL mode (`data/`) for sessions, observational memory, task schedules, and staged code sentry patches.
- **Zero Cloud Leakage:** All credentials reside in the OS secure keychain (`core/security.py`). Models default to local inference runtimes (`llama.cpp` on port 8080 or `Ollama` on port 11434) with optional cloud fallback.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                         TAURI V2 DESKTOP SHELL                           │
│  ┌──────────────────────┐  ┌────────────────────┐  ┌──────────────────┐  │
│  │   Home & Studio      │  │  My Agent Screen   │  │  Scheduled Tasks │  │
│  │   (React 18 + TS)    │  │  (Heatmap & Mem)   │  │  (Cron & Presets)│  │
│  └──────────────────────┘  └────────────────────┘  └──────────────────┘  │
│                              │                                           │
│                    Local HTTP & IPC (Port 8000)                          │
│                              │                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │               PYTHON SIDECAR (FastAPI + DSPy Engine)               │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  ┌─────────┐  │  │
│  │  │ Observational│  │ 90/9/1 Router│  │ ChromaDB RAG│  │ Semantic│  │  │
│  │  │    Memory    │  │ & Sentry     │  │ Vector Store│  │  Cache  │  │  │
│  │  └──────────────┘  └──────────────┘  └─────────────┘  └─────────┘  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quickstart & Running the Application

### Prerequisites
- **Python 3.10+** (Virtual environment managed in `.venv/`)
- **Node.js 18+** & **pnpm** (`pnpm -v`)
- **Rust & Cargo** (for Tauri native builds)

### Launching Option A: Interactive Browser Mode (Fastest)

Run the desktop shell in your web browser with live reloading:

```bash
# Terminal 1 (Optional, starts Python sidecar backend):
.venv/bin/python services/python/server/api.py --port 8000

# Terminal 2 (Starts Vite desktop frontend):
make desktop-dev
```

Open your browser to: **`http://localhost:5173`**.

### Launching Option B: Native Desktop App (Tauri)

To launch the native desktop window with local OS integration:

```bash
make desktop-tauri-dev
```

### Running Verification & Tests
Ensure all system components and security gates pass:
```bash
make verify                               # Runs ruff linter and full test suite (240 tests)
pnpm --filter @agent-engine/desktop build # Validates TypeScript with 0 errors
```

---

## 3. Tour of Screens & Navigation

The desktop shell utilizes URL hash routing, allowing instant navigation via sidebar or direct URL bookmarks.

### Home Screen & Chat
- **Route:** `http://localhost:5173/#home`
- **Greeting & Inspiration:** Context-aware greeting with quick inspiration prompts ("Build an invoice agent", "Analyze codebase architecture", "Deep market research report").
- **Streaming Messages:** 60fps streaming text rendering via `requestAnimationFrame` with animated pulse indicators.
- **Attribution & Telemetry:** Every assistant response displays token throughput (e.g. `48 tok/s`), processing latency (e.g. `312ms`), and estimated cost preview.

### 3-Zone Sidebar & Session Search
- **Zone A (Global Actions):** "New Chat" button with global shortcut display (`Ctrl+K`), quick search bar, and sidecar connectivity indicator.
- **Zone B (Capability Modes):** Direct links to all 8 specialized capability modes and system views.
- **Zone C (Context & History):** Recent project list, active chat history filtered in real-time, and user profile card.
- **Real-Time Search:** Type any query into the search input to filter sessions via `/v1/sessions/search`. Press `Esc` to instantly clear search results.
- **Sidebar Collapse:** Click the collapse arrow to minimize into a compact icon strip.

### Document Ingestion & RAG
- **Drag-and-Drop:** Drag any file (.pdf, .csv, .py, .ts, .md, .txt) directly onto the window canvas.
- **Interactive Chips:** Uploaded documents display as attachment chips in the universal chat input.
- **Snippet Previews:** Click any chip to inspect indexed snippets and token metrics before dispatching.
- **Automatic Vector Indexing:** Attachments are grounded into ChromaDB vector storage via `/v1/memory`.

### My Agent (Identity, Growth & Memory)
- **Route:** `http://localhost:5173/#agent`
- **Identity Banner:** Personal agent avatar, level badges, and interaction streaks.
- **365-Day Heatmap:** GitHub-style interaction activity heatmap rendering in <200ms with level grading.
- **Closeness Tab:** Measures trust index, communication style affinity, and topic familiarity.
- **Growth Tab:** Radar visualization of skills unlocked and cognitive milestones.
- **Memory Tab:** Searchable, editable observational ledger backed by `/v1/memory/observations`. Edit or delete learned facts inline, or add custom directives manually.
- **Self-Growth Toggle:** Persistent per-user switch allowing the agent to continuously learn durable preferences from conversation turns.

### Scheduled Tasks & Cron Engine
- **Route:** `http://localhost:5173/#tasks`
- **Plain-English Cron Builder:** Real-time translation of cron expressions (e.g., `0 3 * * *` translates to *"Runs every day at 03:00"*).
- **Off-Peak Execution (Law 7):** Tasks default to off-peak scheduling (02:00–06:00 window) to protect frontier quota and reduce compute costs.
- **3 Creation Pathways:**
  1. *Manually:* Configure custom schedule and execution parameters.
  2. *Via Chat:* Instruct the agent in plain language to generate the cron job.
  3. *From Template:* Select from pre-built routines (Daily Code Sentry, Weekly RAG Reindex, Daily Financial Digest, Backup Ledger).
- **Multi-Channel Alerts:** Configure notification destinations across Slack, Telegram, and Webhook bridges on task failure.

### Capability Modes & Curated Cases
Agent Engine features 8 capability modes, each accessible via URL hash and pre-configured with 4 curated real-world problem templates (32 total curated cases):

| Mode | Route | Pipeline | Description |
|---|---|---|---|
| **Code Studio** | `#code` | `code_fix` | AST refactoring, pytest test generation, zero-trust security audits, concurrency review |
| **Deep Research** | `#deep-research` | `deep_research` | Autonomous agent swarms, local-first LLM landscape, vector DB comparisons |
| **Docs & Writing** | `#docs` | `summarize` | RFC architecture specs, enterprise SLAs, PRDs, commercial partnership proposals |
| **Data & Sheets** | `#sheets` | `data_analysis` | SaaS unit economics, cohort retention, Excel XLOOKUP automation, DCF models |
| **Presentation Slides** | `#slides` | `summarize` | 10-slide pitch decks, QBR executive updates, architecture review decks |
| **Websites & Apps** | `#websites` | `code_fix` | High-converting dark-mode landing pages, analytics dashboards, accessible components |
| **UI/UX Design** | `#design` | `summarize` | Dark-mode token systems, micro-interaction specs, multi-pane wireframes, APCA contrast audits |
| **Diagrams & Arch** | `#diagrams` | `summarize` | Mermaid sequence diagrams, C4 container models, 90/9/1 execution flows |

---

## 4. Power Features & Shortcuts

### Universal Chat Input
The universal `ChatInput` component powers every screen in the studio:
- **60fps Scaling:** Dynamic textarea auto-growth governed by `requestAnimationFrame`, tested for sub-16ms latency on 10,000+ character inputs.
- **Clipboard Paste & Drag-Drop:** Paste screenshots directly from your clipboard (`Ctrl+V`) to attach base64 image previews.
- **Token Estimator (±5% Calibrated):** Accurate pre-execution token counting that distinguishes between code/JSON (~3.6 chars/tok) and English prose (~3.9 chars/tok).
- **Model Tier Selector:** Quick toggle between `Instant High` ($0.0002/1k), `K3 Swarm High` ($0.0015/1k), and `K3 High` ($0.0080/1k).

### Slash Commands & Skills
Type `/` in the input field to trigger the command palette:
- `/skill <name>` — Run registered DSPy skills
- `/agent <persona>` — Switch active agent personality
- `/workflow <name>` — Execute predefined agent workflows
- `/web-search <query>` — Ground query with live web citations
- `/memory <query>` — Query long-term vector memory
- `/sandbox <code>` — Run code in the isolated execution sandbox
- `/clear` — Reset current conversation session

### Zero-Trust Inline Approvals
When an agent proposes an action that could impact your system (e.g. shell command execution, file modifications, git operations), an interactive `ApprovalCard` appears:
- **Risk Badges:** Color-coded severity tiers (`High Risk`, `Warning`, `Standard`).
- **Diff & Argument Editor:** Review exact code diffs and edit proposed JSON arguments inline before approving.
- **60-Second Auto-Expire:** Unapproved high-risk operations automatically reject after 60 seconds of inactivity to protect unattended machines.

### Keyboard Shortcuts

| Shortcut | Action | Scope |
|---|---|---|
| `Ctrl + K` / `Cmd + K` | Focus universal chat input / Quick palette | Global |
| `Enter` | Submit message | Chat input |
| `Shift + Enter` | Insert newline | Chat input |
| `ArrowUp` / `ArrowDown` | Navigate slash command popup suggestions | Chat input |
| `Tab` / `Enter` | Autocomplete selected command or skill | Slash popup |
| `Esc` | Clear session search / Dismiss modals | Global |

---

## 5. The Governing Laws of Agent Engine

Agent Engine is engineered around strict operational principles:

1. **Law 1: The 90/9/1 Rule**
   - 90% of execution steps are handled by deterministic CODE, AST tools, and the Semantic Cache ($0 token cost).
   - 9% of routine tasks are routed to SMALL/MID tier models ($0.0002–$0.0015/1k).
   - <= 1% of complex reasoning escalates to frontier models ($0.0080/1k).
   - Overall execution budgets remain strictly below 8,000 tokens per workflow.
2. **Law 3: Zero-Trust Security**
   - Destructive operations (`rm -rf`, disk formatting, database drops, git force pushes, secrets file access) are blocked by default and require explicit human-in-the-loop approval.
3. **Law 7: Off-Peak Task Scheduling**
   - Heavy background tasks, reindexing routines, and batch audits default to the 02:00–06:00 local time window to preserve day-time interactive responsiveness.

---

## 6. Sidecar API & Backend Services

The Python sidecar runs on `http://127.0.0.1:8000` and provides comprehensive OpenAPI 3.1 documented endpoints (`http://localhost:8000/docs`):

- `GET /healthz` — Sidecar heartbeat and supervisor probe.
- `GET /v1/cases` — List all curated case templates across the 8 capability modes.
- `GET /v1/cases/{mode}` — Get curated cases for a specific mode (`code`, `deep-research`, etc.).
- `GET /v1/memory` & `POST /v1/memory` — Query and ingest passages into ChromaDB.
- `GET /v1/memory/observations` — Query observational memory ledger.
- `GET /v1/sessions` & `GET /v1/sessions/search` — Session store search and history retrieval.
- `GET /v1/telemetry/cost` — Live cost tracker metrics and 90/9/1 compliance audit.
- `GET /v1/router/tiers` — Model tier definitions and active provider configurations.

---

## 7. Troubleshooting & FAQ

### Q: The top bar shows "Sidecar Offline"?
**A:** Ensure the Python backend is running. Start it manually with:
```bash
.venv/bin/python services/python/server/api.py --port 8000
```
In native desktop mode (`make desktop-tauri-dev`), the Tauri supervisor automatically starts and manages the sidecar lifecycle.

### Q: How do I change the default LLM provider?
**A:** The engine auto-detects local providers. To set an explicit provider or API key, configure `.env`:
```bash
DEFAULT_MODEL_PROVIDER=ollama      # Options: ollama, llamacpp, gemini, openai, anthropic
OLLAMA_BASE_URL=http://localhost:11434
```

### Q: How do I verify that everything is working?
**A:** Run the comprehensive verification target:
```bash
make verify
```
All 240 tests across router, memory, sentry, cache, storage, templates, and desktop shell should pass with 100% green status.
