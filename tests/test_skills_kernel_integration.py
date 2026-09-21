"""Comprehensive Integration Tests for Skills and Adapters Rewired into ExecutionCoordinator (Task R1.13).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md (R1.13)

Validates all 18 canonical requirements:
1. test_skill_invoked_through_coordinator_succeeds_under_active_budget
2. test_budget_exceeded_rejects_skill_execution
3. test_policy_check_blocks_forbidden_skill
4. test_consequential_skill_requires_human_approval
5. test_invocations_record_complete_provenance
6. test_tool_invocation_record_emitted_with_duration_status_digest
7. test_sensitive_arguments_redacted_in_invocation_record
8. test_skill_producing_artifacts_registers_them_in_artifact_service
9. test_skill_failure_recorded_truthfully_as_failed_with_error
10. test_cancellation_halts_skill_execution_promptly
11. test_subprocess_execution_routed_through_capability_boundary_not_raw_os
12. test_file_access_outside_project_root_rejected
13. test_permission_check_validates_declared_permissions_against_context
14. test_undeclared_permission_attempt_rejected
15. test_adapter_invoked_through_coordinator_succeeds
16. test_adapter_cancellation_terminates_underlying_process_cleanly
17. test_adapter_timeout_handled_truthfully
18. test_concurrent_skill_invocations_within_single_execution_tracked_independently
"""

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from core.adapters import (
    AdapterCapability,
    AdapterRegistry,
    AgentAdapter,
    MockAgentAdapter,
)
from core.adapters.base import AdapterExecutionResponse, AdapterStreamChunk
from core.artifacts.models import ArtifactType
from core.artifacts.service import ArtifactService
from core.execution.cancellation import CancellationToken, CancellationReason
from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionRequest,
    ExecutionStatus,
)
from core.ledger.service import ExecutionLedgerService
from core.safety.policy import PolicyEngine, PolicyRule
from core.skills import (
    CapabilityBoundary,
    SkillDiscovery,
    SkillPermission,
    check_permission,
    validate_project_path,
)
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import BudgetAlert, CostTracker
from services.python.server.api import set_execution_coordinator, set_artifact_service


@pytest.fixture
def test_storage(tmp_path):
    """Create isolated SQLite database for integration tests."""
    db_path = str(tmp_path / "test_skills_kernel_integration.db")
    backend = SQLiteBackend(db_path=db_path)
    backend.create_project(
        {
            "id": "proj_skills",
            "name": "Skills Project",
            "root_directory": str(tmp_path / "workspace"),
            "created_at": "2026-09-21T10:00:00Z",
            "is_default": True,
        }
    )
    os.makedirs(str(tmp_path / "workspace"), exist_ok=True)
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
def ledger_service(test_storage):
    """Create isolated ExecutionLedgerService."""
    return ExecutionLedgerService(storage=test_storage)


@pytest.fixture
def adapter_registry():
    """Create fresh isolated AdapterRegistry."""
    return AdapterRegistry()


