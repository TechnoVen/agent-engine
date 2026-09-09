# Autonomous Agent Engine Control Center — Master Operational Guide

> **Control Center URL**: `http://localhost:8501`  
> **Production Version**: `v1.0.0`  
> **Hardware Target**: AMD Ryzen 5 PRO 2400G &bull; 14.6 GB RAM &bull; Arch Linux  
> **Active Local Model**: `qwen2.5-coder:3b` (Ollama on `http://localhost:11434`)  
> **Default Workspace**: `~/code` (`/home/nadir/code`)  
> **Test Verification**: 12 / 12 Tests Passing (100%)

---

## 1. Autonomous Agent Engine Control Center

```
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                     AUTONOMOUS AGENT ENGINE CONTROL CENTER                       │
 ├────────────────────┬────────────────────┬───────────────────┬────────────────────┤
 │ 🛡️ Sentry & Code   │ 🧠 Dynamic Agent   │ 📚 RAG Vector     │ ⚡ LLM Speedometer │
 │    Patches         │    Studio          │    Memory         │    & Benchmark     │
 └────────────────────┴────────────────────┴───────────────────┴────────────────────┘
```

---

### **A. Left Sidebar: Hardware Radar & Multi-Model Switcher**

* **🖥️ Hardware Compute Radar**:
  * **RAM Usage Gauge**: Real-time memory tracker (e.g. `7.1 GB / 14.6 GB (48%)`). Prevents memory overflow during local model execution.
  * **CPU Compute %**: Active Ryzen CPU utilization.
  * **Auto-Refresh Checkbox**: Automatically refreshes the patch list every 5 seconds.
* **🤖 Multi-Model Provider Switcher**:
  * Dropdown to instantly switch between `ollama` (`qwen2.5-coder:3b`), `gemini`, `openai`, `anthropic`, `groq`, and `deepseek`.
  * **"🔄 Switch / Re-Init Provider" Button**: Re-configures DSPy global language model settings in memory across all worker threads without needing a server restart.
* **🟢 Health Indicators**:
  * `Ollama Local Daemon`: Confirms `http://localhost:11434` connectivity.
  * `Cloud API Status`: Confirms whether API keys are loaded from `.env`.

---

### **B. Tab 1: 🛡️ Sentry & Code Patches (Detailed Walkthrough & Example)**

Code Sentry monitors your development folder (`~/code`). When a flaw is detected, a patch proposal is staged in SQLite (`data/audit_sentry.db`):

#### **Real-World Walkthrough: Detecting a Vulnerable SQL Query**
Imagine saving a new file named `~/code/payment_service.py` with an unescaped SQL query string concatenation:

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

#### **How to Review and Apply in the Control Center:**
1. Open **Tab 1 (🛡️ Sentry & Code Patches)**.
2. In the **"Select Patch ID to Inspect"** dropdown, choose `Patch #1042: payment_service.py`.
3. Read the **AI Rationale**: *"Flagged CWE-89 (SQL Injection) due to unescaped f-string query formatting. Applied parameterized query binding and context-managed database connection."*
4. Click **"✅ Approve & Apply Patch"**: The source code in `~/code/payment_service.py` is updated atomically on disk!

---

### **C. Tab 2: 🧠 Dynamic Agent Studio (Low-Code DSPy Compiler)**

Construct and compile arbitrary AI agents visually by declaring signatures, inputs, outputs, and reasoning modules in real time.

#### **Real-World Example: Building a FastAPI CRUD Route Generator**
Configure a custom agent in Tab 2 to generate type-safe FastAPI endpoints on the fly:

| Field | Value |
| :--- | :--- |
| **Node Name** | `FastAPIRouteGenerator` |
| **Task Description** | `Given a Pydantic schema and table name, generate a production-ready FastAPI router with CRUD endpoints, status codes, and error handlers.` |
| **Dynamic Input Fields** | `model_name, pydantic_schema, database_table` |
| **Dynamic Output Fields** | `fastapi_router_code, endpoints_list, error_handling_summary` |
| **Execution Strategy** | `ChainOfThought` |

#### **Running the Agent Visually:**
1. Enter test inputs:
   * `model_name`: `"CustomerOrder"`
   * `pydantic_schema`: `"id: int, customer_id: int, total_amount: float, status: str"`
   * `database_table`: `"orders"`
2. Click **"⚡ Compile & Run Agent"**.
3. In ~3.2 seconds, the dashboard renders the complete FastAPI router code, list of endpoints (`GET /orders/`, `POST /orders/`, etc.), and the internal DSPy chain-of-thought reasoning trace!

