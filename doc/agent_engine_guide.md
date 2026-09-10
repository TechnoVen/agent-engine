# Autonomous Agent Engine Control Center — Master Operational Guide

> **Control Center URL**: `http://localhost:8501`  
> **Production Version**: `v1.0.0`  
> **Hardware Target**: AMD Ryzen 5 PRO 2400G &bull; 14.6 GB RAM &bull; Arch Linux  
> **Active Local Engines**: `llama-server` (Port 8080) & Ollama (Port 11434)  
> **Default Workspace**: `~/code` (`/home/nadir/code`)  
> **Test Verification**: 24 / 24 Tests Passing (100%)

---

## 🚀 Beginner Quick-Start: 3-Minute Zero-to-Hero Tutorial

Welcome! If you are new to the Agent Engine, here is the basic concept in plain English:

* **What is it?** It is a local AI control center that lets you create, test, and run autonomous AI assistants without writing complex code.
* **Where does it run?** 100% locally on your machine using your local LLM (Qwen2.5-Coder-3B via llama-server / Ollama) or optional cloud APIs (Gemini, OpenAI, Anthropic).
* **How do you start it?**
  ```bash
  cd ~/agent_engine
  ./start_studio.sh
  ```
  Then open your browser to **`http://localhost:8501`**.

```
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                     AUTONOMOUS AGENT ENGINE CONTROL CENTER                       │
 ├────────────────────┬────────────────────┬───────────────────┬────────────────────┤
 │ 🛡️ Sentry & Code   │ 🧠 Dynamic Agent   │ 📚 RAG Vector     │ ⚡ LLM Speedometer │
 │    Patches         │    Studio & Skills │    Memory         │    & Sandbox       │
 └────────────────────┴────────────────────┴───────────────────┴────────────────────┘
```

---

## 🧭 Visual Tour of the Control Center

### **A. Left Sidebar: Hardware Radar & Model Switcher**

* **🖥️ Hardware Compute Radar**:
  * **RAM Usage**: Tracks live system memory (e.g., `8.2 GB / 14.6 GB (56%)`). Keeps local models safe from running out of memory.
  * **CPU Compute %**: Monitors active CPU load.
* **🤖 Active LLM Backend Router**:
  * Shows live health badges for **Ollama Daemon** (Port 11434) and **llama.cpp** (Port 8080).
  * **Provider Switcher**: Switch on the fly between `ollama`, `llamacpp`, `gemini`, `openai`, `anthropic`, `groq`, `deepseek`, or `kimi`.
  * **"Switch / Re-Init Provider" Button**: Re-configures DSPy in memory across all worker threads without needing to restart the server.
  * **Context Window Slider**: Choose your context length (e.g., `4,096`, `8,192`, or `16,384` tokens).
  * **⚡ Bypass DSPy Cache Toggle**: Turn cache on for instant re-runs, or off to benchmark raw local hardware speed.

---

### **B. Tab 1: 🛡️ Code Sentry & Patches**

Code Sentry monitors your development folder (`~/code`). Whenever a security flaw (like SQL injection or hardcoded secrets) or style bug is detected, it automatically creates a safe, staged patch proposal in SQLite (`data/audit_sentry.db`):

#### **Real-World Walkthrough: Detecting a Vulnerable SQL Query**
Suppose you write a database query with string concatenation:

```diff
- def fetch_user_balance(user_id):
-     conn = sqlite3.connect("bank.db")
-     cursor = conn.cursor()
-     cursor.execute(f"SELECT balance FROM accounts WHERE user_id = '{user_id}'")  # Vulnerable!
-     return cursor.fetchone()
--- SENTRY 3-TIER SUB-AGENT AUDIT & PATCH PROPOSAL ---
+ def fetch_user_balance(user_id: str) -> Optional[float]:
+     """Retrieve user balance using parameterized SQL query with resource cleanup."""
+     with sqlite3.connect("bank.db") as conn:
+         cursor = conn.cursor()
+         cursor.execute("SELECT balance FROM accounts WHERE user_id = ?", (user_id,))
+         row = cursor.fetchone()
+         return row[0] if row else None
```

#### **How to Review and Apply in 2 Clicks:**
1. Open **Tab 1 (🛡️ Sentry & Code Patches)**.
2. Read the **Audit Finding** and inspect the side-by-side **Original vs Proposed Fix** diff.
3. Click **"✅ Approve & Apply"**: The file is safely updated directly on disk!

---

### **C. Tab 2: 🧠 Dynamic Agent Studio & OpenClaw Skill Templates**

This tab allows anyone—even non-coders—to create, test, import, and export custom AI workflows without writing Python code.

#### **What is a Skill Template? (Explain Like I'm 5)**
Think of a **Skill Template** like a recipe card:
* **Inputs**: The ingredients you give the AI (e.g., meeting notes, tickets, plain English questions).
* **Outputs**: The final dish you want back (e.g., executive summary, action items, SQL queries).
* **Reasoning**: How the AI thinks (`cot` for Step-by-Step Chain of Thought, `predict` for direct response, `react` for tool usage).

