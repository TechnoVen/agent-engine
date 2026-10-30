"""
R2 Package 2 Security Verification Suite:
- R2.3 Mandatory Backend Policy Boundary
- R2.4 Exact-Operation Approval Tokens

Verifies:
1. Consequential operations cannot bypass PolicyEngine
2. Policy DENY prevents execution
3. REQUIRE_APPROVAL stages execution (WAITING_FOR_APPROVAL)
4. ALLOW permits low-risk execution
5. Evaluation error fails closed
6. Approval binds exact capability/tool
7. Approval binds canonical argument digest
8. Changed argument invalidates approval
9. Changed target path invalidates approval
10. Expired approval fails
11. Approval is single-use
12. Concurrent race test: double-consumption permits only one winner
13. Replay fails with security violation
14. Rejection cannot later be approved/consumed
15. Execution ID mismatch invalidates approval
16. Ledger records request, decision, and consumption
17. Raw secret arguments are redacted from approval evidence
18. Frontend cannot forge approval (approved=true ignored without token)
"""

from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import patch

import pytest

from core.execution.coordinator import ExecutionCoordinator
from core.execution.models import (
    ExecutionEventType,
    ExecutionRequest,
    ExecutionStatus,
)
from core.ledger.service import LedgerService
from core.safety.pending import (
    OPERATION_DIGEST_VERSION,
    OperationExpiredError,
    PendingOperationRegistry,
    SecurityBoundaryViolation,
    compute_canonical_operation_digest,
    redact_sensitive_data,
)
from core.safety.policy import PolicyEngine, PolicyRule
from core.skills.boundary import CapabilityBoundary
from core.skills.models import SkillPermission
from core.storage.sqlite import SQLiteBackend
from core.telemetry.cost import CostTracker
from fastapi import HTTPException
from services.python.server.dependencies import IPCTokenManager


@pytest.fixture
def test_env(tmp_path):
    """Provide isolated ExecutionCoordinator environment."""
    db_path = str(tmp_path / "test_r2_policy.db")
    storage = SQLiteBackend(db_path=db_path)
    policy_engine = PolicyEngine(policy_file=str(tmp_path / "policies.yaml"))
    cost_tracker = CostTracker(storage=storage)
    pending_registry = PendingOperationRegistry(default_ttl_seconds=60.0)

    dispatched = []

    def fake_dispatch(ctx, tier, prov, model):
        dispatched.append({"exec_id": ctx.execution_id, "prompt": ctx.prompt})
        return {
            "response": f"Executed prompt: {ctx.prompt}",
            "execution_id": ctx.execution_id,
        }

    coordinator = ExecutionCoordinator(
        storage=storage,
        policy_engine=policy_engine,
        cost_tracker=cost_tracker,
        pending_registry=pending_registry,
        dispatch_override=fake_dispatch,
    )

    ledger_service = LedgerService(storage=storage)

    return {
        "coordinator": coordinator,
        "storage": storage,
        "policy_engine": policy_engine,
        "pending_registry": pending_registry,
        "ledger_service": ledger_service,
        "dispatched": dispatched,
    }


# ============================================================================
# Phase 2A: R2.3 Mandatory Backend Policy Boundary Tests
# ============================================================================


