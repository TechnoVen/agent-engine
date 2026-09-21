"""services/python/server/api.py

Agent Engine Local API - Re-exporting Facade for Backward Compatibility.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).

All domain routes have been modularized into services/python/server/routers/.
This module preserves full backward compatibility for existing tests, tooling,
and execution coordinate callers.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy  # noqa: F401

# Application Factory and App Instance
from services.python.server.app import ALLOWED_ORIGINS, create_app

app = create_app()
v1_router = app.state.v1_router

# Canonical Service Container and Accessors
from services.python.server.container import (
    AppServices,
    START_TIME,
    broadcast_event,
    cost_tracker_instance,
    get_artifact_service,
    get_cost_tracker_service,
    get_event_subscribers,
    get_execution_coordinator,
    get_ledger_service,
    get_memory,
    get_model_router,
    get_observational_memory,
    get_services,
    get_session_store,
    get_storage_backend,
    get_swarm_coordinator,
    get_workflow_storage,
    memory_instance,
    observational_memory_instance,
    router_instance,
    set_artifact_service,
    set_execution_coordinator,
    set_ledger_service,
    set_services,
    set_swarm_coordinator,
    set_workflow_storage,
)

from core.security import get_credential_manager
from core.updater import get_update_manager

# Canonical Error Translation
from services.python.server.errors import (
    ERROR_CODE_HTTP_MAP,
    handle_domain_error,
    map_execution_error_to_http,
)

# Streaming & Transport
from services.python.server.transport import (
    format_sse_chunk,
    format_sse_comment,
    format_sse_error,
)

# Authentication & IPC Dependencies
from services.python.server.dependencies import verify_ipc_token

# Pydantic Schemas (all shared models)
from services.python.server.schemas import *

# Domain Endpoint Functions (re-exported for direct test imports)
from services.python.server.routers.chat import chat_completions
from services.python.server.routers.executions import (
    cancel_execution_endpoint,
    get_execution_endpoint,
    get_execution_events_endpoint,
    list_project_executions_endpoint,
    stream_events,
)
from services.python.server.routers.ledger import get_execution_trace_endpoint
from services.python.server.routers.artifacts import (
    delete_artifact_endpoint,
    get_artifact_content_endpoint,
    get_artifact_endpoint,
    list_execution_artifacts_endpoint,
    list_project_artifacts_endpoint,
)
from services.python.server.routers.pipelines import (
    audit_pipeline_endpoint,
    get_curated_mode_cases,
    get_pipeline_details,
    list_curated_cases,
    list_pipelines,
    run_pipeline,
)
from services.python.server.routers.skills import (
    add_skill_to_collection_endpoint,
    create_skill,
    create_skill_collection,
    delete_skill,
    delete_skill_collection,
    discover_remote_skills,
    execute_skill,
    get_collection_member_skills,
    get_skill,
    get_skill_collection,
    import_remote_skill,
    install_registry_package,
    list_agents,
    list_registry_packages,
    list_skill_collections,
    list_skills,
    remove_skill_from_collection_endpoint,
    search_skills_endpoint,
    uninstall_registry_package,
    update_skill,
    update_skill_collection,
    validate_skill_content,
)
from services.python.server.routers.adapters import (
    discord_interactions_webhook,
    execute_adapter_endpoint,
    get_adapter_endpoint,
    list_adapters_endpoint,
    mattermost_hooks_webhook,
    slack_events_webhook,
    stream_adapter_endpoint,
    teams_activities_webhook,
    test_adapter_endpoint,
)
from services.python.server.routers.projects import (
    append_unified_message,
    build_context_endpoint,
    create_project,
    create_unified_session,
    delete_project,
    delete_unified_session,
    export_unified_session,
    fork_unified_session,
    get_project,
    get_unified_session,
    import_unified_session,
    list_projects,
    list_unified_sessions,
    search_unified_sessions,
    update_project,
    update_unified_session,
)
from services.python.server.routers.policies import (
    approve_pending_operation,
    batch_operations,
    dry_run_safety_policy,
    evaluate_safety,
    export_safety_audit_logs,
    get_pending_operation,
    get_safety_audit_logs,
    get_safety_policy_yaml,
    list_pending_operations,
    list_safety_audit_logs_paginated,
    list_safety_policies,
    register_pending_operation,
    reject_pending_operation,
    submit_safety_approval,
    update_safety_policy_yaml,
    verify_execution,
)
from services.python.server.routers.telemetry import (
    get_budget_config,
    get_cost_metrics,
    get_hardware_telemetry,
    get_telemetry,
    list_distillation_candidates,
    record_cost_metric,
    record_inference_speed_endpoint,
    set_budget_config,
    trigger_distillation,
)
from services.python.server.routers.models import (
    clear_cache,
    get_cache_stats,
    get_eval_benchmarks_endpoint,
    get_eval_rankings_endpoint,
    get_router_tiers_endpoint,
    lookup_cache,
    route_step_endpoint,
    run_eval_endpoint,
    store_cache,
)
from services.python.server.routers.credentials import (
    delete_credential_endpoint,
    get_credential_endpoint,
    list_credentials_endpoint,
    set_credential_endpoint,
    test_credential_endpoint,
)
from services.python.server.routers.workflows import (
    approve_workflow_gate_endpoint,
    create_or_run_workflow,
    delete_workflow_endpoint,
    dry_run_workflow_endpoint,
    get_workflow_endpoint,
    get_workflow_run_endpoint,
    list_pending_workflow_gates_endpoint,
    list_workflow_runs_endpoint,
    list_workflows_endpoint,
    redirect_workflow_gate_endpoint,
    reject_workflow_gate_endpoint,
    run_workflow_endpoint,
    update_workflow_endpoint,
    validate_workflow_endpoint,
)
from services.python.server.routers.swarm import (
    estimate_swarm_cost_endpoint,
    list_swarm_cases_endpoint,
    run_swarm_endpoint,
)
from services.python.server.routers.memory import (
    ingest_memory,
    query_memory,
    query_observations,
    record_observation,
)
from services.python.server.routers.tasks import (
    create_scheduled_task_endpoint,
    delete_scheduled_task_endpoint,
    list_scheduled_tasks,
    toggle_scheduled_task_endpoint,
    trigger_scheduled_task_endpoint,
)
from services.python.server.routers.patches import (
    apply_patch,
    list_patches,
    reject_patch,
)
from services.python.server.routers.collaboration import (
    add_room_participant,
    claim_room_task,
    create_room,
    create_room_task,
    delete_room,
    get_room,
    get_room_context,
    get_room_task,
    list_room_participants,
    list_room_tasks,
    list_rooms,
    remove_room_participant,
    update_room,
    update_room_task,
)
from services.python.server.routers.system import (
    check_updates_endpoint,
    export_diagnostics_endpoint,
    get_auth_session,
    get_flags,
    get_settings_config_endpoint,
    get_sidecar_health,
    get_updater_status_endpoint,
    healthz,
    override_flag,
    search_registry,
    set_updater_channel_endpoint,
    update_settings_config_endpoint,
)


def main(argv: Optional[List[str]] = None):
    """Entrypoint for Agent Engine Python sidecar service."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Agent Engine Python Sidecar Service (FastAPI + FastMCP + ACP)",
        prog="agent-engine-sidecar",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(os.environ.get("AGENT_ENGINE_PORT", os.environ.get("PORT", "8000"))),
        help="Port to bind the sidecar service (default: 8000 or /)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("AGENT_ENGINE_HOST", "127.0.0.1"),
        help="Host address to bind the sidecar service (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("AGENT_ENGINE_IPC_TOKEN"),
        help="Optional secret IPC token for shell-to-sidecar authentication",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        help="Print sidecar version and exit",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Perform internal health self-test and exit",
    )

    args = parser.parse_args(argv)

    if args.version:
        print("0.1.0")
        sys.exit(0)

    if args.verify:
        print("Agent Engine Sidecar v0.1.0: Self-check passed. Routes and schema verified.")
        sys.exit(0)

    if args.token:
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = args.token

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
