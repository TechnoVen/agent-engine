# server/dashboard.py
# Agent Engine Studio – Streamlit Control Center
# v1.0.0 | DSPy + ChromaDB + FastMCP

import os
import sys
import time
import json
import sqlite3
import difflib
import psutil
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure numpy pre‑import for DSPy compatibility
import numpy
import pandas as pd
import streamlit as st
import dspy

# Unlock thread restrictions across Streamlit re‑renders
try:
    type(dspy.settings)._ensure_configure_allowed = lambda self: None
except Exception:
    pass

from core.router import ModelRouter
from core.engine import LowCodeAgent, NodeConfig
from core.memory import AgentMemory
from server.watcher import (
    get_staged_patches,
    apply_staged_patch,
    reject_staged_patch,
    DB_PATH,
    init_db
)

# ---------- Signature for Benchmark ----------
class BenchSig(dspy.Signature):
    """Execute the software engineering challenge concisely and accurately."""
    challenge: str = dspy.InputField(desc="The challenge task")
    solution: str = dspy.OutputField(desc="Clean Python code solution")

# ---------- Page Configuration ----------
st.set_page_config(
    page_title="Autonomous Agent Engine Studio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E88E5;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid #1E88E5;
    }
    .badge-high {
        background-color: #ffebee;
        color: #c62828;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Reload core modules if changed
import importlib
import core.router
importlib.reload(core.router)
from core.router import ModelRouter

# Initialize core services
router = ModelRouter()

@st.cache_resource
def get_dashboard_memory():
    return AgentMemory()

memory = get_dashboard_memory()

# ---------- SIDEBAR: HARDWARE & TELEMETRY ----------
st.sidebar.title("⚡ Agent Engine Studio")
st.sidebar.caption("v1.0.0 | DSPy + ChromaDB + FastMCP")

st.sidebar.markdown("---")
st.sidebar.subheader("🖥️ Hardware & Compute Radar")

# RAM Telemetry
ram = psutil.virtual_memory()
ram_used_gb = ram.used / (1024 ** 3)
ram_total_gb = ram.total / (1024 ** 3)
ram_percent = ram.percent

st.sidebar.write(f"**System RAM ({ram_percent}%)**")
st.sidebar.progress(int(ram_percent))
st.sidebar.caption(f"{ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB Used")

# CPU Telemetry
cpu_percent = psutil.cpu_percent(interval=0.1)
st.sidebar.write(f"**CPU Load ({cpu_percent}%)**")
st.sidebar.progress(int(cpu_percent))

st.sidebar.markdown("---")
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
    index=0
)

bypass_cache = st.sidebar.toggle(
    "⚡ Bypass DSPy Cache",
    value=True,
    help="When enabled (recommended for benchmarks), forces model to run live generation loops on hardware instead of retrieving instant cached responses."
)

if st.sidebar.button("🔄 Switch / Re-Init Provider", use_container_width=True):
    with st.spinner("Configuring backend..."):
        lm, label = router.initialize_and_configure(force_provider=selected_provider, cache=not bypass_cache)
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
    format_func=lambda x: f"{x} tokens {'(fast)' if x==2048 else '(balanced)' if x==4096 else '(heavy)'}"
)
st.session_state.context_choice = context_choice
st.sidebar.caption(f"Current structural target limit: **{context_choice:,}** tokens.")

# Button to apply new context and restart llama-server
if st.sidebar.button("Apply Context Change & Restart Server"):
    # Kill current llama-server, restart with new -c flag
    os.system("pkill -f 'llama-server.*port 8080'")  # crude, but works
    cmd = (
        f"/home/nadir/.local/lib/ollama/llama-server "
        f"-m /home/nadir/agent_engine/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf "
        f"-c {context_choice} --port 8080 > logs_llama_server.log 2>&1 &"
    )
    os.system(cmd)
    st.sidebar.success(f"llama-server restarted with context size {context_choice}")
    time.sleep(2)
    st.rerun()

