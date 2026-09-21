"""Comprehensive Integration Tests for DSPy Pipeline Registry Rewired into ExecutionCoordinator (Task R1.12).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md (R1.12)

Validates all 16 canonical requirements:
1. test_coordinator_executes_pipeline_direct
2. test_pipeline_registry_delegates_to_coordinator
3. test_api_pipeline_run_returns_execution_id
4. test_single_root_execution_multi_hop_pipeline
5. test_multi_model_truthful_accounting
6. test_context_provenance_pipeline_identity
7. test_pipeline_cancellation_propagation
8. test_pipeline_cancellation_creates_partial_artifact
9. test_pipeline_diff_patch_creates_artifact
10. test_pipeline_vulnerabilities_creates_artifact
11. test_pipeline_fixed_code_creates_artifact
12. test_pipeline_policy_blocking_guardrails
13. test_pipeline_budget_limit_enforcement
14. test_pipeline_routing_tier_and_model_resolution
15. test_pipeline_ledger_trace_projection
16. test_pipeline_backward_compatibility
"""

import numpy  # noqa: F401
import json
import re
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
import dspy

from core.artifacts.models import ArtifactStatus, ArtifactType
from core.artifacts.service import ArtifactService
from core.execution.cancellation import CancellationToken
from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
)
from core.ledger.service import ExecutionLedgerService
from core.pipelines import (
    PipelineMetadata,
    PipelineRegistry,
    get_pipeline_registry,
    register_pipeline,
)
from core.safety.policy import PolicyEngine, PolicyRule
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import BudgetAlert, CostTracker
from services.python.server.api import app, set_execution_coordinator, set_artifact_service


@pytest.fixture
def test_storage(tmp_path):
    """Create isolated SQLite database for integration tests."""
    db_path = str(tmp_path / "test_kernel_integration.db")
    backend = SQLiteBackend(db_path=db_path)
    backend.create_project(
        {
            "id": "proj_pipeline",
            "name": "Pipeline Project",
            "root_directory": str(tmp_path / "workspace"),
            "created_at": "2026-09-20T12:00:00Z",
            "is_default": True,
        }
    )
    backend.create_project(
        {
            "id": "other_proj",
            "name": "Other Project",
            "root_directory": str(tmp_path / "other"),
            "created_at": "2026-09-20T12:00:00Z",
            "is_default": False,
        }
    )
    return backend


@pytest.fixture
def artifact_service(test_storage, tmp_path):
    """Create isolated ArtifactService."""
    artifacts_dir = str(tmp_path / "managed_artifacts")
    return ArtifactService(
        storage=test_storage,
        base_artifacts_dir=artifacts_dir,
        inline_threshold_bytes=4096,
    )


@pytest.fixture
def policy_engine():
    """Create clean in-memory PolicyEngine."""
    engine = PolicyEngine()
    engine._rules.clear()
    return engine


@pytest.fixture
def cost_tracker(test_storage):
    """Create CostTracker backed by test storage."""
    return CostTracker(storage=test_storage)


@pytest.fixture
def coordinator(test_storage, policy_engine, cost_tracker, artifact_service):
    """Create ExecutionCoordinator wired with mock dispatch override."""

    def mock_dispatch(ctx, tier, provider, model_name):
        return {
            "vulnerabilities": "None detected",
            "risk_level": "LOW",
            "fix_recommendation": "Code is secure",
            "diff_patch": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-broken\n+fixed",
            "fixed_code": "def fixed(): pass",
            "clean_code": "def clean(): pass",
            "explanation": "Bug fixed successfully",
            "response": "Execution completed",
        }

    coord = ExecutionCoordinator(
        storage=test_storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=mock_dispatch,
        artifact_service=artifact_service,
    )
    set_execution_coordinator(coord)
    set_artifact_service(artifact_service)
    return coord