@pytest.fixture
def skill_discovery(tmp_path):
    """Create isolated SkillDiscovery."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    return SkillDiscovery(agent_engine_dirs=[skills_dir])


@pytest.fixture
def coordinator(
    test_storage,
    policy_engine,
    cost_tracker,
    artifact_service,
    adapter_registry,
    skill_discovery,
    tmp_path,
):
    """Create ExecutionCoordinator wired with all isolated subsystems."""

    def mock_dispatch(ctx, tier, provider, model_name):
        return {
            "response": "Execution completed successfully",
            "results": {"status": "ok", "output": "Mock skill output"},
        }

    coord = ExecutionCoordinator(
        storage=test_storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        dispatch_override=mock_dispatch,
        artifact_service=artifact_service,
        adapter_registry=adapter_registry,
        skill_discovery=skill_discovery,
    )
    set_execution_coordinator(coord)
    set_artifact_service(artifact_service)
    return coord


# ---------------------------------------------------------------------------
# Test 1: Skill Invocation Under Active Budget
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_skill_invoked_through_coordinator_succeeds_under_active_budget(
    coordinator, test_storage, skill_discovery, tmp_path
):
    """Verify skill execution succeeds under active budget and writes canonical record."""
    # Create sample skill in discovery path
    skill_file = tmp_path / "skills" / "summarize.md"
    skill_file.write_text(
        "---\nname: Summarize\ndescription: Summarize text\npermissions: [read]\n---\nSummarize the input.",
        encoding="utf-8",
    )

    req = ExecutionRequest(
        task_type="skill",
        prompt="Summarize meeting",
        inputs={"skill_id": "summarize", "text": "Standup discussion"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)

    assert result.status == ExecutionStatus.COMPLETED
    assert result.execution_id.startswith("exec_")
    assert result.outputs is not None
    assert result.total_tokens > 0

    # Verify execution stored in SQLite
    stored = test_storage.get_execution(result.execution_id)
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["project_id"] == "proj_skills"


# ---------------------------------------------------------------------------
# Test 2: Budget Exceeded Rejection
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_budget_exceeded_rejects_skill_execution(coordinator, cost_tracker):
    """Verify budget exhaustion blocks skill execution pre-flight."""
    critical_alert = BudgetAlert(
        project="proj_skills",
        period="monthly",
        current_spend=150.0,
        budget_limit=50.0,
        percentage=300.0,
        level="critical",
        message="Monthly project budget exceeded",
    )
    with patch.object(cost_tracker, "check_budget_alerts", return_value=[critical_alert]):
        req = ExecutionRequest(
            task_type="skill",
            prompt="Execute expensive skill",
            inputs={"skill_id": "summarize_meeting_notes"},
            project_id="proj_skills",
        )
        result = await coordinator.execute(req)
        assert result.status == ExecutionStatus.BLOCKED
        assert result.error_code == "BUDGET_EXCEEDED"
        assert "budget" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Test 3: Policy Check Blocks Forbidden Skill
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_policy_check_blocks_forbidden_skill(coordinator, policy_engine):
    """Verify policy engine blocks forbidden skill execution pre-flight."""
    rule = PolicyRule(
        id="rule_block_forbidden_skill",
        name="Block Forbidden Skill",
        description="Blocks forbidden skill invocation",
        match_type="exact",
        pattern="skill:forbidden_exploit_skill",
        action="block",
        reason="Exploit skill is banned by organizational policy",
    )
    policy_engine.add_rule(rule)

    req = ExecutionRequest(
        task_type="skill",
        prompt="Execute exploit",
        inputs={"skill_id": "forbidden_exploit_skill"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.BLOCKED
    assert result.error_code == "POLICY_BLOCKED"
    assert "Exploit skill is banned" in (result.error or "")


# ---------------------------------------------------------------------------
# Test 4: Consequential Skill Requires Human Approval
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_consequential_skill_requires_human_approval(coordinator, skill_discovery, tmp_path):
    """Verify consequential or destructive skill stages operation and halts for approval."""
    destructive_file = tmp_path / "skills" / "deploy_prod.md"
    destructive_file.write_text(
        "---\nname: Deploy Prod\ndescription: Deploy to production\nconsequential: true\npermissions: [destructive, execute]\n---\nDeploy.",
        encoding="utf-8",
    )

    req = ExecutionRequest(
        task_type="skill",
        prompt="Deploy to prod",
        inputs={"skill_id": "deploy_prod", "target_env": "production"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status in (ExecutionStatus.BLOCKED, ExecutionStatus.WAITING_FOR_APPROVAL)
    reason = result.error or result.outputs.get("reason", "")
    assert "requires human approval" in reason

    # Verify staged pending operation exists
    pending_ops = coordinator.pending_registry.list_operations(status="pending")
    assert len(pending_ops) >= 1
    assert pending_ops[0].tool_name == "skill:deploy_prod"
    assert pending_ops[0].status == "pending"


# ---------------------------------------------------------------------------
# Test 5: Invocations Record Complete Provenance
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_invocations_record_complete_provenance(
    coordinator, ledger_service, skill_discovery, tmp_path
):
    """Verify ContextProvenance captures skill identity, version, source, and implementation hash."""
    skill_file = tmp_path / "skills" / "prov_skill.md"
    content = (
        "---\nname: Provenance Skill\nversion: 2.1.0\npermissions: [read]\n---\nStep 1. Read files."
    )
    skill_file.write_text(content, encoding="utf-8")

    req = ExecutionRequest(
        task_type="skill",
        prompt="Run provenance skill",
        inputs={"skill_id": "prov_skill"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id, project_id="proj_skills")
    assert trace is not None
    assert trace.context is not None
    assert trace.context.skill_id == "prov_skill"
    assert trace.context.skill_version == "2.1.0"
    assert trace.context.skill_source in ("filesystem", "agent-engine")
    assert trace.context.skill_implementation_hash is not None
    assert len(trace.context.skill_implementation_hash) == 64  # SHA-256


# ---------------------------------------------------------------------------
# Test 6: ToolInvocationRecord Emitted With Duration, Status, Digest
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tool_invocation_record_emitted_with_duration_status_digest(
    coordinator, ledger_service, skill_discovery, tmp_path
):
    """Verify tool invocation record has duration_ms, status=completed, and arguments_digest."""
    skill_file = tmp_path / "skills" / "digest_skill.md"
    skill_file.write_text(
        "---\nname: Digest Skill\nversion: 1.0.0\npermissions: [read]\n---\nExecute.",
        encoding="utf-8",
    )

    req = ExecutionRequest(
        task_type="skill",
        prompt="Run digest skill",
        inputs={"skill_id": "digest_skill", "query": "test query"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id, project_id="proj_skills")
    assert trace is not None
    assert len(trace.tools) >= 1

    inv = trace.tools[0]
    assert inv.invocation_id.startswith("inv_")
    assert inv.tool_id == "skill:digest_skill"
    assert inv.status == "completed"
    assert inv.duration_ms is not None and inv.duration_ms >= 0.0
    assert inv.arguments_digest is not None
    assert len(inv.arguments_digest) == 64


# ---------------------------------------------------------------------------
# Test 7: Sensitive Arguments Redacted in Invocation Record
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_sensitive_arguments_redacted_in_invocation_record(
    coordinator, ledger_service, skill_discovery, tmp_path
):
    """Verify credentials and API keys are redacted in invocation records."""
    skill_file = tmp_path / "skills" / "secret_skill.md"
    skill_file.write_text(
        "---\nname: Secret Skill\nversion: 1.0.0\npermissions: [read]\n---\nExecute.",
        encoding="utf-8",
    )

    secret_key = "sk-proj-super-secret-key-12345"
    password = "p@ssw0rd999!"
    req = ExecutionRequest(
        task_type="skill",
        prompt="Process secrets",
        inputs={
            "skill_id": "secret_skill",
            "api_key": secret_key,
            "password": password,
            "public_param": "hello",
        },
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    trace = ledger_service.get_execution_trace(result.execution_id, project_id="proj_skills")
    assert trace is not None
    inv = trace.tools[0]

    redacted_args = inv.requested_args_redacted or {}
    assert redacted_args.get("api_key") == "[REDACTED]"
    assert redacted_args.get("password") == "[REDACTED]"
    assert redacted_args.get("public_param") == "hello"

    # Raw secret must never appear in raw stringified trace tools
    assert secret_key not in json.dumps(inv.to_public_dict())
    assert password not in json.dumps(inv.to_public_dict())


# ---------------------------------------------------------------------------
# Test 8: Skill Producing Artifacts Registers in ArtifactService
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_skill_producing_artifacts_registers_them_in_artifact_service(
    coordinator, artifact_service
):
    """Verify artifacts emitted by a skill are persisted in ArtifactService."""

    async def skill_with_artifacts(ctx, boundary, **kwargs):
        return {
            "response": "Generated patch and code",
            "artifact_candidates": [
                {
                    "name": "code_fixer_patch.diff",
                    "content": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
                    "type": ArtifactType.PATCH,
                    "mime_type": "text/x-diff",
                },
                {
                    "name": "code_fixer_fixed.py",
                    "content": "def solve(): return 42",
                    "type": ArtifactType.CODE,
                    "mime_type": "text/x-python",
                },
            ],
        }

    req = ExecutionRequest(
        task_type="skill",
        prompt="Fix bug",
        inputs={"skill_id": "code_fixer", "skill_callable": skill_with_artifacts},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED

    artifacts = artifact_service.list_artifacts_by_execution(result.execution_id)
    assert len(artifacts) >= 2
    types = {a.type for a in artifacts}
    assert ArtifactType.PATCH in types or ArtifactType.DIFF in types
    assert ArtifactType.CODE in types


# ---------------------------------------------------------------------------
# Test 9: Skill Failure Recorded Truthfully as FAILED with Error
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_skill_failure_recorded_truthfully_as_failed_with_error(coordinator, ledger_service):
    """Verify skill exceptions result in FAILED status, recorded truthfully with error detail."""

    async def failing_skill(ctx, boundary, **kwargs):
        raise RuntimeError("Skill database connection refused")

    req = ExecutionRequest(
        task_type="skill",
        prompt="Run failing skill",
        inputs={"skill_id": "failing_skill", "skill_callable": failing_skill},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.FAILED
    assert "Skill database connection refused" in (result.error or "")

    # Verify ledger trace reflects truthful failure
    trace = ledger_service.get_execution_trace(result.execution_id, project_id="proj_skills")
    assert trace is not None
    assert len(trace.tools) >= 1
    assert trace.tools[0].status == "failed"
    assert "connection refused" in (trace.tools[0].error or "")


# ---------------------------------------------------------------------------
# Test 10: Cancellation Halts Skill Execution Promptly
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_cancellation_halts_skill_execution_promptly(coordinator):
    """Verify cancellation token halts skill execution promptly."""
    token = CancellationToken("test_cancel")
    token.cancel(reason=CancellationReason.USER_REQUEST, actor="user")

    req = ExecutionRequest(
        task_type="skill",
        prompt="Run cancelled skill",
        inputs={"skill_id": "summarize_meeting_notes"},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req, cancellation_token=token)
    assert result.status == ExecutionStatus.CANCELLED
    assert "cancelled" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Test 11: Subprocess Execution Routed Through CapabilityBoundary
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_subprocess_execution_routed_through_capability_boundary_not_raw_os(tmp_path):
    """Verify subprocess calls execute through CapabilityBoundary with EXECUTE permission."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)

    # 1. Allowed when EXECUTE is declared
    boundary_allowed = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.EXECUTE],
    )
    res = await boundary_allowed.run_subprocess(["echo", "boundary_test_ok"])
    returncode, stdout, stderr = res
    assert returncode == 0
    assert "boundary_test_ok" in stdout

    # 2. Rejected when EXECUTE is omitted
    boundary_forbidden = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ],
    )
    with pytest.raises(PermissionError) as exc_info:
        await boundary_forbidden.run_subprocess(["echo", "should_fail"])
    assert "Permission 'execute' is required" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 12: File Access Outside Project Root Rejected