Instead of writing a 100-line Python script, you define the recipe in a clean JSON file in `configs/templates/`.

---

#### **Pre-Built 12-Template Library (Ready to Use)**

| Name | Description | Inputs | Outputs | Reasoning |
| :--- | :--- | :--- | :--- | :--- |
| **Generate SQL from Natural Language** | Convert business questions into precise SQL queries with schema grounding. | `natural_language_query`, `database_schema`, `sql_dialect` | `sql_query`, `explanation` | Chain of Thought (`cot`) |
| **Summarize Meeting Notes** | Condense meeting transcripts into bullet points and action items. | `transcript`, `focus_areas` | `summary`, `action_items` | Chain of Thought (`cot`) |
| **Draft Weekly Report** | Generate a structured weekly update from tasks and achievements. | `tasks_done`, `blockers`, `next_week_plans` | `report` | Chain of Thought (`cot`) |
| **Extract Key Points from Document** | Identify core arguments and facts from long text. | `document_text`, `max_points` | `key_points`, `themes` | Chain of Thought (`cot`) |
| **Convert Markdown to HTML** | Transform Markdown content into clean HTML. | `markdown_content`, `style_preference` | `html_output` | Direct Predict (`predict`) |
| **Generate Python Unit Tests** | Write `pytest` test cases for a given function. | `function_code`, `test_framework` | `test_code` | Chain of Thought (`cot`) |
| **Explain Code** | Provide a line‑by‑line explanation of any code snippet. | `code_snippet`, `language` | `explanation` | Chain of Thought (`cot`) |
| **Translate Code to Another Language** | Convert code from one programming language to another. | `source_code`, `source_lang`, `target_lang` | `translated_code` | ReAct with Tools (`react`) |
| **Generate API Endpoint from Specification** | Create a FastAPI endpoint stub from an OpenAPI spec. | `spec_description`, `path`, `method` | `endpoint_code`, `documentation` | Chain of Thought (`cot`) |
| **Create JSON Schema** | Derive a JSON schema from example data. | `sample_data`, `schema_name` | `json_schema` | Direct Predict (`predict`) |
| **Email Draft from Brief** | Write a professional email based on key points. | `recipient`, `tone`, `key_points` | `draft_email` | Chain of Thought (`cot`) |
| **Code Review Checklist** | Generate a security + style checklist for Python code. | `code`, `ruleset` | `checklist`, `score` | Chain of Thought (`cot`) |

---

#### **How to Run a Template in 3 Easy Steps:**

1. **Pick a Template / Workflow**: In Tab 2, click the **"Select Skill Template / Workflow"** dropdown and select any of the 12 templates (or choose `(Custom)`).
   * *Instant Auto-Fill*: Selecting a template immediately populates the Agent Name, Goal / Description, Inputs, Outputs, and Reasoning Style in the blueprint schema!
2. **Review / Customize Inputs**: In the right column under **"Execute Compiled Agent"**, review the pre-populated sample text or paste your own data.
   * *Context Meter*: The **Context Window Utilization** bar shows you exactly how much of your active context window (`4,096`, `8,192`, or `16,384` tokens) is being used.
3. **Run**: Click **"🚀 Compile & Run Blueprint"**.
   * In a few seconds, you'll see the structured JSON output with all generated fields!

---

#### **How to Export and Import Agent Blueprints:**
* **Export Blueprint**: Under the template selector, click **"📥 Export Blueprint"**:
  * Saves the current agent configuration as a cleanly formatted `.json` file (`<Agent_Name>.json`).
  * If the blueprint is empty or incomplete, the button remains disabled to prevent invalid exports.
* **Import Blueprint**: Under the template selector, drag and drop or browse to upload a `.json` file in **"📤 Import Blueprint (JSON)"**:
  * Restores the agent name, description, inputs, outputs, and reasoning style automatically into the form.

---

#### **How OpenClaw Bots Run Your Templates (No Python Code Needed):**
OpenClaw bots (Telegram, WhatsApp, Slack) or automation scripts can run any template in 3 lines:

```python
from core.templates import load_template_agent

# OpenClaw dynamically compiles the agent from JSON:
agent = load_template_agent("summarize_meeting_notes")
result = agent(
    meeting_notes="Sync: Bob will add DB index by Wednesday. Carol ships vector search Friday.",
    participants="Bob, Carol, Alice",
)

print(result.executive_summary)
print(result.action_items)
```

You can also run any template directly from your terminal:
```bash
# List all available skill templates
python skills/dspy_template_skill.py --list

# Run a template using its default sample data
python skills/dspy_template_skill.py --template summarize_meeting_notes

# Run with custom JSON inputs
python skills/dspy_template_skill.py --template generate_sql_from_nl --payload '{"natural_language_query": "Count orders per user in 2026", "database_schema": "orders(id, user_id, date)", "sql_dialect": "PostgreSQL"}'
```

---

### **D. Tab 3: 📚 ChromaDB Persistent Vector Memory (RAG)**

Store and retrieve documentation, architecture notes, and coding rules using dense vector search (`data/chroma/`).