class TestPolicyBoundary:
    @pytest.mark.anyio
    async def test_consequential_operation_cannot_bypass_policy_engine(self, test_env):
        """1. Consequential operation cannot bypass PolicyEngine and is staged."""
        coordinator = test_env["coordinator"]
        dispatched = test_env["dispatched"]

        # High-risk destructive command
        req = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Clean build cache",
            task_type="command",
            inputs={
                "tool_name": "run_command",
                "tool_args": {"command": "rm -rf /tmp/test_dir"},
            },
        )

        result = await coordinator.execute(req)

        assert result.status == ExecutionStatus.WAITING_FOR_APPROVAL
        assert result.outputs is not None
        assert result.outputs.get("approval_required") is True
        assert len(dispatched) == 0  # Dispatch override was NOT called

    @pytest.mark.anyio
    async def test_policy_deny_prevents_execution(self, test_env):
        """2. Policy DENY prevents execution completely."""
        coordinator = test_env["coordinator"]
        policy_engine = test_env["policy_engine"]
        dispatched = test_env["dispatched"]

        # Add explicit blocking rule
        policy_engine.add_rule(
            PolicyRule(
                id="RULE_BLOCK_DROP_DB",
                name="Block Drop Database",
                description="Prevent dropping databases",
                match_type="regex",
                pattern=r"drop\s+database",
                action="block",
                reason="Direct database drops are forbidden by policy",
            )
        )

        req = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Drop old records",
            task_type="command",
            inputs={
                "tool_name": "sql_exec",
                "tool_args": {"query": "DROP DATABASE production_db;"},
            },
        )

        result = await coordinator.execute(req)

        assert result.status == ExecutionStatus.BLOCKED
        assert result.error_code == "POLICY_BLOCKED"
        assert "Direct database drops are forbidden" in (result.error or "")
        assert len(dispatched) == 0

    @pytest.mark.anyio
    async def test_require_approval_stages_execution(self, test_env):
        """3. REQUIRE_APPROVAL stages execution into WAITING_FOR_APPROVAL with event."""
        coordinator = test_env["coordinator"]
        pending_registry = test_env["pending_registry"]
        events = []

        req = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Format disk partition",
            task_type="command",
            inputs={
                "tool_name": "bash",
                "tool_args": {"command": "dd if=/dev/zero of=/dev/sdb bs=1M"},
            },
        )

        result = await coordinator.execute(req, event_listener=events.append)

        assert result.status == ExecutionStatus.WAITING_FOR_APPROVAL
        op_id = result.outputs.get("operation_id")
        assert op_id is not None

        # Operation is pending in registry
        op = pending_registry.get_operation(op_id)
        assert op is not None
        assert op.status == "pending"
        assert op.tool_name == "bash"

        # APPROVAL_REQUIRED event emitted
        appr_events = [e for e in events if e.event_type == ExecutionEventType.APPROVAL_REQUIRED]
        assert len(appr_events) == 1
        assert appr_events[0].payload.get("operation_id") == op_id

    @pytest.mark.anyio
    async def test_allow_permits_low_risk_execution(self, test_env):
        """4. ALLOW permits low-risk execution to run and complete."""
        coordinator = test_env["coordinator"]
        dispatched = test_env["dispatched"]

        req = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Read project config",
            task_type="tool",
            inputs={
                "tool_name": "read_file",
                "tool_args": {"path": "README.md"},
            },
        )

        result = await coordinator.execute(req)

        assert result.status == ExecutionStatus.COMPLETED
        assert len(dispatched) == 1

    @pytest.mark.anyio
    async def test_evaluation_error_fails_closed(self, test_env):
        """5. Evaluation error fails closed with POLICY_BLOCKED."""
        coordinator = test_env["coordinator"]
        policy_engine = test_env["policy_engine"]
        dispatched = test_env["dispatched"]

        # Simulate exception in risk scoring or rule matching
        with patch.object(
            policy_engine, "infer_required_permissions", side_effect=RuntimeError("Engine crash")
        ):
            req = ExecutionRequest(
                project_id="proj_r2_test",
                prompt="Safe read",
                inputs={"tool_name": "read_file", "tool_args": {"path": "safe.txt"}},
            )
            result = await coordinator.execute(req)

            assert result.status == ExecutionStatus.BLOCKED
            assert result.error_code == "POLICY_BLOCKED"
            assert "fail-closed" in (result.error or "").lower()
            assert len(dispatched) == 0


# ============================================================================
# Phase 2B: R2.4 Exact-Operation Approval Tokens Tests
# ============================================================================