# ---------------------------------------------------------------------------
def test_file_access_outside_project_root_rejected(tmp_path):
    """Verify paths escaping project root boundary raise PermissionError or ValueError."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)

    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ, SkillPermission.WRITE_LOCAL],
    )

    # Traversal escape
    with pytest.raises((PermissionError, ValueError)):
        boundary.read_file("../../etc/passwd")

    # Absolute path escape outside workspace
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("forbidden", encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        boundary.read_file(str(outside_file))

    # Write outside workspace
    with pytest.raises((PermissionError, ValueError)):
        boundary.write_file("../escape.txt", "data")

    # Direct validation helper check
    with pytest.raises((PermissionError, ValueError)):
        validate_project_path(workspace, "../escape.txt")


# ---------------------------------------------------------------------------
# Test 13: Permission Check Validates Declared Permissions Against Context
# ---------------------------------------------------------------------------
def test_permission_check_validates_declared_permissions_against_context(tmp_path):
    """Verify check_permission enforces presence of requested capability permission."""
    workspace = tmp_path / "workspace"
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ, SkillPermission.WRITE_LOCAL],
    )

    assert check_permission(boundary, SkillPermission.READ) is True
    assert check_permission(boundary, SkillPermission.WRITE_LOCAL) is True

    with pytest.raises(PermissionError) as exc_info:
        check_permission(boundary, SkillPermission.NETWORK)
    assert "Permission 'network' is required" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 14: Undeclared Permission Attempt Rejected
# ---------------------------------------------------------------------------
def test_undeclared_permission_attempt_rejected(tmp_path):
    """Verify skill without WRITE_LOCAL cannot write files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    boundary = CapabilityBoundary(
        project_root=workspace,
        declared_permissions=[SkillPermission.READ],
    )

    with pytest.raises(PermissionError) as exc_info:
        boundary.write_file("test.txt", "content")
    assert "Permission 'write_local' is required" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 15: Adapter Invocation Through Coordinator Succeeds
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_adapter_invoked_through_coordinator_succeeds(
    coordinator, adapter_registry, ledger_service
):
    """Verify agent adapter executes through coordinator with durable tool invocation events."""
    test_adapter = MockAgentAdapter(
        adapter_id="mock_kernel_adapter",
        name="Kernel Mock Adapter",
        description="Deterministic adapter for coordinator test",
        capabilities=[AdapterCapability.TOOLS, AdapterCapability.STREAMING],
    )
    adapter_registry.register(test_adapter)

    req = ExecutionRequest(
        task_type="adapter",
        prompt="Hello from kernel test",
        inputs={
            "adapter_id": "mock_kernel_adapter",
            "model": "instant",
            "temperature": 0.2,
        },
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.outputs.get("adapter_id") == "mock_kernel_adapter"
    assert "Hello from kernel test" in result.outputs.get("content", "")

    # Verify ledger trace captured tool invocation
    trace = ledger_service.get_execution_trace(result.execution_id, project_id="proj_skills")
    assert trace is not None
    assert len(trace.tools) >= 1
    assert trace.tools[0].tool_id == "adapter:mock_kernel_adapter"
    assert trace.tools[0].status == "completed"


# ---------------------------------------------------------------------------
# Test 16: Adapter Cancellation Terminates Underlying Process Cleanly
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_adapter_cancellation_terminates_underlying_process_cleanly(
    coordinator, adapter_registry
):
    """Verify cancelling adapter execution invokes stop() and halts cleanly."""
    stop_called = False

    class SlowStoppableAdapter(AgentAdapter):
        def __init__(self):
            super().__init__(
                adapter_id="slow_stoppable",
                name="Slow Stoppable",
                description="Hangs until cancelled",
                protocol="cli",
            )
            self._initialized = True

        def initialize(self):
            return True

        def health_check(self):
            return MagicMock(status="healthy")

        async def execute(self, req):
            await asyncio.sleep(10.0)
            return AdapterExecutionResponse(adapter_id="slow_stoppable", content="Done")

        async def stream(self, req):
            await asyncio.sleep(10.0)
            yield AdapterStreamChunk(chunk_type="token", delta="Done")

        def stop(self):
            nonlocal stop_called
            stop_called = True

    adapter_registry.register(SlowStoppableAdapter())

    token = CancellationToken("cancel_adapter")
    req = ExecutionRequest(
        task_type="adapter",
        prompt="Long task",
        inputs={"adapter_id": "slow_stoppable"},
        project_id="proj_skills",
    )

    # Cancel after 50ms
    async def cancel_later():
        await asyncio.sleep(0.05)
        token.cancel(reason=CancellationReason.USER_REQUEST, actor="user")

    asyncio.create_task(cancel_later())
    result = await coordinator.execute(req, cancellation_token=token)

    assert result.status == ExecutionStatus.CANCELLED
    assert stop_called is True


# ---------------------------------------------------------------------------
# Test 17: Adapter Timeout Handled Truthfully
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_adapter_timeout_handled_truthfully(coordinator, adapter_registry):
    """Verify adapter timeout results in FAILED status with truthful error, zero fake success."""

    class TimeoutAdapter(AgentAdapter):
        def __init__(self):
            super().__init__(
                adapter_id="timeout_adapter",
                name="Timeout Adapter",
                description="Exceeds timeout limit",
                protocol="cli",
            )
            self._initialized = True

        def initialize(self):
            return True

        def health_check(self):
            return MagicMock(status="healthy")

        async def execute(self, req):
            await asyncio.sleep(2.0)
            return AdapterExecutionResponse(adapter_id="timeout_adapter", content="Late")

        async def stream(self, req):
            await asyncio.sleep(2.0)
            yield AdapterStreamChunk(chunk_type="token", delta="Late")

        def stop(self):
            pass

    adapter_registry.register(TimeoutAdapter())

    req = ExecutionRequest(
        task_type="adapter",
        prompt="Timeout query",
        inputs={"adapter_id": "timeout_adapter", "timeout_seconds": 0.1},
        project_id="proj_skills",
    )

    result = await coordinator.execute(req)
    assert result.status == ExecutionStatus.FAILED
    assert "timed out" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Test 18: Concurrent Skill Invocations Within Single Execution Tracked Independently
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_concurrent_skill_invocations_within_single_execution_tracked_independently(
    coordinator, test_storage, ledger_service, tmp_path
):
    """Verify concurrent invoke_skill calls within a single execution produce distinct invocation records."""
    # First create root execution
    req = ExecutionRequest(
        task_type="root_task",
        prompt="Orchestrate multiple skills",
        project_id="proj_skills",
    )
    result = await coordinator.execute(req)
    exec_id = result.execution_id

    # Two distinct concurrent skill functions
    async def skill_fn_1(boundary, **kwargs):
        await asyncio.sleep(0.02)
        return {"result": "skill_1_done", "val": kwargs.get("x")}

    async def skill_fn_2(boundary, **kwargs):
        await asyncio.sleep(0.02)
        return {"result": "skill_2_done", "val": kwargs.get("y")}

    # Invoke concurrently within same execution
    res1, res2 = await asyncio.gather(
        coordinator.invoke_skill(
            exec_id,
            "skill_one",
            inputs={"x": 101},
            declared_permissions=[SkillPermission.READ],
            skill_callable=skill_fn_1,
        ),
        coordinator.invoke_skill(
            exec_id,
            "skill_two",
            inputs={"y": 202},
            declared_permissions=[SkillPermission.READ],
            skill_callable=skill_fn_2,
        ),
    )

    assert res1["result"] == "skill_1_done"
    assert res2["result"] == "skill_2_done"

    # Verify ledger trace has 2 independent ToolInvocationRecords
    trace = ledger_service.get_execution_trace(exec_id, project_id="proj_skills")
    assert trace is not None
    assert len(trace.tools) == 2

    inv1, inv2 = trace.tools[0], trace.tools[1]
    assert inv1.invocation_id != inv2.invocation_id
    assert inv1.tool_id != inv2.tool_id
    assert inv1.status == "completed"
    assert inv2.status == "completed"
    assert inv1.duration_ms is not None and inv1.duration_ms >= 0.0
    assert inv2.duration_ms is not None and inv2.duration_ms >= 0.0