* **🔍 Search Memory**:
  1. Enter: `"What is our timeout and retry policy for external HTTP API requests?"`
  2. Set **Top K** slider to `3`.
  3. Click **"🔍 Search Knowledge Base"** to see relevant passages ranked by similarity score.
* **➕ Ingest Knowledge**:
  1. Paste content: `"Database Architecture: We use SQLite with WAL mode for concurrency, and ChromaDB for dense vector indexing."`
  2. Enter tag: `"database_architecture.md"`
  3. Click **"📥 Ingest into Memory"**.

---

### **E. Tab 4: ⚡ LLM Speedometer & Interactive Sandbox**

Measure real-time token throughput (tok/s) on your local hardware and immediately run, edit, and test generated code in a safe sandbox.

#### **1. Running the Speedometer Benchmark:**
1. Select a challenge (e.g., `Algorithmic Data Optimization`, `FastAPI CRUD Endpoint Generator`).
2. Click **"🚀 Fire Synthetic Benchmark Challenge"**.
3. View the performance metrics:
   * **Total Latency** (e.g., `5.2s`)
   * **Estimated Tokens** (e.g., `210`)
   * **Generation Speed** (e.g., `18.5 tok/s`)
   * **Speed History Chart** (tracks your performance over time)

#### **2. Interactive Sandbox – Run the Generated Code:**
Right below the benchmark results is the **Interactive Sandbox**:
* **Automatic Clean Code**: The code area is pre-filled with clean, executable Python code. Markdown fences (` ```python `) and conversational text are automatically stripped away.
* **Run Code**: Click **"▶️ Run Code"** to execute the script in an isolated environment. The standard output appears below.
* **Built-in Helper Tools**:
  * **`🧹 Strip Backticks & Clean`**: Automatically strips any backticks or markdown fences pasted by mistake.
  * **`🔄 Reset to Solution`**: Restores the original generated benchmark solution.
  * **`🪄 Auto-Wrap in Function Definition`**: If a function definition header was missing or the code started with a naked `return`, this button appears automatically and wraps the code inside a valid function in 1 click!
* **Safe Builtins**: The sandbox includes all standard Python primitives (`isinstance`, `set`, `bool`, `round`, `all`, `any`, `math`, etc.) so standard code runs smoothly without unexpected `NameError` exceptions.

---

## 🛠️ FastMCP IDE Integration (VS Code / Cursor / Goose)

The Agent Engine exposes 9 FastMCP tools over standard I/O for IDEs and CLI agents:

| FastMCP Tool | Description |
| :--- | :--- |
| `list_skill_templates` | Discovers and catalogs all OpenClaw skill templates in `configs/templates/`. |
| `execute_skill_template` | Executes a skill template by ID with a JSON payload. |
| `execute_dynamic_blueprint`| Runs an arbitrary dynamic agent signature on the fly. |
| `analyze_and_fix_code` | Scans code for security vulnerabilities and produces a staged patch. |
| `list_staged_patches` | Lists all pending security and style patches in the database. |
| `apply_staged_patch_by_id` | Applies a staged patch directly to the source file on disk. |
| `query_agent_memory` | Semantic vector search over ChromaDB knowledge base. |
| `ingest_agent_memory` | Ingests new text documents into vector memory. |
| `get_system_telemetry` | Returns hardware consumption (RAM, CPU) and LLM backend status. |

---

## 💻 Master CLI Command Reference

| Task | Command |
| :--- | :--- |
| **Launch Entire Studio** | `./start_studio.sh` |
| **Launch Web Dashboard Only** | `python main.py dashboard` |
| **Start llama-server (Port 8080)**| `./start_llama_server.sh` |
| **Start Ollama (Port 11434)** | `./start_ollama.sh` |
| **List Skill Templates** | `python skills/dspy_template_skill.py --list` |
| **Run Skill Template via CLI** | `python skills/dspy_template_skill.py --template summarize_meeting_notes` |
| **Start Code Sentry Watcher** | `python main.py watch --dir ~/code` |
| **Check System Status** | `python main.py status` |
| **Start FastMCP Server** | `python main.py mcp` |
| **Run Complete Test Suite** | `pytest tests/ -v` |

---

## 🧪 Automated Testing & Verification

All 24 automated unit and integration tests pass with zero regressions:

```bash
$ pytest tests/ -v
============================== 24 passed in 5.84s ==============================
```

* Tests covered:
  * `tests/test_engine.py`: Dynamic signatures, LowCodeAgent CoT & ReAct, AgentPipeline, ChromaDB persistence.
  * `tests/test_mcp.py`: FastMCP tools registration, telemetry, memory lifecycle, patch management.
  * `tests/test_sandbox.py`: Markdown fence stripping, residual backtick cleanup, auto-repair of naked returns, sandboxed execution.
  * `tests/test_templates.py`: SkillTemplate schema, NodeConfig conversion, template discovery, CRUD operations, OpenClaw skill adapter, MCP execution.
  * `tests/test_watcher.py`: File watcher security scanner, SQLite patch staging, patch approve/reject lifecycle.
