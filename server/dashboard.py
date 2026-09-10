# server/dashboard.py
# Agent Engine Studio – Streamlit Control Center
# v1.0.0 | DSPy + ChromaDB + FastMCP

import ast
import builtins
import contextlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time

import dspy
import pandas as pd
import psutil
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Unlock thread restrictions across Streamlit re‑renders
try:
    type(dspy.settings)._ensure_configure_allowed = lambda self: None
except AttributeError:
    # If the attribute doesn't exist, just continue
    pass

from core.engine import LowCodeAgent, NodeConfig
from core.memory import AgentMemory
from core.router import ModelRouter
from server.watcher import (
    DB_PATH,
    apply_staged_patch,
    get_staged_patches,
    init_db,
    reject_staged_patch,
)


# ---------- Helpers for Code Extraction & Repair ----------
def extract_code_block(text: str) -> str:
    """
    Extracts clean, runnable Python code from text that may contain
    markdown code fences (```python ... ```), backticks, or conversational text.
    """
    if not text or not isinstance(text, str):
        return ""

    stripped = text.strip()

    # 1. Match code blocks with python/py language tag
    py_blocks = re.findall(r"```(?:python|py)\s*\n(.*?)\n```", stripped, re.DOTALL | re.IGNORECASE)
    if py_blocks:
        return "\n\n".join(b.strip() for b in py_blocks if b.strip())

    # 2. Match generic code blocks
    generic_blocks = re.findall(r"```\s*\n(.*?)\n```", stripped, re.DOTALL)
    if generic_blocks:
        return "\n\n".join(b.strip() for b in generic_blocks if b.strip())

    # 3. Match unclosed fence (e.g. ```python\ncode...)
    unclosed = re.search(r"```(?:python|py)?\s*\n(.*)", stripped, re.DOTALL | re.IGNORECASE)
    if unclosed:
        body = unclosed.group(1).rstrip()
        if body.endswith("```"):
            body = body[:-3].rstrip()
        return body

    # 4. Strip any solitary backtick fence lines
    lines = stripped.splitlines()
    clean_lines = [line for line in lines if not line.strip().startswith("```")]
    return "\n".join(clean_lines).strip()


def auto_repair_naked_return(code: str) -> str:
    """
    If code starts with a naked return statement (often caused by LLM output splitting),
    attempts to reconstruct a valid function header from example usage or variable names.
    """
    if not code:
        return code

    lines = code.splitlines()
    first_non_empty = next((l.strip() for l in lines if l.strip()), "")
    if first_non_empty.startswith("return "):
        # Look for a call pattern like: result = function_name(args)
        call_match = re.search(r"(\w+)\s*=\s*(\w+)\s*\((.*?)\)", code)
        if call_match:
            res_var, func_name, args = call_match.groups()
            func_lines = [f"def {func_name}({args}):"]

            # Separate function body lines from example lines
            example_idx = -1
            for i, line in enumerate(lines):
                if "example usage" in line.lower() or f"{res_var} = {func_name}" in line:
                    example_idx = i
                    break

            if example_idx > -1:
                func_body_lines = lines[:example_idx]
                example_lines = lines[example_idx:]
            else:
                func_body_lines = [lines[0]]
                example_lines = lines[1:]

            for f_line in func_body_lines:
                if f_line.strip():
                    func_lines.append("    " + f_line.strip())
                else:
                    func_lines.append("")

            repaired = "\n".join(func_lines) + "\n\n" + "\n".join(example_lines)
            return repaired
    return code


# ---------- Signature for Benchmark ----------
class BenchSig(dspy.Signature):
    """You are an expert Python engineer. Provide a complete, standalone, runnable Python script that solves the challenge. Include all necessary imports, function definitions, and a runnable example with print statements at the bottom. Return ONLY valid, executable Python code."""

    challenge: str = dspy.InputField(desc="The programming challenge to solve")
    solution: str = dspy.OutputField(
        desc="Complete, runnable Python code solution including full function definitions and example usage"
    )