# ---------- MAIN CONTENT TABS ----------
st.markdown('<div class="main-title">Autonomous Agent Engine Control Center</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Multi-Agent Sentry, Dynamic Blueprint Compiler, RAG Memory, and Hardware Telemetry</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs([
    "🛡️ Sentry & Code Patches",
    "🧠 Dynamic Agent Studio",
    "📚 RAG Vector Memory",
    "⚡ LLM Speedometer & Benchmark"
])

# ==============================================================================
# TAB 1: SENTRY & CODE AUDIT STAGING
# ==============================================================================
with tab1:
    st.subheader("🛡️ Code Sentry Audit & Patch Review")
    st.write("Review real-time code modifications, security alerts, and style remediations generated by the Sentry File-Watcher.")

    staged_patches = get_staged_patches()

    kpi1, kpi2, kpi3 = st.columns(3)
    with kpi1:
        st.metric("Pending Review", len(staged_patches))
    with kpi2:
        init_db()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_patches WHERE status = 'applied'")
            applied_count = cursor.fetchone()[0]
        st.metric("Applied Patches", applied_count)
    with kpi3:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_patches")
            total_audits = cursor.fetchone()[0]
        st.metric("Total Files Audited", total_audits)

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

            with st.expander(f"Patch #{patch_id}: [{p_type} - {risk}] {file_name} ({patch['timestamp']})", expanded=True):
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
                    if st.button(f"✅ Approve & Apply #{patch_id}", key=f"apply_{patch_id}", type="primary"):
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
        df_history = pd.read_sql_query("SELECT id, file_path, status, patch_type, risk_level, timestamp FROM audit_patches ORDER BY id DESC LIMIT 20", conn)
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.caption("No historical audit records yet.")


# ==============================================================================
# TAB 2: DYNAMIC AGENT BLUEPRINT STUDIO
# ==============================================================================
with tab2:
    st.subheader("🧠 Low-Code DSPy Dynamic Agent Compiler")
    st.write("Construct and compile arbitrary AI agents visually by declaring signatures, inputs, and reasoning modules.")

    col_form, col_exec = st.columns([1, 1])

    with col_form:
        st.markdown("#### 1. Define Blueprint Schema")
        agent_name = st.text_input("Agent Name", value="CodeDocGenerator")
        agent_desc = st.text_area("System Goal / Description", value="Analyze the input Python function and generate comprehensive Google-style docstrings with type annotations.")

        inputs_raw = st.text_input("Inputs (comma-separated)", value="function_code, focus_area")
        outputs_raw = st.text_input("Outputs (comma-separated)", value="annotated_code, docstring_summary")
        reasoning_style = st.selectbox("Reasoning Style", ["Chain of Thought (cot)", "ReAct with Tools (react)", "Direct Predict (predict)"])

    with col_exec:
        st.markdown("#### 2. Execute Compiled Agent")
        in_fields = [s.strip() for s in inputs_raw.split(",") if s.strip()]
        out_fields = [s.strip() for s in outputs_raw.split(",") if s.strip()]

        input_payload = {}
        for f in in_fields:
            if "code" in f.lower():
                input_payload[f] = st.text_area(f"Input: {f}", value="def fetch_user(user_id):\n    return db.query(user_id)", height=100)
            else:
                input_payload[f] = st.text_input(f"Input: {f}", value="Security & Efficiency")

        # Live Context Window Utilization & Token Counter
        total_chars = sum(len(str(v)) for v in input_payload.values()) + len(agent_desc)
        est_input_tokens = int(total_chars / 3.8)
        usage_pct = min((est_input_tokens / context_choice) * 100, 100.0)

        st.markdown("##### 📏 Context Window Utilization")
        st.progress(int(usage_pct))
        c_tok1, c_tok2 = st.columns([3, 2])
        with c_tok1:
            st.caption(f"Payload: **~{est_input_tokens:,}** / **{context_choice:,}** tokens ({usage_pct:.1f}%)")
        with c_tok2:
            if usage_pct >= 100:
                st.caption("🔴 **Exceeds Limit**")
            elif usage_pct >= 75:
                st.caption("🟡 **Approaching Limit**")
            else:
                st.caption("🟢 **Optimal**")

        if usage_pct >= 100:
            st.error(f"🚨 **Payload Exceeds Active Limit**: Input is ~{est_input_tokens:,} tokens, exceeding your selected {context_choice:,} limit. Increase context in the sidebar to prevent truncation.")
        elif usage_pct >= 75:
            st.warning(f"⚠️ **Approaching Context Ceiling**: Input is consuming {usage_pct:.1f}% of active {context_choice:,} window.")

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
                outputs=out_fields,
                reasoning_type=r_type
            )

            with st.spinner(f"Compiling DSPy dynamic signature and executing with '{selected_provider}' (ctx={context_choice})..."):
                with dspy.context(cache=not bypass_cache):
                    router.initialize_and_configure(force_provider=selected_provider, cache=not bypass_cache, num_ctx=context_choice)
                    agent = LowCodeAgent(config)
                    prediction = agent(**input_payload)
                    pred_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)

                st.success("Execution Complete!")
                st.json(pred_dict)