class TestExactOperationApprovals:
    def test_approval_binds_exact_capability_or_tool(self):
        """6. Approval binds exact capability/tool; tool name mismatch fails."""
        registry = PendingOperationRegistry()
        args = {"command": "npm test"}
        op = registry.register_operation("run_command", args)

        _, token = registry.approve_operation(op.operation_id, actor="operator")

        # Attempt to consume token under a different tool name
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry.consume_token(token, tool_name="delete_files", tool_args=args)

        assert "Tool name mismatch" in str(exc_info.value)
        # Verify token was not consumed
        assert registry.get_operation(op.operation_id).status == "approved"

    def test_approval_binds_canonical_argument_digest(self):
        """7. Approval binds canonical argument digest (order-independent serialization)."""
        registry = PendingOperationRegistry()

        # Semantically identical arguments with different dictionary key ordering
        args1 = {"b": 2, "a": 1, "nested": {"z": 100, "y": 200}}
        args2 = {"nested": {"y": 200, "z": 100}, "a": 1, "b": 2}

        assert registry.compute_args_hash(args1) == registry.compute_args_hash(args2)

        op = registry.register_operation("test_tool", args1)
        _, token = registry.approve_operation(op.operation_id, actor="operator")

        # Consuming with args2 succeeds because canonical digest is identical
        consumed = registry.consume_token(token, "test_tool", args2)
        assert consumed.status == "consumed"

    def test_changed_argument_invalidates_approval(self):
        """8. Changed argument invalidates approval."""
        registry = PendingOperationRegistry()
        approved_args = {"command": "git status"}
        tampered_args = {"command": "git push --force"}

        op = registry.register_operation("bash", approved_args)
        _, token = registry.approve_operation(op.operation_id, actor="operator")

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry.consume_token(token, "bash", tampered_args)

        assert "Cryptographic argument verification failed" in str(exc_info.value)
        assert registry.get_operation(op.operation_id).status == "approved"

    def test_changed_target_path_invalidates_approval(self):
        """9. Changed target path invalidates approval."""
        registry = PendingOperationRegistry()
        safe_args = {"path": "/workspace/tmp/output.log", "action": "delete"}
        malicious_args = {"path": "/etc/shadow", "action": "delete"}

        op = registry.register_operation("fs_delete", safe_args)
        _, token = registry.approve_operation(op.operation_id, actor="operator")

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry.consume_token(token, "fs_delete", malicious_args)

        assert "Cryptographic argument verification failed" in str(exc_info.value)

    def test_expired_approval_fails(self):
        """10. Expired approval fails both approval and consumption."""
        registry = PendingOperationRegistry(default_ttl_seconds=0.05)
        op = registry.register_operation("bash", {"command": "ls"})

        time.sleep(0.08)

        # Approving an expired operation fails
        with pytest.raises(OperationExpiredError):
            registry.approve_operation(op.operation_id)

        # If approved before expiry but consumed after expiry:
        registry2 = PendingOperationRegistry()
        op2 = registry2.register_operation("bash", {"command": "ls"})
        _, token2 = registry2.approve_operation(op2.operation_id)

        # Artificially expire operation
        op2.expires_at = time.time() - 10.0

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry2.consume_token(token2, "bash", {"command": "ls"})

        assert "expired" in str(exc_info.value).lower()

    def test_approval_is_single_use(self):
        """11. Approval is single-use; subsequent attempts detect replay."""
        registry = PendingOperationRegistry()
        args = {"command": "deploy_staging"}
        op = registry.register_operation("deploy", args)
        _, token = registry.approve_operation(op.operation_id)

        # First consumption succeeds
        consumed1 = registry.consume_token(token, "deploy", args)
        assert consumed1.status == "consumed"

        # Second consumption fails with replay attack detected
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry.consume_token(token, "deploy", args)

        assert "replay attack detected" in str(exc_info.value).lower()

    def test_concurrent_race_double_consumption_permits_only_one_winner(self):
        """12. Concurrent race test: double-consumption permits exactly one winner."""
        registry = PendingOperationRegistry()
        args = {"command": "transfer_funds", "amount": 1000}
        op = registry.register_operation("finance", args)
        _, token = registry.approve_operation(op.operation_id)

        results = []
        errors = []

        def attempt_consume():
            try:
                res = registry.consume_token(token, "finance", args)
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = 10
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(attempt_consume) for _ in range(threads)]
            for f in futures:
                f.result()

        # Exactly 1 winner, 9 rejected
        assert len(results) == 1
        assert len(errors) == threads - 1
        assert all(isinstance(e, SecurityBoundaryViolation) for e in errors)
        assert registry.get_operation(op.operation_id).status == "consumed"

    @pytest.mark.anyio
    async def test_replay_fails_with_security_violation(self, test_env):
        """13. Replay through execution coordinator fails with APPROVAL_VIOLATION."""
        coordinator = test_env["coordinator"]
        pending_registry = test_env["pending_registry"]

        args = {"command": "rm -rf /tmp/data"}
        op = pending_registry.register_operation("run_command", args)
        _, token = pending_registry.approve_operation(op.operation_id)

        # First execution with approval token succeeds
        req1 = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Clean data",
            task_type="command",
            inputs={"tool_name": "run_command", "tool_args": args, "approval_token": token},
        )
        res1 = await coordinator.execute(req1)
        assert res1.status == ExecutionStatus.COMPLETED

        # Replay attempt with same token fails closed
        req2 = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Clean data again",
            task_type="command",
            inputs={"tool_name": "run_command", "tool_args": args, "approval_token": token},
        )
        res2 = await coordinator.execute(req2)
        assert res2.status == ExecutionStatus.BLOCKED
        assert res2.error_code == "APPROVAL_VIOLATION"
        assert "replay attack detected" in (res2.error or "").lower()

    def test_rejection_cannot_later_be_approved_or_consumed(self):
        """14. Rejection cannot later be approved or consumed."""
        registry = PendingOperationRegistry()
        op = registry.register_operation("bash", {"command": "rm -rf /"})

        rejected_op = registry.reject_operation(op.operation_id, actor="security_admin")
        assert rejected_op.status == "rejected"

        # Approval of rejected op fails
        with pytest.raises(ValueError) as exc_info:
            registry.approve_operation(op.operation_id)
        assert "Cannot approve rejected operation" in str(exc_info.value)

    def test_execution_id_mismatch_invalidates_approval(self):
        """15. Execution ID mismatch invalidates approval."""
        registry = PendingOperationRegistry()
        args = {"command": "sync"}
        op = registry.register_operation("sync_tool", args, execution_id="exec_valid_123")
        _, token = registry.approve_operation(op.operation_id)

        # Attempt to consume with wrong execution_id
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            registry.consume_token(token, "sync_tool", args, execution_id="exec_malicious_999")

        assert "Execution ID mismatch" in str(exc_info.value)

        # Consuming with matching execution_id succeeds
        consumed = registry.consume_token(token, "sync_tool", args, execution_id="exec_valid_123")
        assert consumed.status == "consumed"


