# 🚀 Agent Engine – Autonomous Local-First AI Operations Studio

**v1.0.0** · DSPy + ChromaDB + FastMCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![DSPy](https://img.shields.io/badge/DSPy-0.5+-green.svg)](https://dspy.ai/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 Overview

**Agent Engine** is a **production‑ready, self‑contained AI agent platform** that runs entirely on your local machine. It combines:

- 🧠 **Dynamic Agent Compilation** – build low‑code AI agents using DSPy signatures, no prompt engineering required.
- 🛡️ **Autonomous Code Sentry** – a file‑watcher that audits Python code for security vulnerabilities and PEP‑8 style issues, automatically staging or applying fixes.
- 📚 **Persistent RAG Memory** – ChromaDB vector store for long‑term knowledge retrieval.
- 🔌 **IDE Integration** – expose 7+ agent tools to VS Code, Cursor, Goose AI via the Model Context Protocol (MCP).
- 📊 **Streamlit Control Center** – web dashboard with hardware telemetry, memory search, and performance benchmarks.
- 📱 **Omnichannel** – manage tasks via Telegram/WhatsApp through OpenClaw skills.
- 🔐 **Encrypted Backups** – AES‑256 encrypted daily Git snapshots protect your code and financial logs.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Low‑Code Blueprints** | Define agents by declaring inputs, outputs, and reasoning style (CoT / ReAct) – no boilerplate. |
| **Multi‑Provider Router** | Auto‑selects from Ollama, llama.cpp, Gemini, OpenAI, Anthropic, DeepSeek, Groq, or Kimi with intelligent fallback. |
| **Security Auditing** | 3‑stage pipeline: *SecurityAuditor* → *CodeLinter* → *CodeFixer*. Catches SQL injection, XSS, hardcoded secrets, and style violations. |
| **Infinite‑Loop Breaker** | Prevents recursive auto‑editing by locking files after 3 changes in 15 seconds. |
| **Vector Memory** | Ingest API docs, READMEs, and coding guidelines into ChromaDB for semantic search. |
| **Hardware Telemetry** | Real‑time RAM, CPU, and (optional) NVIDIA VRAM usage graphs in the dashboard sidebar. |
| **Performance Benchmarks** | One‑click synthetic coding challenges measure local model speed (tok/s) and latency. |
| **Telegram Approvals** | Receive interactive Approve/Reject buttons on your phone before patches are applied. |
| **Encrypted Git Backups** | Daily automated commits of encrypted SQLite databases and financial ledgers. |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INTERFACE LAYER                             │
├──────────────────────┬──────────────────────┬─────────────────────┤
│  VS Code / Cursor    │   Zed IDE            │   Streamlit UI      │
│  (MCP stdio)         │   (ACP)              │   (Port 8501)       │
└──────────┬───────────┴──────────┬───────────┴──────────┬──────────┘
           │                      │                      │
           ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FAST MCP SERVER                                │
│                   (server/mcp_server.py)                            │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         CORE ENGINE                                  │
│                      (core/engine.py)                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  DynamicSignatureBuilder → LowCodeAgent → AgentPipeline      │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬───────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────┐
│  MODEL ROUTER   │ │  RAG / MEMORY   │ │  HARNESS ENGINEERING    │
│ (core/router.py)│ │ (core/memory.py)│ │   (core/harness.py)     │
└─────────────────┘ └─────────────────┘ └─────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA & STORAGE                               │
├──────────────────────┬──────────────────────┬─────────────────────┤
│  SQLite              │  ChromaDB            │  File System        │
│  (audit_sentry.db)   │  (vector indices)    │  (.agent_history/)  │
└──────────────────────┴──────────────────────┴─────────────────────┘
```

---

## 📦 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/TechnoVen/agent-engine.git
cd agent-engine
```

### 2. Set Up Python Environment
```bash
# Using uv (recommended)
uv venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# Or using pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Download a Local Model
The default model is **Qwen 2.5 Coder 3B** (Q4_K_M, ~1.9 GB). Download it using the HF mirror:
```bash
mkdir -p models
wget -O models/qwen2.5-coder-3b-instruct-q4_k_m.gguf \
'https://hf-mirror.com/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf'
```

### 4. Configure Environment
Copy the example environment file and add your API keys (optional – local models work out of the box):
```bash
cp .env.example .env
nano .env
```

```ini
# Minimal .env – local only
LOCAL_MODEL_NAME="qwen2.5-coder-3b-instruct-q4_k_m"
LLAMACPP_HOST="http://localhost:8080/v1"

# For cloud fallback (optional)
GEMINI_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
# ... other keys
```

### 5. (Optional) Install Pre-commit Hooks
```bash
pre-commit install
```

---

## 🚀 Usage

### Launch the Complete Studio
```bash
chmod +x start_studio.sh
./start_studio.sh
```
This starts four background services:
- **llama‑server** – local model inference on port 8080
- **Gateway** – Telegram webhook listener on port 8000
- **Sentry Watcher** – filesystem security daemon
- **Streamlit Dashboard** – web UI on port 8501

Press `Ctrl+C` to gracefully stop all services.

### Web Dashboard
Open your browser: **http://localhost:8501**

| Tab | Function |
|-----|----------|
| 🛡️ **Sentry & Patches** | Review staged code fixes, see before/after diffs, apply/reject patches. |
| 🧠 **Dynamic Agent Studio** | Build custom agents visually – declare inputs, outputs, and reasoning style. |
| 📚 **RAG Vector Memory** | Ingest and search documentation, code rules, or API references. |
| ⚡ **Speedometer** | Run synthetic benchmarks to measure your local model’s tok/s performance. |

### IDE Integration (VS Code / Cursor)
Add to your MCP configuration (e.g., `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "agent-engine": {
      "command": "uv",
      "args": ["run", "server/mcp_server.py"],
      "cwd": "/home/nadir/agent_engine"
    }
  }
}
```
Then use these tools in chat:
- `analyze_and_fix_code` – audit and patch a file.
- `query_agent_memory` – semantic search over ingested docs.
- `list_staged_patches` – show pending fixes.

### CLI Usage
```bash
# Run a one‑off agent blueprint
python main.py run --config configs/my_agent.yaml --input "My task"