# ---------- Page Configuration ----------
st.set_page_config(
    page_title="Autonomous Agent Engine Studio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- CUSTOM STYLING ----------
st.markdown(
    """
<style>
    /* Main title gradient */
    .main-title {
        font-size: 2.4rem;
        font-weight: 700;
        background: linear-gradient(135deg, #1E88E5, #42A5F5);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #B0BEC5;
        margin-bottom: 1.8rem;
    }
    /* Glass cards for metrics */
    .metric-card {
        background: rgba(255,255,255,0.04);
        backdrop-filter: blur(10px);
        border-radius: 12px;
        padding: 1.4rem 1rem;
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 8px 20px rgba(0,0,0,0.3);
        transition: 0.2s ease-in-out;
        text-align: center;
    }
    .metric-card:hover {
        border-color: #1E88E5;
        transform: translateY(-2px);
    }
    .metric-card .label {
        font-size: 0.88rem;
        color: #90A4AE;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.3rem;
    }
    .metric-card .value {
        font-size: 1.9rem;
        font-weight: 700;
        color: #FAFAFA;
    }
    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: 0.2s;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .stButton > button:hover {
        transform: scale(1.01);
        border-color: #1E88E5;
    }
    /* ---------- MODERN TABS STYLING ---------- */
    /* Tab list container – spacious and cleanly separated */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 2px solid rgba(255, 255, 255, 0.1);
        padding-bottom: 8px;
        margin-bottom: 1.2rem;
        padding-top: 4px;
    }

    /* Each tab – base button style with generous padding and card background */
    .stTabs [data-baseweb="tab"] {
        background-color: #1e222d !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-bottom: none !important;
        border-radius: 10px 10px 0 0 !important;
        padding: 0.75rem 1.8rem !important;
        margin: 0 !important;
        transition: all 0.25s ease-in-out !important;
        cursor: pointer !important;
        min-height: 48px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }

    /* Target inner text elements inside tab for maximum readability & padding */
    .stTabs [data-baseweb="tab"] p,
    .stTabs [data-baseweb="tab"] [data-testid="stMarkdownContainer"] p,
    .stTabs [data-baseweb="tab"] span {
        color: #cbd5e1 !important;
        font-weight: 500 !important;
        font-size: 0.98rem !important;
        line-height: 1.4 !important;
        letter-spacing: 0.3px !important;
        margin: 0 !important;
        padding: 2px 6px !important;
    }

    /* Hover effect for inactive tabs */
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #282f3f !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
        transform: translateY(-1px) !important;
    }

    .stTabs [data-baseweb="tab"]:hover p,
    .stTabs [data-baseweb="tab"]:hover [data-testid="stMarkdownContainer"] p,
    .stTabs [data-baseweb="tab"]:hover span {
        color: #f8fafc !important;
    }

    /* Active tab – high-contrast royal blue card with clear legible text */
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
        border: 1px solid #3b82f6 !important;
        border-bottom: 2px solid #60a5fa !important;
        box-shadow: 0 6px 16px rgba(37, 99, 235, 0.35) !important;
        transform: translateY(-2px) !important;
    }

    .stTabs [aria-selected="true"] p,
    .stTabs [aria-selected="true"] [data-testid="stMarkdownContainer"] p,
    .stTabs [aria-selected="true"] span {
        color: #ffffff !important;
        font-weight: 600 !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5) !important;
    }

    /* Tab content panel – clean card container */
    .stTabs [data-baseweb="tab-panel"] {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 0 12px 12px 12px;
        padding: 1.8rem 1.4rem;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-top: none;
        margin-top: 0.2rem;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
    }

    @media (max-width: 768px) {
        .stTabs [data-baseweb="tab"] {
            padding: 0.5rem 1rem !important;
        }
        .stTabs [data-baseweb="tab"] p {
            font-size: 0.85rem !important;
        }
    }
    /* Expanders */
    .streamlit-expanderHeader {
        background-color: #1a1d24;
        border-radius: 8px;
    }
    /* Code blocks */
    .stCodeBlock {
        border-radius: 8px;
        border: 1px solid #2D2F36;
    }
    /* Footer */
    .footer {
        margin-top: 3rem;
        text-align: center;
        font-size: 0.85rem;
        color: #64748b;
        border-top: 1px solid #1e293b;
        padding-top: 1.2rem;
        padding-bottom: 1rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Initialize core services
router = ModelRouter()


@st.cache_resource
def get_dashboard_memory():
    return AgentMemory()


memory = get_dashboard_memory()


# ---------- BENCHMARK HISTORY TABLE INIT ----------
def init_benchmark_history_table():
    """Create the benchmark_history table if it doesn't exist."""
    os.makedirs("data", exist_ok=True)  # Ensure data directory exists
    conn = sqlite3.connect("data/audit_sentry.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            provider TEXT,
            context_size INTEGER,
            challenge TEXT,
            latency_seconds REAL,
            tokens_per_second REAL,
            estimated_tokens INTEGER,
            cached INTEGER  -- 1 if cached, 0 if live hardware
        )
    """)
    conn.commit()
    conn.close()


init_benchmark_history_table()

# ---------- SIDEBAR: HARDWARE & TELEMETRY ----------
st.sidebar.title("⚡ Agent Engine Studio")
st.sidebar.caption("v1.0.0 | DSPy + ChromaDB + FastMCP")

st.sidebar.markdown("---")
st.sidebar.subheader("🖥️ Hardware & Compute Radar")

# RAM Telemetry
ram = psutil.virtual_memory()
ram_used_gb = ram.used / (1024**3)
ram_total_gb = ram.total / (1024**3)
ram_percent = ram.percent

st.sidebar.write(f"**System RAM ({ram_percent}%)**")
st.sidebar.progress(int(ram_percent))
st.sidebar.caption(f"{ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB Used")

# CPU Telemetry
cpu_percent = psutil.cpu_percent(interval=0.1)
st.sidebar.write(f"**CPU Load ({cpu_percent}%)**")
st.sidebar.progress(int(cpu_percent))

st.sidebar.markdown("---")

# ---------- CLIENT MODE TOGGLE ----------
if "client_mode" not in st.session_state:
    st.session_state.client_mode = False

client_mode = st.sidebar.toggle(
    "🔒 Client Mode (simplified view)",
    value=st.session_state.client_mode,
    help="Hides advanced provider, context, and benchmark settings for non-technical clients.",
)
st.session_state.client_mode = client_mode

st.sidebar.markdown("---")

# Conditional Router Controls based on Client Mode
if not client_mode:
    st.sidebar.subheader("🤖 LLM Backend Router")

    status = router.get_status()

    c1, c2 = st.sidebar.columns(2)
    with c1:
        st.caption("Ollama Daemon")
        if status["ollama_live"]:
            st.success("🟢 Online")
        else:
            st.error("🔴 Offline")

    with c2:
        st.caption("llama.cpp")
        if status["llamacpp_live"]:
            st.success("🟢 Online")
        else:
            st.error("🔴 Offline")

    selected_provider = st.sidebar.selectbox(
        "Active LLM Provider",
        ["ollama", "llamacpp", "gemini", "openai", "anthropic", "groq", "deepseek"],
        index=0,
    )

    bypass_cache = st.sidebar.toggle(
        "⚡ Bypass DSPy Cache",
        value=True,
        help="When enabled (recommended for benchmarks), forces model to run live generation loops on hardware instead of retrieving instant cached responses.",
    )

    if st.sidebar.button("🔄 Switch / Re-Init Provider", use_container_width=True):
        with st.spinner("Configuring backend..."):
            lm, label = router.initialize_and_configure(
                force_provider=selected_provider, cache=not bypass_cache
            )
            st.sidebar.success(f"Configured: {label}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Context Window")

    # Single context slider – value stored in session state for persistence
    if "context_choice" not in st.session_state:
        st.session_state.context_choice = 4096

    context_choice = st.sidebar.select_slider(
        "Select KV Cache Size:",
        options=[2048, 4096, 8192, 16384],
        value=st.session_state.context_choice,
        format_func=lambda x: (
            f"{x} tokens {'(fast)' if x == 2048 else '(balanced)' if x == 4096 else '(heavy)'}"
        ),
    )
    st.session_state.context_choice = context_choice
    st.sidebar.caption(f"Current structural target limit: **{context_choice:,}** tokens.")

    # Button to apply new context and restart llama-server
    if st.sidebar.button("Apply Context Change & Restart Server"):
        os.system("pkill -f 'llama-server.*port 8080'")
        cmd = (
            f"/home/nadir/.local/lib/ollama/llama-server "
            f"-m /home/nadir/agent_engine/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf "
            f"-c {context_choice} --port 8080 > logs_llama_server.log 2>&1 &"
        )
        os.system(cmd)
        st.sidebar.success(f"llama-server restarted with context size {context_choice}")
        time.sleep(2)
        st.rerun()
else:
    st.sidebar.info("🔒 Client Mode active – advanced settings hidden.")
    selected_provider = "ollama" if router.check_local_ollama_health() else "llamacpp"
    bypass_cache = False
    context_choice = st.session_state.get("context_choice", 4096)

# ---------- MAIN CONTENT TABS ----------
st.markdown(
    '<div class="main-title">Autonomous Agent Engine Control Center</div>', unsafe_allow_html=True
)
st.markdown(
    '<div class="sub-title">Multi-Agent Sentry, Dynamic Blueprint Compiler, RAG Memory, and Hardware Telemetry</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🛡️  Sentry & Code Patches",
        "🧠  Dynamic Agent Studio",
        "📚  RAG Vector Memory",
        "⚡  LLM Speedometer & Benchmark",
    ]
)

# ==============================================================================
# TAB 1: SENTRY & CODE AUDIT STAGING
# ==============================================================================
with tab1:
    st.subheader("🛡️ Code Sentry Audit & Patch Review")
    st.write(
        "Review real-time code modifications, security alerts, and style remediations generated by the Sentry File-Watcher."
    )

    staged_patches = get_staged_patches()

    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.markdown(
            f'<div class="metric-card"><div class="label">Pending Review</div><div class="value">{len(staged_patches)}</div></div>',
            unsafe_allow_html=True,
        )
    with kpi2:
        init_db()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_patches WHERE status = 'applied'")
            applied_count = cursor.fetchone()[0]
        st.markdown(
            f'<div class="metric-card"><div class="label">Applied Patches</div><div class="value">{applied_count}</div></div>',
            unsafe_allow_html=True,
        )
    with kpi3:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_patches")
            total_audits = cursor.fetchone()[0]
        st.markdown(
            f'<div class="metric-card"><div class="label">Total Files Audited</div><div class="value">{total_audits}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    if not staged_patches:
        st.success("✨ All clean! No pending staged patches awaiting review.")
    else:
        st.write(f"### 📥 Pending Staged Patches ({len(staged_patches)})")
        for patch in staged_patches:
            patch_id = patch["id"]
            file_name = os.path.basename(patch["file_path"])
            risk = patch["risk_level"] or "None"
            p_type = patch["patch_type"].upper()

            with st.expander(
                f"Patch #{patch_id}: [{p_type} - {risk}] {file_name} ({patch['timestamp']})",
                expanded=True,
            ):
                st.markdown(f"**File Target:** `{patch['file_path']}`")
                st.markdown(f"**Audit Finding:** {patch['report']}")

                # Code Diff View
                col_orig, col_patch = st.columns(2)
                with col_orig:
                    st.caption("🔴 Original Code")
                    st.code(patch["original_code"], language="python")
                with col_patch:
                    st.caption("🟢 Proposed Fix")
                    st.code(patch["patched_code"], language="python")

                # Action buttons
                btn_col1, btn_col2, _ = st.columns([1, 1, 4])
                with btn_col1:
                    if st.button(
                        f"✅ Approve & Apply #{patch_id}", key=f"apply_{patch_id}", type="primary"
                    ):
                        if apply_staged_patch(patch_id):
                            st.success(f"Applied patch #{patch_id} directly to disk!")
                            st.rerun()
                        else:
                            st.error("Failed to apply patch.")
                with btn_col2:
                    if st.button(f"❌ Reject #{patch_id}", key=f"reject_{patch_id}"):
                        if reject_staged_patch(patch_id):
                            st.warning(f"Rejected patch #{patch_id}.")
                            st.rerun()

    # Historical Log
    st.markdown("---")
    st.subheader("📜 Audit Trail History")
    with sqlite3.connect(DB_PATH) as conn:
        df_history = pd.read_sql_query(
            "SELECT id, file_path, status, patch_type, risk_level, timestamp FROM audit_patches ORDER BY id DESC LIMIT 20",
            conn,
        )
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.caption("No historical audit records yet.")


# ==============================================================================
# TAB 2: DYNAMIC AGENT STUDIO (with Templates + Import/Export)
# ==============================================================================
with tab2:
    st.subheader("🧠 Dynamic Agent Studio & OpenClaw Skill Templates")
    st.write("Construct agents visually, or load pre‑built templates for common workflows.")

    # ---------- TEMPLATE LIBRARY ----------
    TEMPLATES = {
        "Generate SQL from Natural Language": {
            "name": "Generate SQL from Natural Language",
            "description": "Convert business questions into precise SQL queries with schema grounding.",
            "inputs": "natural_language_query, database_schema, sql_dialect",
            "outputs": "sql_query, explanation",
            "reasoning": "Chain of Thought (cot)",
        },
        "Summarize Meeting Notes": {
            "name": "Summarize Meeting Notes",
            "description": "Condense meeting transcripts into bullet points and action items.",
            "inputs": "transcript, focus_areas",
            "outputs": "summary, action_items",
            "reasoning": "Chain of Thought (cot)",
        },
        "Draft Weekly Report": {
            "name": "Draft Weekly Report",
            "description": "Generate a structured weekly update from tasks and achievements.",
            "inputs": "tasks_done, blockers, next_week_plans",
            "outputs": "report",
            "reasoning": "Chain of Thought (cot)",
        },
        "Extract Key Points from Document": {
            "name": "Extract Key Points from Document",
            "description": "Identify core arguments and facts from long text.",
            "inputs": "document_text, max_points",
            "outputs": "key_points, themes",
            "reasoning": "Chain of Thought (cot)",
        },
        "Convert Markdown to HTML": {
            "name": "Convert Markdown to HTML",
            "description": "Transform Markdown content into clean HTML.",
            "inputs": "markdown_content, style_preference",
            "outputs": "html_output",
            "reasoning": "Direct Predict (predict)",
        },
        "Generate Python Unit Tests": {
            "name": "Generate Python Unit Tests",
            "description": "Write pytest test cases for a given function.",
            "inputs": "function_code, test_framework",
            "outputs": "test_code",
            "reasoning": "Chain of Thought (cot)",
        },
        "Explain Code": {
            "name": "Explain Code",
            "description": "Provide a line‑by‑line explanation of any code snippet.",
            "inputs": "code_snippet, language",
            "outputs": "explanation",
            "reasoning": "Chain of Thought (cot)",
        },
        "Translate Code to Another Language": {
            "name": "Translate Code to Another Language",
            "description": "Convert code from one programming language to another.",
            "inputs": "source_code, source_lang, target_lang",
            "outputs": "translated_code",
            "reasoning": "ReAct with Tools (react)",
        },
        "Generate API Endpoint from Specification": {
            "name": "Generate API Endpoint from Specification",
            "description": "Create a FastAPI endpoint stub from an OpenAPI spec.",
            "inputs": "spec_description, path, method",
            "outputs": "endpoint_code, documentation",
            "reasoning": "Chain of Thought (cot)",
        },
        "Create JSON Schema": {
            "name": "Create JSON Schema",
            "description": "Derive a JSON schema from example data.",
            "inputs": "sample_data, schema_name",
            "outputs": "json_schema",
            "reasoning": "Direct Predict (predict)",
        },
        "Email Draft from Brief": {
            "name": "Email Draft from Brief",
            "description": "Write a professional email based on key points.",
            "inputs": "recipient, tone, key_points",
            "outputs": "draft_email",
            "reasoning": "Chain of Thought (cot)",
        },
        "Code Review Checklist": {
            "name": "Code Review Checklist",
            "description": "Generate a security + style checklist for Python code.",
            "inputs": "code, ruleset",
            "outputs": "checklist, score",
            "reasoning": "Chain of Thought (cot)",
        },
    }

    # ---------- SESSION STATE INIT FOR FORM ----------
    for key in ["agent_name", "agent_desc", "inputs_raw", "outputs_raw", "reasoning_style"]:
        if key not in st.session_state:
            st.session_state[key] = ""

    if "prev_selected_template" not in st.session_state:
        st.session_state["prev_selected_template"] = "(Custom)"

    # ---------- TEMPLATE SELECTION ----------
    template_names = list(TEMPLATES.keys())
    selected_template = st.selectbox(
        "Select Skill Template / Workflow:",
        ["(Custom)"] + template_names,
        index=0,
        key="template_dropdown_selector",
    )

    if selected_template != st.session_state["prev_selected_template"]:
        st.session_state["prev_selected_template"] = selected_template
        if selected_template != "(Custom)":
            template = TEMPLATES[selected_template]
            st.session_state.agent_name = template["name"]
            st.session_state.agent_desc = template["description"]
            st.session_state.inputs_raw = template["inputs"]
            st.session_state.outputs_raw = template["outputs"]
            st.session_state.reasoning_style = template["reasoning"]
            st.session_state["agent_name_input"] = template["name"]
            st.session_state["agent_desc_input"] = template["description"]
            st.session_state["inputs_raw_input"] = template["inputs"]
            st.session_state["outputs_raw_input"] = template["outputs"]
            st.session_state["reasoning_style_input"] = template["reasoning"]

    # ---------- IMPORT / EXPORT BUTTONS ----------
    col_imp, col_exp = st.columns(2)
    with col_imp:
        uploaded_file = st.file_uploader(
            "📤 Import Blueprint (JSON)", type=["json"], key="import_blueprint"
        )
        if uploaded_file is not None:
            file_sig = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get("last_imported_sig") != file_sig:
                try:
                    data = json.load(uploaded_file)
                    name_val = data.get("name", "")
                    desc_val = data.get("description", "")
                    inputs_val = (
                        ", ".join(data.get("inputs", []))
                        if isinstance(data.get("inputs"), list)
                        else str(data.get("inputs", ""))
                    )
                    outputs_val = (
                        ", ".join(data.get("outputs", []))
                        if isinstance(data.get("outputs"), list)
                        else str(data.get("outputs", ""))
                    )
                    raw_r = data.get("reasoning_type", "Chain of Thought (cot)")
                    if "react" in str(raw_r).lower():
                        reasoning_val = "ReAct with Tools (react)"
                    elif "predict" in str(raw_r).lower():
                        reasoning_val = "Direct Predict (predict)"
                    else:
                        reasoning_val = "Chain of Thought (cot)"

                    st.session_state.agent_name = name_val
                    st.session_state.agent_desc = desc_val
                    st.session_state.inputs_raw = inputs_val
                    st.session_state.outputs_raw = outputs_val
                    st.session_state.reasoning_style = reasoning_val
                    st.session_state["agent_name_input"] = name_val
                    st.session_state["agent_desc_input"] = desc_val
                    st.session_state["inputs_raw_input"] = inputs_val
                    st.session_state["outputs_raw_input"] = outputs_val
                    st.session_state["reasoning_style_input"] = reasoning_val
                    st.session_state["last_imported_sig"] = file_sig
                    st.success("Blueprint imported successfully!")
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

    with col_exp:
        # Build current config for export
        current_config = {
            "name": st.session_state.agent_name,
            "description": st.session_state.agent_desc,
            "inputs": [s.strip() for s in st.session_state.inputs_raw.split(",") if s.strip()],
            "outputs": [s.strip() for s in st.session_state.outputs_raw.split(",") if s.strip()],
            "reasoning_type": st.session_state.reasoning_style,
        }
        if current_config["name"] and current_config["inputs"] and current_config["outputs"]:
            json_str = json.dumps(current_config, indent=2)
            st.download_button(
                label="📥 Export Blueprint",
                data=json_str,
                file_name=f"{current_config['name'].replace(' ', '_')}.json",
                mime="application/json",
                use_container_width=True,
            )
        else:
            st.button(
                "📥 Export Blueprint",
                disabled=True,
                use_container_width=True,
                help="Fill in the form first.",
            )

    st.markdown("---")

    # Ensure widget keys are set if not yet in session_state
    for k_item, val_item in [
        ("agent_name_input", st.session_state.get("agent_name", "")),
        ("agent_desc_input", st.session_state.get("agent_desc", "")),
        ("inputs_raw_input", st.session_state.get("inputs_raw", "")),
        ("outputs_raw_input", st.session_state.get("outputs_raw", "")),
        (
            "reasoning_style_input",
            st.session_state.get("reasoning_style", "Chain of Thought (cot)"),
        ),
    ]:
        if k_item not in st.session_state:
            st.session_state[k_item] = val_item

    # ---------- BLUEPRINT FORM ----------
    col_form, col_exec = st.columns(2)

    with col_form:
        st.markdown("#### 1. Define Blueprint Schema")
        agent_name = st.text_input("Agent Name", key="agent_name_input")
        agent_desc = st.text_area("System Goal / Description", key="agent_desc_input", height=100)
        inputs_raw = st.text_input("Inputs (comma-separated)", key="inputs_raw_input")
        outputs_raw = st.text_input("Outputs (comma-separated)", key="outputs_raw_input")

        reasoning_options = [
            "Chain of Thought (cot)",
            "ReAct with Tools (react)",
            "Direct Predict (predict)",
        ]
        reasoning_style = st.selectbox(
            "Reasoning Style", reasoning_options, key="reasoning_style_input"
        )
        # Update session state (so export/import work)
        st.session_state.agent_name = agent_name
        st.session_state.agent_desc = agent_desc
        st.session_state.inputs_raw = inputs_raw
        st.session_state.outputs_raw = outputs_raw
        st.session_state.reasoning_style = reasoning_style

        # OpenClaw Integration Snippet Accordion
        with st.expander("🔌 OpenClaw Integration & Headless Bridge", expanded=False):
            template_slug = agent_name.lower().replace(" ", "_") if agent_name else "custom_agent"
            st.markdown(f"""
```python
from core.templates import load_template_agent

# OpenClaw dynamically loads without custom Python code:
agent = load_template_agent("{template_slug}")
result = agent(**input_payload)
print(result)
```
""")
            st.caption(f"Config stored at: `configs/templates/{template_slug}.json`")

    with col_exec:
        st.markdown("#### 2. Execute Compiled Agent")
        in_fields = [s.strip() for s in inputs_raw.split(",") if s.strip()]
        input_payload = {}
        for f in in_fields:
            if "schema" in f.lower():
                input_payload[f] = st.text_area(
                    f"Input: {f}",
                    value="TABLE customers (id INT, email VARCHAR); TABLE orders (id INT, customer_id INT, total DECIMAL);",
                    height=100,
                )
            elif "query" in f.lower() or "transcript" in f.lower() or "document" in f.lower():
                input_payload[f] = st.text_area(
                    f"Input: {f}",
                    value="Find the top 5 customers who spent the most in Q3 2026.",
                    height=60,
                )
            elif "code" in f.lower() or "snippet" in f.lower():
                input_payload[f] = st.text_area(
                    f"Input: {f}", value="def add(a, b):\n    return a + b", height=80
                )
            else:
                input_payload[f] = st.text_input(
                    f"Input: {f}", value="PostgreSQL" if "dialect" in f.lower() else "default"
                )

        # Context window usage
        total_chars = sum(len(str(v)) for v in input_payload.values()) + len(agent_desc)
        est_tokens = int(total_chars / 3.8)
        usage = min((est_tokens / context_choice) * 100, 100.0)
        st.progress(int(usage))
        st.caption(f"~{est_tokens:,} / {context_choice:,} tokens ({usage:.1f}%)")

        if st.button("🚀 Compile & Run Blueprint", type="primary", use_container_width=True):
            r_type = "cot"
            if "react" in reasoning_style.lower():
                r_type = "react"
            elif "predict" in reasoning_style.lower():
                r_type = "predict"

            config = NodeConfig(
                name=agent_name,
                description=agent_desc,
                inputs=in_fields,
                outputs=[s.strip() for s in outputs_raw.split(",") if s.strip()],
                reasoning_type=r_type,
            )

            # Use provider from sidebar (or fallback)
            if client_mode:
                provider = "ollama"
            else:
                provider = selected_provider

            with st.spinner(f"Executing with {provider}..."):
                router = ModelRouter()
                if hasattr(router, "get_lm_for_tenant"):
                    lm, _ = router.get_lm_for_tenant(
                        tenant_id="local",
                        provider=provider,
                        cache=not bypass_cache,
                        num_ctx=context_choice,
                    )
                else:
                    lm, _ = router.initialize_and_configure(
                        force_provider=provider, cache=not bypass_cache, num_ctx=context_choice
                    )
                with dspy.context(lm=lm):
                    agent = LowCodeAgent(config)
                    prediction = agent(**input_payload)
                    pred_dict = (
                        prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)
                    )
                st.success("Done!")
                st.json(pred_dict)


# ==============================================================================
# TAB 3: RAG VECTOR MEMORY
# ==============================================================================
with tab3:
    st.subheader("📚 ChromaDB Persistent Vector Memory")
    st.write(
        "Inspect, query, and ingest contextual facts, API documentation, and code rules into the persistent vector store."
    )

    c_mem1, c_mem2 = st.columns([1, 1])

    with c_mem1:
        st.markdown("#### 🔍 Semantic Memory Search")
        query_input = st.text_input(
            "Query Memory", value="How does local LLM routing work on Ryzen CPUs?"
        )
        top_k = st.slider("Passages to Retrieve (Top K)", 1, 5, 3)

        if st.button("Search Vector Memory", use_container_width=True):
            passages = memory.retrieve_passages(query_input, n_results=top_k)
            if passages:
                for idx, p in enumerate(passages, 1):
                    st.info(f"**Match #{idx}:** {p}")
            else:
                st.warning("No matching memory documents found.")

    with c_mem2:
        st.markdown("#### ➕ Ingest Knowledge Document")
        doc_text = st.text_area(
            "Document Content",
            value="FastMCP exposes Python agent tools directly over stdio to VS Code and Goose AI.",
            height=120,
        )
        source_tag = st.text_input("Source Tag / Topic", value="architecture_guide")

        if st.button("📥 Store into ChromaDB", type="primary", use_container_width=True):
            ids = memory.add_documents([doc_text], metadatas=[{"source": source_tag}])
            st.success(
                f"Indexed document successfully (ID: {ids[0]}). Total count: {memory.count()}"
            )

    st.markdown("---")
    st.caption(f"Total Vectors in Active Collection ('agent_knowledge'): {memory.count()}")

# ==============================================================================
# TAB 4: LLM SPEEDOMETER & BENCHMARK
# ==============================================================================


def render_speedometer_and_sandbox():
    st.write(
        "Measure inference latency, token generation throughput, and test failover resilience in an interactive sandbox."
    )

    bench_col1, bench_col2 = st.columns(2)

    with bench_col1:
        st.markdown("#### Challenge Type Configuration")
        challenge_type = st.selectbox(
            "Select Coding Target Challenge:",
            options=[
                "Algorithmic Data Optimization",
                "FastAPI CRUD Endpoint Generator",
                "Thread-Safe Architecture Design",
            ],
        )

    with bench_col2:
        st.markdown("#### Run Synthetic Benchmark")

        if st.button(
            "🚀 Fire Synthetic Benchmark Challenge", type="primary", use_container_width=True
        ):
            # 1. Initialize global router configuration variables safely
            try:
                router.initialize_and_configure(
                    force_provider=selected_provider, cache=not bypass_cache, num_ctx=context_choice
                )
                bench_runner = dspy.Predict(BenchSig)
            except Exception as init_err:
                st.warning(f"⚠️ Router initialization failed: {init_err}")
                if router.check_local_ollama_health():
                    local_lm, _ = router.create_lm(
                        "ollama", cache=not bypass_cache, num_ctx=context_choice
                    )
                    dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                else:
                    from core.models import get_model_provider

                    local_lm = get_model_provider(
                        "local", cache=not bypass_cache, num_ctx=context_choice
                    )
                    dspy.configure(lm=local_lm, cache=not bypass_cache)
                bench_runner = dspy.Predict(BenchSig)

            start_time = time.time()
            output_text = ""

            with st.spinner(
                f"Generating challenge response with '{selected_provider}' backend (ctx={context_choice}, {'Uncached' if bypass_cache else 'Cached'})..."
            ):
                try:
                    # 2. Try running through your primary selected cloud/local endpoint model
                    with dspy.context(cache=not bypass_cache):
                        res = bench_runner(challenge=challenge_type)
                    output_text = str(getattr(res, "solution", "") or getattr(res, "code", ""))
                    if not output_text and hasattr(res, "reasoning"):
                        output_text = str(res.reasoning)
                except Exception as transport_error:
                    st.error(f"❌ Primary Provider Error: {transport_error}")
                    fallback_success = False

                    # 3. Intelligent fallback recovery to active local engines
                    if router.check_local_ollama_health():
                        st.info(
                            "🔌 Rerouting workload to active local Ollama daemon on port 11434..."
                        )
                        try:
                            local_lm, label = router.create_lm(
                                "ollama", cache=not bypass_cache, num_ctx=context_choice
                            )
                            dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                            fallback_runner = dspy.Predict(BenchSig)
                            with dspy.context(cache=not bypass_cache):
                                res = fallback_runner(challenge=challenge_type)
                            output_text = str(
                                getattr(res, "solution", "") or getattr(res, "code", "")
                            )
                            if not output_text and hasattr(res, "reasoning"):
                                output_text = str(res.reasoning)
                            fallback_success = True
                            st.success(f"Recovered successfully using {label}!")
                        except Exception as e:
                            st.warning(f"Ollama execution failed: {e}")

                    if not fallback_success and router.check_local_llamacpp_health():
                        st.info(
                            "🔌 Rerouting workload to active local llama.cpp server on port 8080..."
                        )
                        try:
                            local_lm, label = router.create_lm("llamacpp", cache=not bypass_cache)
                            dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                            fallback_runner = dspy.Predict(BenchSig)
                            with dspy.context(cache=not bypass_cache):
                                res = fallback_runner(challenge=challenge_type)
                            output_text = str(
                                getattr(res, "solution", "") or getattr(res, "code", "")
                            )
                            if not output_text and hasattr(res, "reasoning"):
                                output_text = str(res.reasoning)
                            fallback_success = True
                            st.success(f"Recovered successfully using {label}!")
                        except Exception as e:
                            st.warning(f"llama.cpp execution failed: {e}")

                    if not fallback_success and not output_text:
                        st.error(
                            "💀 Inference Failure: Could not reach selected provider or local inference fallback nodes."
                        )
                        st.warning(
                            "💡 Action Required: If using local inference, ensure Ollama is running (`./start_ollama.sh`). If using cloud, configure your API keys in `.env`."
                        )

            duration = time.time() - start_time

            # 5. Persist and display benchmark results
            if output_text:
                clean_code = extract_code_block(output_text) or output_text
                clean_code = auto_repair_naked_return(clean_code)

                est_tokens = len(clean_code.split()) * 1.3
                tok_per_sec = est_tokens / duration if duration > 0 else 0
                is_cached = not bypass_cache and duration < 0.1

                st.session_state["benchmark_result"] = {
                    "challenge": challenge_type,
                    "provider": selected_provider,
                    "duration": duration,
                    "est_tokens": int(est_tokens),
                    "tok_per_sec": tok_per_sec,
                    "output_text": clean_code,
                    "raw_output": output_text,
                    "cached": is_cached,
                    "bypass_cache": bypass_cache,
                    "context_size": context_choice,
                }
                # Sync directly into sandbox text area key so Streamlit updates immediately
                st.session_state["sandbox_code"] = clean_code

    # Full-width benchmark results view
    if "benchmark_result" in st.session_state:
        b_res = st.session_state["benchmark_result"]

        # ----- Insert into history database -----
        conn = sqlite3.connect("data/audit_sentry.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO benchmark_history
            (timestamp, provider, context_size, challenge, latency_seconds, tokens_per_second, estimated_tokens, cached)
            VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                b_res["provider"],
                b_res.get("context_size", context_choice),
                b_res["challenge"],
                b_res["duration"],
                b_res["tok_per_sec"],
                b_res["est_tokens"],
                1 if b_res.get("cached") else 0,
            ),
        )
        conn.commit()
        conn.close()
        # ---------------------------------------

        st.markdown("---")
        st.subheader(f"📊 Benchmark Results: {b_res['challenge']}")
        st.caption(
            f"Executed on active backend: **{b_res['provider']}** &bull; Context Window: **{b_res.get('context_size', context_choice):,} tokens**"
        )

        # Metrics row
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Latency", f"{b_res['duration']:.2f} s")
        with m2:
            st.metric("Estimated Tokens", f"{b_res['est_tokens']}")
        with m3:
            st.metric("Generation Speed", f"{b_res['tok_per_sec']:.1f} tok/s")
        with m4:
            mode_label = "⚡ Live Hardware" if not b_res.get("cached") else "💾 In-Memory Cache"
            st.metric("Execution Mode", mode_label)

        if b_res.get("cached"):
            st.info(
                "💡 **Cached Result Detected**: Toggle '⚡ Bypass DSPy Cache' in the sidebar to benchmark raw hardware speed."
            )

        # ============================================================
        # 1. INTERACTIVE EXECUTION SANDBOX
        # ============================================================
        st.markdown("---")
        st.subheader("🧪 Interactive Sandbox – Run the Generated Code")
        with st.expander("✏️ Edit & Run Code", expanded=True):
            # Synchronize session state sandbox_code
            if "sandbox_code" not in st.session_state or not st.session_state["sandbox_code"]:
                st.session_state["sandbox_code"] = extract_code_block(b_res.get("output_text", ""))

            current_sandbox_code = st.session_state.get("sandbox_code", "")

            # Action buttons for code cleanup & reset
            col_actions_1, col_actions_2, col_actions_3 = st.columns([2, 1, 1])
            with col_actions_2:
                if st.button("🧹 Strip Backticks & Clean", key="clean_sandbox_btn"):
                    st.session_state["sandbox_code"] = extract_code_block(current_sandbox_code)
                    st.rerun()
            with col_actions_3:
                if st.button("🔄 Reset to Solution", key="reset_sandbox_btn"):
                    st.session_state["sandbox_code"] = extract_code_block(
                        b_res.get("output_text", "")
                    )
                    st.rerun()

            # Editable code area – pre‑filled with the sanitized generated solution
            code_to_run = st.text_area(
                "Code to execute (Python):",
                value=current_sandbox_code,
                height=220,
                key="sandbox_code",
            )

            col_run, col_repair = st.columns([2, 3])
            with col_run:
                run_pressed = st.button("▶️ Run Code", key="run_sandbox", type="primary")

            # Check if there is an obvious naked return at module level
            first_line = next((l.strip() for l in code_to_run.splitlines() if l.strip()), "")
            if first_line.startswith("return "):
                with col_repair:
                    if st.button("🪄 Auto-Wrap in Function Definition", key="repair_sandbox_btn"):
                        repaired = auto_repair_naked_return(code_to_run)
                        st.session_state["sandbox_code"] = repaired
                        st.rerun()

            if run_pressed:
                # Capture stdout/stderr
                output_capture = io.StringIO()
                error_capture = io.StringIO()

                # Pre-clean: strip accidental markdown fences if present
                exec_code = extract_code_block(code_to_run)
                if not exec_code:
                    exec_code = code_to_run.strip()

                # Syntax verification with ast.parse
                syntax_ok = True
                try:
                    ast.parse(exec_code)
                except SyntaxError as syn_err:
                    syntax_ok = False
                    error_capture.write(f"SyntaxError on line {syn_err.lineno}: {syn_err.msg}\n")
                    if syn_err.text:
                        error_capture.write(f"  Line {syn_err.lineno}: {syn_err.text.strip()}\n")
                    if (
                        "outside function" in str(syn_err.msg).lower()
                        or "return" in str(syn_err.msg).lower()
                    ):
                        error_capture.write(
                            "\n💡 Hint: A 'return' statement cannot exist at module level.\n"
                            "Click '🪄 Auto-Wrap in Function Definition' above or enclose the code in `def function_name(...):`.\n"
                        )

                if syntax_ok:
                    old_cwd = os.getcwd()
                    with tempfile.TemporaryDirectory() as tmpdir:
                        os.chdir(tmpdir)
                        try:
                            # Rich safe builtins for sandboxed execution
                            safe_builtins = {
                                name: getattr(builtins, name)
                                for name in [
                                    "abs",
                                    "all",
                                    "any",
                                    "ascii",
                                    "bin",
                                    "bool",
                                    "bytearray",
                                    "bytes",
                                    "chr",
                                    "complex",
                                    "dict",
                                    "divmod",
                                    "enumerate",
                                    "filter",
                                    "float",
                                    "format",
                                    "frozenset",
                                    "getattr",
                                    "hasattr",
                                    "hash",
                                    "hex",
                                    "int",
                                    "isinstance",
                                    "issubclass",
                                    "iter",
                                    "len",
                                    "list",
                                    "map",
                                    "max",
                                    "min",
                                    "next",
                                    "oct",
                                    "ord",
                                    "pow",
                                    "print",
                                    "range",
                                    "repr",
                                    "reversed",
                                    "round",
                                    "set",
                                    "slice",
                                    "sorted",
                                    "str",
                                    "sum",
                                    "tuple",
                                    "type",
                                    "zip",
                                    "open",
                                    "Exception",
                                    "ValueError",
                                    "TypeError",
                                    "RuntimeError",
                                    "KeyError",
                                    "IndexError",
                                    "AttributeError",
                                    "ImportError",
                                    "ZeroDivisionError",
                                    "OverflowError",
                                    "StopIteration",
                                    "AssertionError",
                                    "SyntaxError",
                                    "NameError",
                                ]
                                if hasattr(builtins, name)
                            }
                            safe_builtins["__import__"] = __import__

                            safe_globals = {
                                "__builtins__": safe_builtins,
                                "__name__": "__sandbox__",
                                "__doc__": None,
                            }

                            with (
                                contextlib.redirect_stdout(output_capture),
                                contextlib.redirect_stderr(error_capture),
                            ):
                                exec(exec_code, safe_globals)

                        except Exception as e:
                            error_capture.write(f"Runtime Exception: {e}\n")
                        finally:
                            os.chdir(old_cwd)

                # Display results
                st.subheader("📤 Execution Output")
                output_text_out = output_capture.getvalue()
                error_text = error_capture.getvalue()

                if output_text_out:
                    st.code(output_text_out, language="text")
                else:
                    st.caption("(No stdout output)")

                if error_text:
                    st.error(f"❌ Errors:\n{error_text}")
                else:
                    st.success("✅ Code executed without errors.")

        # ============================================================
        # 2. BENCHMARK HISTORY LINE CHART
        # ============================================================
        st.markdown("---")
        st.subheader("📈 Benchmark Speed History (Tokens/sec over time)")

        # Fetch history from database
        conn = sqlite3.connect("data/audit_sentry.db")
        history_df = pd.read_sql_query(
            "SELECT timestamp, tokens_per_second, provider, context_size FROM benchmark_history ORDER BY id ASC",
            conn,
        )
        conn.close()

        if history_df.empty:
            st.info("No historical benchmark data yet. Run a few benchmarks to populate the chart.")
        else:
            # Convert timestamp to datetime for better plotting
            history_df["timestamp"] = pd.to_datetime(history_df["timestamp"])
            # Line chart with tokens/sec over time
            st.line_chart(
                data=history_df,
                x="timestamp",
                y="tokens_per_second",
                color="provider",
                use_container_width=True,
            )
            # Show a small table with recent runs
            with st.expander("📋 Show recent benchmark records"):
                st.dataframe(
                    history_df.sort_values("timestamp", ascending=False).head(10),
                    use_container_width=True,
                    hide_index=True,
                )


# ==============================================================================
# TAB 4: LLM SPEEDOMETER & BENCHMARK
# ==============================================================================
with tab4:
    st.subheader("⚡ Local Model Speedometer & Interactive Sandbox")
    if client_mode:
        st.info(
            "🔒 Benchmarking and hardware profiling are disabled in Client Mode. Please toggle off Client Mode in the sidebar to run latency benchmarks and access the execution sandbox."
        )
    else:
        render_speedometer_and_sandbox()

# ---------- FOOTER ----------
st.markdown(
    '<div class="footer">Agent Engine v1.0 • DSPy + ChromaDB + FastMCP • All processing runs locally</div>',
    unsafe_allow_html=True,
)