# ============================================================================
# Phase 2C: Ledger Audit, Redaction, and Anti-Forging Tests
# ============================================================================


class TestLedgerRedactionAndForging:
    @pytest.mark.anyio
    async def test_ledger_records_request_decision_and_consumption(self, test_env):
        """16. Ledger records request, decision, and consumption."""
        coordinator = test_env["coordinator"]
        pending_registry = test_env["pending_registry"]
        ledger_service = test_env["ledger_service"]

        args = {"command": "truncate table users"}
        exec_id = "exec_ledger_test_001"

        # 1. First execution stages the operation
        req1 = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Truncate users",
            task_type="command",
            inputs={"execution_id": exec_id, "tool_name": "db_admin", "tool_args": args},
        )
        res1 = await coordinator.execute(req1)
        assert res1.status == ExecutionStatus.WAITING_FOR_APPROVAL
        op_id = res1.outputs.get("operation_id")

        # 2. Operator approves operation
        _, token = pending_registry.approve_operation(op_id, actor="sec_lead")

        # 3. Resubmit execution with token
        req2 = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Truncate users",
            task_type="command",
            inputs={
                "execution_id": exec_id,
                "tool_name": "db_admin",
                "tool_args": args,
                "approval_token": token,
            },
        )
        res2 = await coordinator.execute(req2)
        assert res2.status == ExecutionStatus.COMPLETED

        # 4. Inspect execution trace reconstructed from ledger events
        trace = ledger_service.get_execution_trace(exec_id)
        assert trace is not None
        assert len(trace.approvals) == 1

        approval_record = trace.approvals[0]
        assert approval_record.status == "consumed"
        assert approval_record.consumed is True
        assert approval_record.decided_by == "sec_lead"
        assert approval_record.tool_name == "db_admin"
        assert approval_record.digest is not None

    def test_raw_secret_arguments_are_redacted_from_approval_evidence(self):
        """17. Raw secret arguments are redacted from approval evidence."""
        secret_args = {
            "api_key": "sk-secret-live-xyz123",
            "password": "SuperSecretPassword!",
            "database_url": "postgres://user:pass@localhost/db",
            "public_param": "visible_value",
        }

        redacted = redact_sensitive_data(secret_args)
        assert redacted["api_key"] == "[REDACTED]"
        assert redacted["password"] == "[REDACTED]"
        assert redacted["public_param"] == "visible_value"

        # Verify PendingOperation.to_public_dict() redacts tool_args
        registry = PendingOperationRegistry()
        op = registry.register_operation("auth_tool", secret_args)
        pub_dict = op.to_public_dict()

        assert pub_dict["tool_args"]["api_key"] == "[REDACTED]"
        assert pub_dict["tool_args"]["password"] == "[REDACTED]"
        assert pub_dict["tool_args"]["public_param"] == "visible_value"

        # Raw arguments in op remain intact for cryptographic verification
        assert op.tool_args["api_key"] == "sk-secret-live-xyz123"
        _, token = registry.approve_operation(op.operation_id)
        consumed = registry.consume_token(token, "auth_tool", secret_args)
        assert consumed.status == "consumed"

    @pytest.mark.anyio
    async def test_frontend_cannot_forge_approval(self, test_env):
        """18. Frontend cannot forge approval (client flags ignored; fake token blocked)."""
        coordinator = test_env["coordinator"]
        dispatched = test_env["dispatched"]

        # Attempt 1: Client sends approved=True without approval_token
        req_forged_flag = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Destructive action",
            task_type="command",
            inputs={
                "tool_name": "run_command",
                "tool_args": {"command": "rm -rf /"},
                "approved": True,
                "allow_high_risk": True,
                "auto_apply": True,
            },
        )

        res1 = await coordinator.execute(req_forged_flag)
        # Must NOT execute
        assert res1.status in (ExecutionStatus.WAITING_FOR_APPROVAL, ExecutionStatus.BLOCKED)
        assert len(dispatched) == 0

        # Attempt 2: Client manufactures a forged approval token
        req_forged_token = ExecutionRequest(
            project_id="proj_r2_test",
            prompt="Destructive action",
            task_type="command",
            inputs={
                "tool_name": "run_command",
                "tool_args": {"command": "rm -rf /"},
                "approval_token": "tok_forged_random_hex_12345",
            },
        )

        res2 = await coordinator.execute(req_forged_token)
        assert res2.status == ExecutionStatus.BLOCKED
        assert res2.error_code == "APPROVAL_VIOLATION"
        assert len(dispatched) == 0