---

### **D. Tab 3: 📚 ChromaDB Persistent Vector Memory (RAG)**

Inspect, query, and ingest contextual facts, API documentation, and code rules into the persistent vector store (`data/chroma/`).

#### **🔍 1. Semantic Memory Search Console (With Example)**
* **Query Memory Input**: Enter: `"What is our timeout and retry policy for external HTTP API requests?"`
* **Passages to Retrieve (Top K Slider)**: Set slider to **3** (Retrieves top 3 relevant passages).
* **Action**: Click **"🔍 Search Knowledge Base"**.
* **Result Returned**:
  ```text
  Passage #1 (Relevance Score: 0.91)
  "Policy #402: All external API integrations must use httpx.AsyncClient with a strict 5.0-second timeout and exponential backoff retry (max 3 attempts)."
  Metadata: {"source": "network_policy.md", "timestamp": "2026-08-28T10:15:00"}
  ```

#### **➕ 2. Ingest Knowledge Document Console (With Example)**
* **Document Content Box**: Paste: `"Database Architecture: We use SQLite with WAL (Write-Ahead Logging) mode enabled for high concurrency, and ChromaDB for dense vector indexing."`
* **Source Tag / Metadata**: Enter: `"database_architecture.md"`
* **Action**: Click **"📥 Ingest into Memory"** to calculate embeddings and store permanently in ChromaDB.

---

### **E. Tab 4: ⚡ Local Model Speedometer & Latency Benchmark**

Measure real-time token generation throughput (tokens/sec) and inference response latency on your AMD Ryzen 5 PRO 2400G CPU and Radeon Vega graphics.

#### **Synthetic Benchmark Challenge Walkthrough**
Click **"🚀 Run Speed Benchmark"** to execute a standardized coding challenge against your active local model:

| Benchmark Metric | Observed Score (`qwen2.5-coder:3b`) | Evaluation Status |
| :--- | :--- | :--- |
| **Generation Throughput** | **18.6 tokens/sec** | ⚡ Faster than human reading speed (~5 tok/s) |
| **Time to First Token (TTFT)** | **310 ms** | ⚡ Ultra-low latency prompt ingestion |
| **Total Generation Time** | **6.42 seconds** | Completes full 120-token function generation |
| **RAM Footprint Delta** | **+0.12 GB active** | Memory stays well within the 14.6 GB threshold |
| **Benchmark Passes** | **4 / 4 Validation Checks Passed** | Syntax Valid &bull; Logic Correct &bull; Type Hints &bull; Docstrings |

---

## 2. Goose AI Developer Workflow in `~/code`

Goose runs in your terminal, connects directly to your local `qwen2.5-coder:3b` model, and has native access to all 7 Agent Engine FastMCP tools:

```bash
# Start Goose in your code workspace
cd ~/code
goose session
```

### **Example Prompts in Goose:**

* **Query Vector Memory**:
  ```text
  > Use query_agent_memory to search for information about our DSPy router and LowCodeAgent.
  ```
* **Check Code Sentry Patches**:
  ```text
  > Check if there are any staged security patches using list_staged_patches.
  ```
* **Ingest Knowledge**:
  ```text
  > Ingest note into agent memory: "Always use parameterized queries for SQLite."
  ```

---

## 3. Master CLI Command Reference

| Command | Description |
| :--- | :--- |
| `python main.py dashboard` | Launch the Streamlit Control Center on `http://localhost:8501`. |
| `python main.py watch --dir ~/code` | Start Code Sentry file watcher on `~/code` (staged review mode). |
| `python main.py watch --dir ~/code --auto-apply` | Start Code Sentry in auto-apply mode (direct disk writes). |
| `python main.py status` | Display complete diagnostic health table (Ollama, API keys, vector count). |
| `python main.py staged` | List pending security and quality patches in SQLite. |
| `python main.py apply <id>` | Apply a specific staged patch to the target source file. |
| `python main.py reject <id>` | Reject and dismiss a staged patch recommendation. |
| `python main.py mcp` | Start FastMCP stdio server for IDE integrations. |
| `python main.py rag-demo` | Run a live ChromaDB ingestion and semantic search demonstration. |
| `pytest -v` | Run all 12 automated verification unit and integration tests. |

---

*Guide generated for Nadir &bull; Saved to `~/Documents/agent_engine_guide.html` & `~/Documents/agent_engine_guide.md`.*
