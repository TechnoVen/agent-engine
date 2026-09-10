# 🚀 Agent Engine – Autonomous Local-First Multi-Agent Studio

**v1.0.0** · Tauri v2 + FastAPI + DSPy + ChromaDB + FastMCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![DSPy](https://img.shields.io/badge/DSPy-3.0+-green.svg)](https://dspy.ai/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-red.svg)](https://streamlit.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 Overview

**Agent Engine** is a **cross-platform, local-first, multi-agent studio** that lets anyone (developer, author, business owner, enterprise) build, run, supervise, and deploy AI agents — locally or in the cloud — with safety, memory, workflow orchestration, cost discipline, and human approval built in.

Think of it as **VS Code for agents**:
- 🧠 **Dynamic Agent Compilation** – build low‑code AI agents using DSPy signatures, no prompt engineering required.
- 🛡️ **Autonomous Code Sentry** – a file‑watcher that audits Python code for security vulnerabilities and PEP‑8 style issues, automatically staging or applying fixes with infinite-loop breakers.
- 📚 **Persistent RAG Memory** – ChromaDB vector store for long‑term knowledge retrieval and semantic search.
- 🔌 **IDE Integration & Protocols** – expose agent tools via the Model Context Protocol (MCP stdio/SSE) and Agent Client Protocol (ACP).
- 📊 **Unified Control Center** – web dashboard and desktop studio with hardware telemetry, memory search, interactive sandbox with 1-click AST repair, and performance benchmarks.
- 🗄️ **Repository Storage Pattern** – thread-safe SQLite with WAL mode locally, PostgreSQL in the cloud with multi-tenant isolation and Alembic migrations.
- 🚩 **Modular Feature Flags** – lightweight personal builds by default, dynamic flag gating for cloud sync, registry, and enterprise multi-tenancy.
- 💰 **Cost Optimization Discipline** – strict 90/9/1 token optimization rule (90% deterministic/cache/local, 9% mid-tier, 1% frontier) keeping execution budgets <8k tokens.
- 📱 **Omnichannel & Collaboration** – manage tasks via Telegram/WhatsApp and native team channels (Slack, Teams, Discord, Mattermost).

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Low‑Code Blueprints & Templates** | 12+ pre-built declarative skill templates (JSON) with instant auto-fill, AST verification, and dynamic DSPy signatures. |
| **Multi‑Provider Router** | Auto‑selects from Ollama, llama.cpp, Gemini, OpenAI, Anthropic, DeepSeek, Groq, or Kimi with intelligent fallback. |
| **Security Auditing Sentry** | 3‑stage pipeline: *SecurityAuditor* → *CodeLinter* → *CodeFixer*. Catches SQL injection, XSS, hardcoded secrets, and style violations. |
| **Infinite‑Loop Breaker** | Prevents recursive auto‑editing by locking files after 3 changes in 15 seconds. |
| **Vector Memory** | Ingest API docs, READMEs, and coding guidelines into ChromaDB for semantic search. |
| **Hardware Telemetry** | Real‑time RAM, CPU, and (optional) NVIDIA VRAM usage graphs in the dashboard and sidecar API. |
| **Interactive DSPy Sandbox** | Streamlit-based sandbox with 1-click AST auto-repair for naked returns and secure execution. |
| **Storage Repository Pattern** | Abstract storage layer supporting local SQLite (WAL) and enterprise PostgreSQL with migrations. |
| **Feature Flag System** | Configurable via environment variables and runtime admin endpoints (`/v1/flags`). |
| **Encrypted Git Backups** | Daily automated commits of encrypted SQLite databases and financial ledgers via Fernet AES-256. |

---

## 🏗️ System Architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                          AGENT ENGINE (Tauri Shell)                      │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  │
│  │  Kimi-Style Chat   │  │  Control Dashboard │  │  Settings & Auth   │  │
│  │  (React/TS)        │  │  (React/TS)        │  │  (React/TS)        │  │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘  │
│                              │                                           │
│                    Local HTTP / JSON-RPC (Tauri IPC)                     │
│                              │                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │               PYTHON SIDECAR (FastAPI + FastMCP + ACP)             │  │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐          │  │
│  │  │  Agent    │ │ Workflow  │ │  Skill    │ │  Safety   │          │  │
│  │  │ Registry  │ │  Engine   │ │ Registry  │ │  Engine   │          │  │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘          │  │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐          │  │
│  │  │  DSPy     │ │  Model    │ │  Memory   │ │  Cost     │          │  │
│  │  │  Pipelines│ │  Router   │ │ (Chroma)  │ │  Tracker  │          │  │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘          │  │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐          │  │
│  │  │  File     │ │  Backup & │ │  Bench-   │ │  MCP/ACP  │          │  │
│  │  │  Watcher  │ │ Encryption│ │  mark     │ │  Servers  │          │  │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘          │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                    AGENT ADAPTER LAYER                             │  │
│  │  Claude Code │ Codex │ OpenClaw │ Goose │ Hermes │ Cursor │ Windsurf│  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                STORAGE (Repository Pattern)                        │  │
│  │  SQLite (local) ──or── PostgreSQL (cloud/multi-tenant)             │  │
│  │  ChromaDB (vectors) │ AES-256 encrypted files │ Git (backups)      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Monorepo Directory Structure

```text
agent_engine/
├── apps/
│   └── desktop/               # Tauri v2 shell (Rust) + React/TypeScript UI
├── services/
│   └── python/                # Python sidecar service (FastAPI + FastMCP + ACP)
├── packages/
│   ├── shared-schema/         # OpenAPI 3.1 contract & SSE JSON Schema
│   ├── sdk-js/                # TypeScript client library
│   └── sdk-python/            # Python client library & agent packager
├── core/                      # Core engine, router, storage repository, memory, config
│   ├── config/                # Feature flags and environment settings
│   ├── context/               # Token budget builder & context truncation
│   ├── router/                # Model router and execution router (90/9/1 rule)
│   ├── storage/               # Abstract storage, SQLite (WAL), and PostgreSQL backends
│   ├── engine.py              # Dynamic signature and agent compiler
│   └── templates.py           # Skill template schema and CRUD engine
├── configs/                   # Templates catalog and provider configs
│   └── templates/             # 12+ pre-built JSON skill templates
├── server/                    # FastMCP server, watcher daemon, and Streamlit dashboard
├── skills/                    # Discovered & omnichannel skill adapters
├── tests/                     # Test suite (pytest: unit, contract, integration)
├── docs/                      # Architecture docs, ADRs, cost guide, and master ROADMAP.md
│   ├── ADR/                   # Architecture Decision Records (ADR-001 - ADR-015)
│   ├── COST_OPTIMIZATION_GUIDE.md  # 90/9/1 cost optimization principles
│   └── ROADMAP.md             # Master milestone and task tracker
├── infra/                     # Sidecar builds, packaging, and cloud manifests
├── alembic/                   # Alembic database schema migrations
├── Makefile                   # Root build, bootstrap, test & verification automation
├── pyproject.toml             # Root uv workspace configuration
├── pnpm-workspace.yaml        # JS/TS workspace configuration
└── main.py                    # Master CLI entrypoint
```

---

## 🚀 Quickstart & Developer Workflow

### 1. Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ and `pnpm` (for desktop UI / JS SDK)
- Rust and Cargo (for Tauri desktop shell)

### 2. Bootstrap Environment
```bash
make bootstrap
```
Initializes the Python virtual environment via `uv`, verifies workspace dependencies, and checks for Node/pnpm and Cargo toolchains.

### 3. Run Verification & Tests
```bash
make verify
```
Runs code linting (`ruff check`) and the full test suite (`pytest`), ensuring 100% of unit, contract, and integration tests pass.

```bash
make test
```
Runs all pytest test suites directly (`.venv/bin/pytest tests/ -v`).

### 4. Code Formatting
```bash
make format
```
Formats all Python files using `ruff format`.

---

## 💻 Master CLI & Servers

| Command | Purpose |
|---|---|
| `.venv/bin/python main.py status` | Check model router health and local providers |
| `.venv/bin/python main.py dashboard` | Launch Streamlit control center (`http://localhost:8501`) |
| `.venv/bin/python main.py watch` | Start Code Sentry filesystem watcher |
| `.venv/bin/python main.py staged` | List pending staged patches in storage repository |
| `.venv/bin/python main.py apply <id>` | Apply a staged patch to disk |
| `.venv/bin/python main.py mcp` | Launch FastMCP server over stdio for IDEs |
| `.venv/bin/python main.py run --config <path> --input <query>` | Run a one-off agent blueprint |

---

## 🔌 IDE Integration (VS Code / Cursor)

Add to your MCP configuration (e.g., `claude_desktop_config.json` or Goose extension config):
```json
{
  "mcpServers": {
    "agent-engine": {
      "command": "uv",
      "args": ["run", "server/mcp_server.py"],
      "cwd": "/path/to/agent_engine"
    }
  }
}
```

Exposed MCP Tools:
- `analyze_and_fix_code`: Audit and patch a source file with safety verification.
- `query_agent_memory`: Semantic search over ingested RAG vector docs.
- `list_staged_patches`: List pending staged fixes in repository.
- `get_system_telemetry`: Real-time CPU, RAM, and GPU statistics.
- `list_skill_templates`: Discover pre-built declarative skill templates.
- `get_skill_template`: Inspect blueprint details for an agent template.
- `execute_skill_template`: Instantiate and run a template with user inputs.

---

## 📡 Local API Contract

The communication contract between the desktop shell and the Python sidecar is defined under [`packages/shared-schema/`](file:///home/nadir/agent_engine/packages/shared-schema):
- [`packages/shared-schema/openapi.yaml`](file:///home/nadir/agent_engine/packages/shared-schema/openapi.yaml): OpenAPI 3.1.0 specification for `/v1/...` REST endpoints.
- [`packages/shared-schema/events.schema.json`](file:///home/nadir/agent_engine/packages/shared-schema/events.schema.json): Schema for streaming SSE events (`token`, `tool_call`, `approval_request`, `patch_staged`, `cost_update`, `agent_status`).

---

## 🔧 Configuration Reference

Key environment variables (`.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `STORAGE_BACKEND` | Storage backend (`sqlite` or `postgres`) | `sqlite` |
| `DATABASE_URL` | PostgreSQL connection string (when `postgres` selected) | `None` |
| `TENANT_MODE` | Multi-tenancy mode (`single` or `multi`) | `single` |
| `FEATURE_ENABLE_DESKTOP_UI` | Enable desktop Tauri frontend | `true` |
| `FEATURE_ENABLE_CLOUD_SYNC` | Enable cloud database sync | `false` |
| `FEATURE_ENABLE_REGISTRY` | Enable community package registry | `false` |
| `FEATURE_ENABLE_ACP` | Enable Agent Client Protocol | `false` |
| `FEATURE_ENABLE_ENTERPRISE_RBAC` | Enable enterprise RBAC policies | `false` |
| `PROVIDER_PRIORITY` | Comma‑separated provider order | `ollama,llamacpp,gemini,openai,...` |
| `LOCAL_MODEL_NAME` | Model name for llama.cpp / Ollama | `qwen2.5-coder-3b-instruct-q4_k_m` |
| `LLAMACPP_HOST` | llama.cpp server URL | `http://localhost:8080/v1` |
| `DEFAULT_MAX_TOKENS` | Default context limit | `4096` |
| `REQUEST_TIMEOUT` | Health‑check timeout (sec) | `5` |
| `AES_MASTER_KEY` | Fernet key for encrypted backups | (required for backups) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | (optional) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | Cloud API keys | (optional) |

---

## 🗺️ Implementation Roadmap

Track progress across all milestones and phases in [`docs/ROADMAP.md`](file:///home/nadir/agent_engine/docs/ROADMAP.md).  
Architectural conflict resolutions and guidelines are documented in [`docs/ADR/README.md`](file:///home/nadir/agent_engine/docs/ADR/README.md).

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 🛠️ Built With

- [Tauri](https://tauri.app/) – Lightweight, memory-efficient cross-platform desktop shell.
- [FastAPI](https://fastapi.tiangolo.com/) – High-performance async Python sidecar server.
- [DSPy](https://dspy.ai/) – Programming foundation models, not prompt engineering.
- [ChromaDB](https://www.trychroma.com/) – Open‑source vector database for semantic memory.
- [FastMCP](https://github.com/jlowin/fastmcp) – Model Context Protocol server.
- [Streamlit](https://streamlit.io/) – Python interactive web UI and testing sandbox.
- [SQLAlchemy & Alembic](https://www.sqlalchemy.org/) – Abstract database repository and schema migrations.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) & [Ollama](https://ollama.ai/) – Efficient local inference.