# ============================================================================
# Phase 2D: CTO Review Section 12 Security Closure Suite (15 Scenarios)
# ============================================================================


class TestSection12SecurityClosurePass:
    """Rigorous verification of the 15 required security closure scenarios."""

    def test_01_root_low_risk_execution_cannot_authorize_later_destructive_operation(
        self, tmp_path
    ):
        """1. Root low-risk execution cannot authorize a later destructive operation."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        critical_file = proj_dir / "critical.txt"
        critical_file.write_text("critical database contents")

        policy_engine = PolicyEngine()
        registry = PendingOperationRegistry()

        # Approve a read operation
        read_args = {"path": str(critical_file)}
        op = registry.register_operation(
            tool_name="filesystem.read_file",
            tool_args=read_args,
            capability="filesystem",
        )
        _, read_token = registry.approve_operation(op.operation_id)

        # Boundary configured with write permissions, but given read approval token
        boundary = CapabilityBoundary(
            project_root=proj_dir,
            declared_permissions=[SkillPermission.WRITE_LOCAL, SkillPermission.DESTRUCTIVE],
            policy_engine=policy_engine,
            pending_registry=registry,
            approval_token=read_token,
        )

        # Attempt to delete file using read token fails closed
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            boundary.delete_file("critical.txt")
        assert "Tool name mismatch" in str(
            exc_info.value
        ) or "Cryptographic argument verification failed" in str(exc_info.value)
        assert critical_file.exists()

    def test_02_operation_level_policy_engine_is_mandatory(self, tmp_path):
        """2. Operation-level PolicyEngine is mandatory."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        target_file = proj_dir / "critical.txt"
        target_file.write_text("data")

        policy_engine = PolicyEngine()
        # Direct boundary access with DESTRUCTIVE permission but without an approval token
        boundary = CapabilityBoundary(
            project_root=proj_dir,
            declared_permissions=[SkillPermission.WRITE_LOCAL, SkillPermission.DESTRUCTIVE],
            policy_engine=policy_engine,
        )

        # Unapproved destructive delete requires approval fail-closed
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            boundary.delete_file("critical.txt")
        assert "requires approval" in str(exc_info.value).lower()
        assert target_file.exists()

    def test_03_exact_actual_arguments_are_recomputed_before_side_effect(self, tmp_path):
        """3. Exact actual arguments are recomputed before side effect."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        target = proj_dir / "target.txt"
        target.write_text("initial data")

        policy_engine = PolicyEngine()
        registry = PendingOperationRegistry()

        # Approved for deleting target.txt
        approved_args = {"path": str(target.resolve())}
        op = registry.register_operation(
            tool_name="filesystem.delete_file",
            tool_args=approved_args,
            capability="filesystem",
        )
        _, token = registry.approve_operation(op.operation_id)

        boundary = CapabilityBoundary(
            project_root=proj_dir,
            declared_permissions=[SkillPermission.WRITE_LOCAL, SkillPermission.DESTRUCTIVE],
            policy_engine=policy_engine,
            pending_registry=registry,
        )

        # Tampering with target path immediately before execution fails
        other_file = proj_dir / "other.txt"
        other_file.write_text("should not be deleted")

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            boundary.delete_file("other.txt", approval_token=token)
        assert "Cryptographic argument verification failed" in str(exc_info.value)
        assert other_file.exists()
        assert target.exists()

    def test_04_persisted_approval_state_survives_restart(self, tmp_path):
        """4. Persisted approval state survives/reconciles restart."""
        db_path = str(tmp_path / "durable_restart.db")
        storage1 = SQLiteBackend(db_path=db_path)
        reg1 = PendingOperationRegistry(storage=storage1)

        tool_args = {"command": "echo durable"}
        op = reg1.register_operation("bash", tool_args)
        _, token = reg1.approve_operation(op.operation_id, actor="admin_user")

        # Simulate engine restart by instantiating new storage and registry
        storage2 = SQLiteBackend(db_path=db_path)
        reg2 = PendingOperationRegistry(storage=storage2)

        recovered = reg2.get_operation(op.operation_id)
        assert recovered is not None
        assert recovered.status == "approved"
        assert recovered.actor == "admin_user"
        assert recovered.token_verifier is not None

        # Consuming token on restarted registry succeeds
        consumed = reg2.consume_token(token, "bash", tool_args)
        assert consumed.status == "consumed"

    def test_05_consumed_approval_remains_consumed_after_restart(self, tmp_path):
        """5. Consumed approval remains consumed after restart."""
        db_path = str(tmp_path / "consumed_restart.db")
        storage1 = SQLiteBackend(db_path=db_path)
        reg1 = PendingOperationRegistry(storage=storage1)

        tool_args = {"action": "wipe_cache"}
        op = reg1.register_operation("cache_cleaner", tool_args)
        _, token = reg1.approve_operation(op.operation_id)
        reg1.consume_token(token, "cache_cleaner", tool_args)

        # Restart
        storage2 = SQLiteBackend(db_path=db_path)
        reg2 = PendingOperationRegistry(storage=storage2)

        recovered = reg2.get_operation(op.operation_id)
        assert recovered is not None
        assert recovered.status == "consumed"

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            reg2.consume_token(token, "cache_cleaner", tool_args)
        assert "already been consumed" in str(exc_info.value).lower()

    def test_06_db_level_concurrent_consumption_has_exactly_one_winner(self, tmp_path):
        """6. DB-level concurrent consumption has exactly one winner."""
        db_path = str(tmp_path / "concurrent_cas.db")
        storage = SQLiteBackend(db_path=db_path)
        reg = PendingOperationRegistry(storage=storage)

        tool_args = {"amount": 1000000, "account": "acc_treasury"}
        op = reg.register_operation("transfer", tool_args)
        _, token = reg.approve_operation(op.operation_id)

        winners = []
        failures = []

        def worker():
            try:
                res = reg.consume_token(token, "transfer", tool_args)
                winners.append(res)
            except Exception as ex:
                failures.append(ex)

        threads = 10
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker) for _ in range(threads)]
            for f in futures:
                f.result()

        assert len(winners) == 1
        assert len(failures) == threads - 1
        assert all(isinstance(f, SecurityBoundaryViolation) for f in failures)

        # Direct database verification
        db_record = storage.get_approval(op.operation_id)
        assert db_record["status"] == "consumed"
        assert db_record["consumed_at"] is not None

    def test_07_raw_approval_token_is_absent_from_db_ledger_logs(self, tmp_path):
        """7. Raw approval token is absent from DB/ledger/logs."""
        db_path = str(tmp_path / "raw_token_absence.db")
        storage = SQLiteBackend(db_path=db_path)
        reg = PendingOperationRegistry(storage=storage)

        tool_args = {"secret_payload": "confidential"}
        op = reg.register_operation("secret_task", tool_args)
        _, raw_token = reg.approve_operation(op.operation_id)
        reg.consume_token(raw_token, "secret_task", tool_args)

        # Inspect database record
        db_rec = storage.get_approval(op.operation_id)
        assert db_rec is not None
        assert raw_token not in str(db_rec)
        assert db_rec["token_verifier"] != raw_token
        assert len(db_rec["token_verifier"]) == 64

    def test_08_canonical_digest_version_is_persisted(self, tmp_path):
        """8. Canonical digest version is persisted."""
        db_path = str(tmp_path / "version_test.db")
        storage = SQLiteBackend(db_path=db_path)
        reg = PendingOperationRegistry(storage=storage)

        op = reg.register_operation("sample_tool", {"k": "v"})
        assert op.digest_version == OPERATION_DIGEST_VERSION

        db_rec = storage.get_approval(op.operation_id)
        assert db_rec["digest_version"] == OPERATION_DIGEST_VERSION

        recovered = reg.get_operation(op.operation_id)
        assert recovered.digest_version == OPERATION_DIGEST_VERSION

    def test_09_operation_digest_is_deterministic(self):
        """9. Operation digest is deterministic."""
        args_a = {"alpha": 1, "beta": 2, "details": {"inner_x": 10, "inner_y": 20}}
        args_b = {"beta": 2, "details": {"inner_y": 20, "inner_x": 10}, "alpha": 1}

        d1 = compute_canonical_operation_digest("run_cmd", args_a, capability="exec", version=1)
        d2 = compute_canonical_operation_digest("run_cmd", args_b, capability="exec", version=1)
        assert d1 == d2

        d_diff = compute_canonical_operation_digest(
            "run_cmd", {"alpha": 99}, capability="exec", version=1
        )
        assert d1 != d_diff

    def test_10_normalized_path_change_invalidates_authorization(self):
        """10. Normalized path change invalidates authorization."""
        reg = PendingOperationRegistry()
        approved_args = {"path": "/app/workspace/target.py"}
        op = reg.register_operation("fs_write", approved_args)
        _, token = reg.approve_operation(op.operation_id)

        tampered_args = {"path": "/app/workspace/other.py"}
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            reg.consume_token(token, "fs_write", tampered_args)
        assert "Cryptographic argument verification failed" in str(exc_info.value)

    def test_11_executable_argv_change_invalidates_authorization(self):
        """11. Executable/argv change invalidates authorization."""
        reg = PendingOperationRegistry()
        approved_args = {"command": "git pull origin main"}
        op = reg.register_operation("bash", approved_args)
        _, token = reg.approve_operation(op.operation_id)

        tampered_args = {"command": "git push origin main"}
        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            reg.consume_token(token, "bash", tampered_args)
        assert "Cryptographic argument verification failed" in str(exc_info.value)

    def test_12_actor_mismatch_fails(self):
        """12. Actor mismatch fails."""
        reg = PendingOperationRegistry()
        args = {"command": "shutdown -h now"}
        op = reg.register_operation("sys_cmd", args)
        _, token = reg.approve_operation(op.operation_id, actor="lead_secops")

        with pytest.raises(SecurityBoundaryViolation) as exc_info:
            reg.consume_token(token, "sys_cmd", args, actor="untrusted_caller")
        assert "Actor mismatch" in str(exc_info.value)

    def test_13_policy_exception_at_operation_boundary_fails_closed(self, tmp_path):
        """13. Policy exception at operation boundary fails closed."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()

        policy_engine = PolicyEngine()
        with patch.object(policy_engine, "evaluate", side_effect=RuntimeError("Engine failure")):
            boundary = CapabilityBoundary(
                project_root=proj_dir,
                declared_permissions=[SkillPermission.WRITE_LOCAL],
                policy_engine=policy_engine,
            )
            with pytest.raises(SecurityBoundaryViolation) as exc_info:
                boundary.check_operation_policy(
                    capability="filesystem",
                    operation="write_file",
                    tool_name="filesystem.write_file",
                    tool_args={"path": "file.txt"},
                )
            assert "fail-closed" in str(exc_info.value).lower()

    def test_14_handshake_permission_failure_fails_closed(self, tmp_path):
        """14. Handshake permission failure fails closed."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        symlink_dir = tmp_path / "symlink_dir"
        symlink_dir.symlink_to(real_dir)

        token_file = symlink_dir / "ipc.token"
        tm = IPCTokenManager()

        with patch.dict("os.environ", {"AGENT_ENGINE_TOKEN_FILE": str(token_file)}, clear=False):
            patch_env = patch.dict("os.environ", {"AGENT_ENGINE_IPC_TOKEN": ""})
            patch_env.start()
            try:
                tm._token = None
                with pytest.raises(PermissionError) as exc_info:
                    tm._persist_handshake_token("token_secret_123")
                assert "symlink detected" in str(exc_info.value).lower()
            finally:
                patch_env.stop()

    def test_15_stale_ipc_token_is_invalid_after_launch_rotation(self, tmp_path):
        """15. Stale IPC token is invalid after launch rotation."""
        token_file = tmp_path / "ipc.token"
        tm = IPCTokenManager()

        with patch.dict("os.environ", {"AGENT_ENGINE_TOKEN_FILE": str(token_file)}, clear=False):
            t1 = tm.rotate_token()
            assert t1 is not None

            # Rotation invalidates t1 and generates t2
            t2 = tm.rotate_token()
            assert t2 is not None
            assert t1 != t2
            assert tm.get_token() == t2

            class MockRequest:
                headers = {"Authorization": f"Bearer {t1}"}

            with pytest.raises(HTTPException) as exc_info:
                tm.verify_request(MockRequest())
            assert exc_info.value.status_code == 401

            class ValidRequest:
                headers = {"Authorization": f"Bearer {t2}"}

            assert tm.verify_request(ValidRequest()) is True