# ==============================================================================
# TAB 3: RAG VECTOR MEMORY
# ==============================================================================
with tab3:
    st.subheader("📚 ChromaDB Persistent Vector Memory")
    st.write("Inspect, query, and ingest contextual facts, API documentation, and code rules into the persistent vector store.")

    c_mem1, c_mem2 = st.columns([1, 1])

    with c_mem1:
        st.markdown("#### 🔍 Semantic Memory Search")
        query_input = st.text_input("Query Memory", value="How does local LLM routing work on Ryzen CPUs?")
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
        doc_text = st.text_area("Document Content", value="FastMCP exposes Python agent tools directly over stdio to VS Code and Goose AI.", height=120)
        source_tag = st.text_input("Source Tag / Topic", value="architecture_guide")

        if st.button("📥 Store into ChromaDB", type="primary", use_container_width=True):
            ids = memory.add_documents([doc_text], metadatas=[{"source": source_tag}])
            st.success(f"Indexed document successfully (ID: {ids[0]}). Total count: {memory.count()}")

    st.markdown("---")
    st.caption(f"Total Vectors in Active Collection ('agent_knowledge'): {memory.count()}")

# ==============================================================================
# TAB 4: LLM SPEEDOMETER & BENCHMARK
# ==============================================================================
with tab4:
    st.subheader("⚡ LLM Speedometer & Benchmark")
    st.write("Measure inference latency, token generation throughput, and test failover resilience.")

    bench_col1, bench_col2 = st.columns(2)

    with bench_col1:
        st.markdown("#### Challenge Type Configuration")
        challenge_type = st.selectbox(
            "Select Coding Target Challenge:",
            options=[
                "Algorithmic Data Optimization",
                "FastAPI CRUD Endpoint Generator",
                "Thread-Safe Architecture Design"
            ]
        )

    with bench_col2:
        st.markdown("#### Run Synthetic Benchmark")

        if st.button("🚀 Fire Synthetic Benchmark Challenge", type="primary", use_container_width=True):
            # 1. Initialize global router configuration variables safely
            try:
                router.initialize_and_configure(force_provider=selected_provider, cache=not bypass_cache, num_ctx=context_choice)
                bench_runner = dspy.ChainOfThought(BenchSig)
            except Exception as init_err:
                st.warning(f"⚠️ Router initialization failed: {init_err}")
                if router.check_local_ollama_health():
                    local_lm, _ = router.create_lm("ollama", cache=not bypass_cache, num_ctx=context_choice)
                    dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                else:
                    from core.models import get_model_provider
                    local_lm = get_model_provider("local", cache=not bypass_cache, num_ctx=context_choice)
                    dspy.configure(lm=local_lm, cache=not bypass_cache)
                bench_runner = dspy.ChainOfThought(BenchSig)

            start_time = time.time()
            output_text = ""

            with st.spinner(f"Generating challenge response with '{selected_provider}' backend (ctx={context_choice}, {'Uncached' if bypass_cache else 'Cached'})..."):
                try:
                    # 2. Try running through your primary selected cloud/local endpoint model
                    with dspy.context(cache=not bypass_cache):
                        res = bench_runner(challenge=challenge_type)
                    output_text = str(getattr(res, "solution", ""))
                except Exception as transport_error:
                    st.error(f"❌ Primary Provider Error: {transport_error}")
                    fallback_success = False

                    # 3. Intelligent fallback recovery to active local engines
                    if router.check_local_ollama_health():
                        st.info("🔌 Rerouting workload to active local Ollama daemon on port 11434...")
                        try:
                            local_lm, label = router.create_lm("ollama", cache=not bypass_cache, num_ctx=context_choice)
                            dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                            fallback_runner = dspy.ChainOfThought(BenchSig)
                            with dspy.context(cache=not bypass_cache):
                                res = fallback_runner(challenge=challenge_type)
                            output_text = str(getattr(res, "solution", ""))
                            fallback_success = True
                            st.success(f"Recovered successfully using {label}!")
                        except Exception as e:
                            st.warning(f"Ollama execution failed: {e}")

                    if not fallback_success and router.check_local_llamacpp_health():
                        st.info("🔌 Rerouting workload to active local llama.cpp server on port 8080...")
                        try:
                            local_lm, label = router.create_lm("llamacpp", cache=not bypass_cache)
                            dspy.settings.configure(lm=local_lm, cache=not bypass_cache)
                            fallback_runner = dspy.ChainOfThought(BenchSig)
                            with dspy.context(cache=not bypass_cache):
                                res = fallback_runner(challenge=challenge_type)
                            output_text = str(getattr(res, "solution", ""))
                            fallback_success = True
                            st.success(f"Recovered successfully using {label}!")
                        except Exception as e:
                            st.warning(f"llama.cpp execution failed: {e}")

                    if not fallback_success and not output_text:
                        st.error("💀 Inference Failure: Could not reach selected provider or local inference fallback nodes.")
                        st.warning("💡 Action Required: If using local inference, ensure Ollama is running (`./start_ollama.sh`). If using cloud, configure your API keys in `.env`.")

            duration = time.time() - start_time

            # 5. Persist and display benchmark results
            if output_text:
                est_tokens = len(output_text.split()) * 1.3
                tok_per_sec = est_tokens / duration if duration > 0 else 0
                is_cached = not bypass_cache and duration < 0.1

                st.session_state["benchmark_result"] = {
                    "challenge": challenge_type,
                    "provider": selected_provider,
                    "duration": duration,
                    "est_tokens": int(est_tokens),
                    "tok_per_sec": tok_per_sec,
                    "output_text": output_text,
                    "cached": is_cached,
                    "bypass_cache": bypass_cache,
                    "context_size": context_choice
                }

    # Full-width benchmark results view
    if "benchmark_result" in st.session_state:
        b_res = st.session_state["benchmark_result"]
        st.markdown("---")
        st.subheader(f"📊 Benchmark Results: {b_res['challenge']}")
        st.caption(f"Executed on active backend: **{b_res['provider']}** &bull; Context Window: **{b_res.get('context_size', context_choice):,} tokens**")

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
            st.info("💡 **Cached Result Detected**: Response was served in milliseconds from DSPy's memory cache. Toggle **'⚡ Bypass DSPy Cache'** in the sidebar to benchmark raw GPU/CPU speed.")

        st.markdown("#### 💡 Solution Output")
        view_tab1, view_tab2 = st.tabs(["Formatted View", "Raw Output"])
        with view_tab1:
            with st.container(border=True):
                st.markdown(b_res["output_text"])
        with view_tab2:
            st.code(b_res["output_text"], language="markdown")