@pytest.fixture
def test_client(coordinator):
    """FastAPI TestClient with isolated coordinator."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1: Direct Coordinator Pipeline Execution
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_coordinator_executes_pipeline_direct(coordinator, test_storage):
    """Verify ExecutionCoordinator executes pipeline and records canonical Execution record."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security of main.py",
        inputs={"pipeline_name": "security_audit", "code": "def run(): pass", "language": "python"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.COMPLETED
    assert result.execution_id.startswith("exec_")
    assert result.outputs.get("risk_level") == "LOW"
    assert result.total_tokens > 0

    # Verify persisted canonical execution
    stored = test_storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["project_id"] == "proj_pipeline"


# ---------------------------------------------------------------------------
# Test 2: PipelineRegistry.run delegates to ExecutionCoordinator
# ---------------------------------------------------------------------------
def test_pipeline_registry_delegates_to_coordinator(coordinator, test_storage):
    """Verify PipelineRegistry.run() delegates to ExecutionCoordinator and persists Execution."""
    registry = get_pipeline_registry()
    registry.set_coordinator(coordinator)

    initial_count = len(test_storage.list_executions(limit=100))

    outputs = registry.run(
        "security_audit",
        code="print('eval')",
        language="python",
        project_id="proj_pipeline",
    )

    assert isinstance(outputs, dict)
    assert outputs.get("risk_level") == "LOW"

    # Verify an execution was recorded in SQLite
    executions = test_storage.list_executions(limit=100)
    assert len(executions) == initial_count + 1
    newest = executions[0]
    assert newest["status"] == "completed"
    req = newest.get("request") or {}
    if isinstance(req, str):
        req = json.loads(req)
    assert req.get("task_type") == "pipeline"


# ---------------------------------------------------------------------------
# Test 3: REST Endpoint returns execution_id
# ---------------------------------------------------------------------------
def test_api_pipeline_run_returns_execution_id(test_client, test_storage):
    """Verify POST /v1/pipelines/{name}/run returns execution_id and creates canonical execution."""
    resp = test_client.post(
        "/v1/pipelines/security_audit/run",
        json={"inputs": {"code": "x = 10", "language": "python"}, "project_id": "proj_pipeline"},
        headers={"X-Project-ID": "proj_pipeline"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pipeline"] == "security_audit"
    assert "outputs" in data
    assert "execution_id" in data
    assert re.match(r"^exec_[0-9a-f]{12,16}$", data["execution_id"])

    # Verify stored in SQLite
    stored = test_storage.get_execution(data["execution_id"])
    assert stored is not None
    assert stored["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 4: Single Root Execution Invariant for Multi-Hop Pipelines
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_single_root_execution_multi_hop_pipeline(coordinator, test_storage):
    """Verify multi-hop DSPy pipelines produce exactly one root Execution record."""
    coordinator._dispatch_override = lambda ctx, tier, prov, model: {
        "ast_data": "tree_representation",
        "score": "95",
    }
    reg = PipelineRegistry(coordinator=coordinator)

    class TwoHopModule(dspy.Module):
        def __init__(self):
            super().__init__()
            self.step1 = dspy.Predict("code -> ast_data")
            self.step2 = dspy.Predict("ast_data -> score")

        def forward(self, code: str):
            s1 = self.step1(code=code)
            s2 = self.step2(ast_data=s1.ast_data)
            return {"ast_data": s1.ast_data, "score": s2.score}

    reg.register(
        TwoHopModule,
        PipelineMetadata(
            name="two_hop_audit",
            description="Two-hop audit pipeline",
            inputs=["code"],
            outputs=["ast_data", "score"],
            category="code",
        ),
    )

    coordinator.pipeline_registry = reg
    initial_count = len(test_storage.list_executions(limit=100))

    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Run two hop audit",
        inputs={"pipeline_name": "two_hop_audit", "code": "def test(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    # Verify exactly 1 execution record was created
    executions = test_storage.list_executions(limit=100)
    assert len(executions) == initial_count + 1
    assert executions[0]["id"] == result.execution_id


# ---------------------------------------------------------------------------
# Test 5: Truthful Multi-Model Accounting without Double Counting
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_multi_model_truthful_accounting(coordinator, test_storage):
    """Verify internal DSPy LM calls accumulate tokens and cost truthfully into parent execution."""
    reg = PipelineRegistry(coordinator=coordinator)

    call_count = 0

    def mock_dispatch(ctx, tier, prov, model):
        nonlocal call_count
        call_count += 1
        return {"step_out": f"step_{call_count}_done"}

    coordinator._dispatch_override = mock_dispatch

    class MultiStepModule(dspy.Module):
        def __init__(self):
            super().__init__()
            self.p1 = dspy.Predict("text_in -> step_out")
            self.p2 = dspy.Predict("step_in -> step_out")

        def forward(self, text: str):
            r1 = self.p1(text_in=text)
            r2 = self.p2(step_in=r1.step_out)
            return {"final": r2.step_out}

    reg.register(
        MultiStepModule,
        PipelineMetadata(
            name="multi_step",
            description="Multi-step pipeline",
            inputs=["text"],
            outputs=["final"],
        ),
    )

    coordinator.pipeline_registry = reg
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Run multi-step",
        inputs={"pipeline_name": "multi_step", "text": "start processing"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED
    assert call_count == 2
    assert result.total_tokens > 0
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


# ---------------------------------------------------------------------------
# Test 6: Context Provenance Records Pipeline Identity
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_context_provenance_pipeline_identity(coordinator, test_storage):
    """Verify execution context provenance records pipeline identity accurately."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security",
        inputs={"pipeline_name": "security_audit", "code": "def foo(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    # Check durable events for context_provenance
    events = test_storage.get_execution_events(result.execution_id)
    routing_events = [
        e for e in events if e.get("event_type") == ExecutionEventType.ROUTING_RESOLVED.value
    ]
    assert len(routing_events) > 0
    prov = routing_events[0].get("payload", {}).get("context_provenance", {})
    assert prov.get("pipeline_name") == "security_audit"
    assert prov.get("pipeline_version") == "1.0.0"
    assert prov.get("pipeline_category") == "code"
    assert prov.get("pipeline_author") == "Agent Engine"


# ---------------------------------------------------------------------------
# Test 7: Pipeline Cancellation Propagation
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_cancellation_propagation(coordinator, test_storage):
    """Verify cancellation halts pipeline execution promptly and sets CANCELLED state."""
    token = CancellationToken("test_token")
    token.cancel(reason="test abort", actor="tester")

    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security",
        inputs={"pipeline_name": "security_audit", "code": "def foo(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req, cancellation_token=token)
    assert result.status == ExecutionStatus.CANCELLED
    assert result.error_code == "CANCELLED"

    stored = test_storage.get_execution(result.execution_id)
    assert stored["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Test 8: Pipeline Cancellation Creates Partial Artifact
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_cancellation_creates_partial_artifact(coordinator, artifact_service):
    """Verify cancelled pipeline with partial output creates a PARTIAL artifact."""
    token = CancellationToken("test_art_cancel")

    def mock_dispatch_with_cancel(ctx, tier, prov, model):
        token.cancel(reason="mid-flight abort", actor="test_user")
        return {"vulnerabilities": "Partial scan complete"}

    coordinator._dispatch_override = mock_dispatch_with_cancel

    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security",
        inputs={"pipeline_name": "security_audit", "code": "def foo(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req, cancellation_token=token)
    assert result.status == ExecutionStatus.CANCELLED

    # Check for created partial artifacts
    artifacts = artifact_service.list_artifacts_by_execution(result.execution_id)
    assert len(artifacts) > 0
    partial_art = artifacts[0]
    assert partial_art.status == ArtifactStatus.PARTIAL
    assert "partial_output" in partial_art.name


# ---------------------------------------------------------------------------
# Test 9: Code Fix Diff Patch Creates PATCH Artifact
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_diff_patch_creates_artifact(coordinator, artifact_service):
    """Verify code_fix pipeline output diff_patch produces a canonical PATCH artifact."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Fix bug in main.py",
        inputs={"pipeline_name": "code_fix", "code": "broken", "issue_description": "Fix bug"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    artifacts = artifact_service.list_artifacts_by_execution(result.execution_id)
    patch_arts = [a for a in artifacts if a.type == ArtifactType.PATCH]
    assert len(patch_arts) == 1
    art = patch_arts[0]
    assert art.name == "diff.patch"
    assert art.mime_type == "text/x-diff"
    assert art.status == ArtifactStatus.READY
    assert art.id in result.artifacts_created


# ---------------------------------------------------------------------------
# Test 10: Security Audit Vulnerabilities Creates Analysis Artifact
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_vulnerabilities_creates_artifact(coordinator, artifact_service):
    """Verify security_audit pipeline vulnerabilities produces a canonical data/analysis artifact."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security",
        inputs={"pipeline_name": "security_audit", "code": "def secure(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    artifacts = artifact_service.list_artifacts_by_execution(result.execution_id)
    vuln_arts = [a for a in artifacts if "vulnerabilities" in a.name]
    assert len(vuln_arts) == 1
    art = vuln_arts[0]
    assert art.status == ArtifactStatus.READY
    assert art.id in result.artifacts_created


# ---------------------------------------------------------------------------
# Test 11: Code Fix Fixed Code Creates CODE Artifact
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_fixed_code_creates_artifact(coordinator, artifact_service):
    """Verify fixed_code in pipeline output produces a canonical CODE artifact."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Fix code",
        inputs={"pipeline_name": "code_fix", "code": "broken", "issue_description": "Fix bug"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    artifacts = artifact_service.list_artifacts_by_execution(result.execution_id)
    code_arts = [a for a in artifacts if a.type == ArtifactType.CODE]
    assert len(code_arts) == 1
    art = code_arts[0]
    assert art.name == "fixed_code.py"
    assert art.mime_type == "text/x-python"
    assert art.status == ArtifactStatus.READY
    assert art.id in result.artifacts_created


# ---------------------------------------------------------------------------
# Test 12: Safety Policy Blocking via Declared Guardrails
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_policy_blocking_guardrails(coordinator, policy_engine):
    """Verify guardrail policy rules block pipeline execution pre-flight."""
    # Add blocking rule for code_injection_check
    rule = PolicyRule(
        id="rule_inj_block",
        name="Block Injection",
        description="Blocks harmful injection payloads",
        match_type="keyword",
        pattern="EVIL_PAYLOAD_DROP_DB",
        action="block",
        reason="Malicious code injection detected",
    )
    policy_engine.add_rule(rule)

    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit suspicious code",
        inputs={"pipeline_name": "security_audit", "code": "EVIL_PAYLOAD_DROP_DB"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.BLOCKED
    assert result.error_code == "POLICY_BLOCKED"
    assert "Malicious code injection" in (result.error or "")


# ---------------------------------------------------------------------------
# Test 13: Budget Limit Enforces BLOCKED Status
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_budget_limit_enforcement(coordinator, cost_tracker):
    """Verify budget alerts block pipeline execution with BUDGET_EXCEEDED."""
    critical_alert = BudgetAlert(
        project="proj_pipeline",
        period="monthly",
        current_spend=100.0,
        budget_limit=50.0,
        percentage=200.0,
        level="critical",
        message="Monthly budget exceeded",
    )
    with patch.object(cost_tracker, "check_budget_alerts", return_value=[critical_alert]):
        req = ExecutionRequest(
            task_type="pipeline",
            prompt="Audit security",
            inputs={"pipeline_name": "security_audit", "code": "def ok(): pass"},
            project_id="proj_pipeline",
        )
        result = await coordinator.execute(req)
        assert result.status == ExecutionStatus.BLOCKED
        assert result.error_code == "BUDGET_EXCEEDED"


# ---------------------------------------------------------------------------
# Test 14: Routing Tier and Model Resolution Recorded
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_routing_tier_and_model_resolution(coordinator):
    """Verify model router resolves tier and model for pipeline execution."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Audit security",
        inputs={"pipeline_name": "security_audit", "code": "def ok(): pass"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.routing_tier is not None
    assert result.model_used is not None
    assert result.provider_used is not None


# ---------------------------------------------------------------------------
# Test 15: ExecutionLedgerService Trace Projection for Pipeline
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_pipeline_ledger_trace_projection(coordinator, test_storage, artifact_service):
    """Verify ExecutionLedgerService projects pipeline trace with provenance and artifacts."""
    req = ExecutionRequest(
        task_type="pipeline",
        prompt="Fix code bug",
        inputs={"pipeline_name": "code_fix", "code": "broken", "issue_description": "Fix bug"},
        project_id="proj_pipeline",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    ledger = ExecutionLedgerService(storage=test_storage)
    trace = ledger.get_execution_trace(result.execution_id, project_id="proj_pipeline")
    assert trace is not None
    assert trace.execution_id == result.execution_id
    assert trace.status == ExecutionStatus.COMPLETED
    assert trace.context_provenance.get("pipeline_name") == "code_fix"
    assert len(trace.artifacts) > 0
    art_names = [a.name for a in trace.artifacts]
    assert "diff.patch" in art_names


# ---------------------------------------------------------------------------
# Test 16: PipelineRegistry Backward Compatibility
# ---------------------------------------------------------------------------
def test_pipeline_backward_compatibility():
    """Verify all existing PipelineRegistry APIs remain functional and backward compatible."""
    reg = PipelineRegistry()

    @register_pipeline(
        name="compat_test",
        description="Compatibility test pipeline",
        inputs=["val"],
        outputs=["res"],
        category="testing",
        registry=reg,
    )
    class CompatModule(dspy.Module):
        def forward(self, val: int):
            return {"res": val * 2}

    assert reg.get("compat_test") is CompatModule
    meta = reg.get_metadata("compat_test")
    assert meta is not None
    assert meta.name == "compat_test"

    pipelines = reg.list_pipelines()
    assert any(p.name == "compat_test" for p in pipelines)

    instance = reg.instantiate("compat_test")
    assert isinstance(instance, CompatModule)

    assert reg.unregister("compat_test") is True
    assert reg.get("compat_test") is None

    # Test KeyError on missing
    with pytest.raises(KeyError):
        reg.instantiate("missing_pipeline")
    with pytest.raises(KeyError):
        reg.run("missing_pipeline")