# Start the file watcher (stage only)
python main.py watch

# Start the file watcher with auto‑apply
python main.py watch --auto-apply

# Show system status
python main.py status
```

---

## 📁 Project Structure

```
agent_engine/
├── core/                     # Core agent mechanics
│   ├── engine.py             # Dynamic blueprint compiler
│   ├── router.py             # Multi‑provider model router
│   ├── models.py             # Model factory with fallback
│   ├── memory.py             # ChromaDB vector memory
│   ├── harness.py            # DSPy optimization harness
│   └── logger.py             # Audit logging
├── server/                   # Interfaces & daemons
│   ├── dashboard.py          # Streamlit control center
│   ├── mcp_server.py         # FastMCP stdio server (7 tools)
│   ├── watcher.py            # Security sentry daemon
│   ├── gateway.py            # Telegram webhook listener
│   └── tunnel.py             # ngrok tunnel wrapper
├── tools/                    # Utility scripts
│   ├── benchmark_engine.py   # Performance benchmarker
│   ├── rollback_recovery.py  # Database rollback
│   ├── decrypt_verify.py     # AES‑256 decryption
│   └── clean_retention.py    # Snapshot purger
├── skills/                   # OpenClaw skills
│   ├── creative_writer_skill.py
│   ├── email_agent_skill.py
│   ├── finance_ledger_skill.py
│   └── dspy_bridge_skill.py
├── data/                     # Persistent storage
│   ├── audit_sentry.db       # SQLite audit database
│   └── chroma/               # ChromaDB indices
├── models/                   # Local GGUF model cache
├── configs/                  # MCP & Goose configs
├── tests/                    # Pytest test suite
├── start_studio.sh           # Unified launcher
├── main.py                   # CLI entrypoint
└── .env                      # Environment configuration
```

---

## 🔧 Configuration Reference

Key environment variables (`.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `PROVIDER_PRIORITY` | Comma‑separated provider order | `ollama,llamacpp,gemini,openai,...` |
| `LOCAL_MODEL_NAME` | Model name for llama.cpp | `qwen2.5-coder-3b-instruct-q4_k_m` |
| `LLAMACPP_HOST` | llama.cpp server URL | `http://localhost:8080/v1` |
| `DEFAULT_MAX_TOKENS` | Default context limit | `4096` |
| `REQUEST_TIMEOUT` | Health‑check timeout (sec) | `5` |
| `AES_MASTER_KEY` | Fernet key for encrypted backups | (required for backups) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | (optional) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / etc. | Cloud API keys | (optional) |

---

## 🧪 Testing

Run the full test suite:
```bash
pytest tests/ -v
```

All 12+ tests pass, covering:
- Dynamic signature building
- MCP tool discovery
- Watcher ignore rules and loop‑breaker logic

---

## 🤝 Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/amazing`).
3. Commit your changes (`git commit -m 'Add amazing feature'`).
4. Push to the branch (`git push origin feature/amazing`).
5. Open a Pull Request.

Please ensure Ruff linting passes:
```bash
ruff check --fix .
ruff format .
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 🛠️ Built With

- [DSPy](https://dspy.ai/) – Programming, not prompting.
- [ChromaDB](https://www.trychroma.com/) – Open‑source vector database.
- [FastMCP](https://github.com/jlowin/fastmcp) – MCP server wrapper.
- [Streamlit](https://streamlit.io/) – Python web UI.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) – Efficient local inference.
- [Watchdog](https://pythonhosted.org/watchdog/) – Filesystem monitoring.
- [OpenClaw](https://openclaw.ai/) – Omnichannel AI assistant framework.

---

## ⭐ Acknowledgments

Built as a local‑first, privacy‑focused alternative to cloud‑based agent platforms. Special thanks to the open‑source communities behind all the tools that made this possible.
