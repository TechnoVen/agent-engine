import json
import os
import sys

import psutil

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure numpy pre-import for DSPy compatibility
from mcp.server.fastmcp import FastMCP

from core.engine import LowCodeAgent, NodeConfig
from core.memory import AgentMemory
from core.router import ModelRouter
from core.templates import TemplateManager
from server.watcher import (
    AutonomousPatchEngine,
    apply_staged_patch,
    get_staged_patches,
    stage_patch_record,
)

# Initialize FastMCP server
mcp = FastMCP("AgentEngine", dependencies=["dspy", "chromadb", "pydantic", "psutil", "watchdog"])

# Initialize shared components
router = ModelRouter()
patch_engine = AutonomousPatchEngine()
memory = AgentMemory()


@mcp.tool()
def analyze_and_fix_code(code: str, file_path: str = "snippet.py") -> str:
    """
    Audit Python code for OWASP security vulnerabilities and PEP 8 cleanliness.
    If vulnerabilities or violations are found, generates a clean, patched version.
    """
    router.initialize_and_configure()
    result = patch_engine.scan_and_patch(code)

    if not result["needs_patch"]:
        return f"✅ [Clean]: No vulnerabilities or style violations detected in {file_path}."

    patch_type = result["type"].upper()
    risk = result["risk_level"]
    report = result["report"]
    patched_code = result["patched_code"]

    # Stage the patch for reference
    patch_id = stage_patch_record(
        file_path=file_path,
        patch_type=result["type"],
        risk_level=risk,
        report=report,
        original_code=code,
        patched_code=patched_code,
        status="staged",
    )

    response = (
        f"⚠️ [{patch_type} ALERT] (Risk: {risk} | Patch ID #{patch_id})\n"
        f"Report: {report}\n\n"
        f"--- Proposed Remediated Code ---\n"
        f"```python\n{patched_code}\n```"
    )
    return response


@mcp.tool()
def query_agent_memory(query: str, top_k: int = 3) -> str:
    """
    Perform semantic vector search over the local ChromaDB RAG memory.
    Returns relevant knowledge passages and facts.
    """
    passages = memory.retrieve_passages(query, n_results=top_k)
    if not passages:
        return f"No memory items found matching query: '{query}'."

    output = [f"=== Memory Query: '{query}' (Found {len(passages)} passages) ==="]
    for idx, p in enumerate(passages, 1):
        output.append(f"[{idx}] {p}")
    return "\n\n".join(output)


@mcp.tool()
def ingest_agent_memory(document_text: str, source_title: str = "ide_note") -> str:
    """
    Store new text, documentation, or code architectural notes into the local ChromaDB RAG memory.
    """
    import datetime

    now_iso = datetime.datetime.now().isoformat()
    ids = memory.add_documents(
        documents=[document_text], metadatas=[{"source": source_title, "timestamp": now_iso}]
    )
    return f"Successfully indexed document into vector memory (ID: {ids[0]}). Total count: {memory.count()}"


@mcp.tool()
def execute_dynamic_blueprint(
    name: str,
    description: str,
    inputs_comma_separated: str,
    outputs_comma_separated: str,
    payload_json: str,
) -> str:
    """
    Dynamically compile and execute a custom DSPy agent blueprint on the fly.
    - inputs_comma_separated: e.g. "code, goal"
    - outputs_comma_separated: e.g. "refactored_code, explanation"
    - payload_json: JSON string with matching input key-values, e.g. '{"code": "...", "goal": "..."}'
    """
    router.initialize_and_configure()

    in_list = [s.strip() for s in inputs_comma_separated.split(",") if s.strip()]
    out_list = [s.strip() for s in outputs_comma_separated.split(",") if s.strip()]

    config = NodeConfig(
        name=name, description=description, inputs=in_list, outputs=out_list, reasoning_type="cot"
    )

    try:
        payload = json.loads(payload_json)
    except Exception as e:
        return f"Error parsing payload_json: {e}"

    agent = LowCodeAgent(config)
    prediction = agent(**payload)
    pred_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)

    return json.dumps({"agent": name, "inputs": payload, "results": pred_dict}, indent=2)


@mcp.tool()
def list_staged_patches() -> str:
    """
    List all pending security and code quality patches waiting for review.
    """
    patches = get_staged_patches()
    if not patches:
        return "No pending staged patches in database."

    output = [f"Found {len(patches)} pending staged patches:"]
    for p in patches:
        output.append(
            f"- Patch #{p['id']}: File '{p['file_path']}' | Type: {p['patch_type']} | Risk: {p['risk_level']} | Staged at: {p['timestamp']}"
        )
    return "\n".join(output)


@mcp.tool()
def apply_staged_patch_by_id(patch_id: int) -> str:
    """
    Apply a pending staged patch directly to the target file on disk.
    """
    success = apply_staged_patch(patch_id)
    if success:
        return f"Successfully applied patch #{patch_id} to file!"
    return f"Failed to apply patch #{patch_id}. Patch ID may not exist or is already applied."


@mcp.tool()
def get_system_telemetry() -> str:
    """
    Retrieve local hardware resource consumption (RAM, CPU) and LLM backend status.
    """
    ram = psutil.virtual_memory()
    router_status = router.get_status()

    telemetry = {
        "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
        "ram_total_gb": round(ram.total / (1024**3), 2),
        "ram_available_gb": round(ram.available / (1024**3), 2),
        "ram_used_percent": ram.percent,
        "ollama_active": router_status["ollama_live"],
        "llamacpp_active": router_status["llamacpp_live"],
        "primary_provider": router_status["primary_provider"],
        "active_model": router_status["active_model"],
        "indexed_memory_documents": memory.count(),
    }
    return json.dumps(telemetry, indent=2)


@mcp.tool()
def list_skill_templates() -> str:
    """
    List all available OpenClaw skill templates discovered in configs/templates/.
    Provides template ID, name, category, description, and input parameters.
    """
    templates = TemplateManager.list_templates()
    if not templates:
        return "No skill templates found in configs/templates/."

    catalog = []
    for t in templates:
        catalog.append(
            {
                "id": t.id,
                "name": t.name,
                "category": t.category,
                "description": t.description,
                "inputs": list(t.inputs.keys()) if isinstance(t.inputs, dict) else t.inputs,
                "outputs": list(t.outputs.keys()) if isinstance(t.outputs, dict) else t.outputs,
                "sample_inputs": t.sample_inputs,
            }
        )
    return json.dumps(catalog, indent=2)


@mcp.tool()
def execute_skill_template(template_id: str, payload_json: str = "{}") -> str:
    """
    Execute a pre-built OpenClaw skill template by its template_id.
    Pass input parameters as a JSON object string in payload_json.
    """
    template = TemplateManager.get_template(template_id)
    if not template:
        return f"Error: Skill template '{template_id}' was not found in configs/templates/."

    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception as e:
        return f"Error parsing payload_json: {e}"

    # If payload is empty, default to sample inputs
    if not payload and template.sample_inputs:
        payload = template.sample_inputs

    router.initialize_and_configure()
    agent = template.create_agent()
    prediction = agent(**payload)
    pred_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)

    return json.dumps(
        {
            "template_id": template.id,
            "template_name": template.name,
            "inputs": payload,
            "results": pred_dict,
        },
        indent=2,
    )


if __name__ == "__main__":
    # Ensure router is configured on launch
    router.initialize_and_configure()
    # Runs stdio MCP server for VS Code / Cursor / Goose
    mcp.run()
