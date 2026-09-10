import numpy  # noqa: F401 - Must be imported before dspy / FastAPI dependencies
import pytest
from fastapi.testclient import TestClient

from core.safety.audit import AuditLogger
from core.safety.policy import PolicyDecision, PolicyEngine
from core.safety.risk import RiskLevel, RiskScorer
from core.storage import SQLiteBackend
from services.python.server.api import app


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def temp_storage(tmp_path):
    db_path = str(tmp_path / "safety_test.db")
    backend = SQLiteBackend(db_path=db_path)
    yield backend
    backend.close()


@pytest.fixture
def temp_engine(temp_storage):
    audit_logger = AuditLogger(storage=temp_storage)
    return PolicyEngine(audit_logger=audit_logger)


class TestPolicyAcceptanceCriteria:
    """Acceptance criteria tests for Task 1.4: Guardrail Policy Engine."""

    def test_acceptance_criteria_k8s_delete_production_blocked(self, temp_engine):
        """
        Acceptance Criteria:
        Policy blocks 'kubectl delete namespace production'; suggests 'kubectl rollout restart'.
        """
        decision: PolicyDecision = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "kubectl delete namespace production"},
        )

        assert decision.decision == "block"
        assert decision.risk_score >= 0.85
        assert decision.risk_level == "critical"
        assert (
            decision.suggestion
            == "kubectl rollout restart deployment/<deployment_name> -n <namespace>"
        )
        assert "production Kubernetes namespace" in (decision.reason or "")
        assert len(decision.violating_rules) >= 1
        assert decision.violating_rules[0].id == "k8s_prod_namespace_delete"
        assert decision.audit_id is not None

    def test_k8s_delete_prod_variants(self, temp_engine):
        # Variant: "prod"
        d1 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "kubectl delete namespace prod"},
        )
        assert d1.decision == "block"

        # Variant: "prod-us-east-1"
        d2 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "kubectl delete namespace prod-us-east-1"},
        )
        assert d2.decision == "block"

        # Read-only kubectl command should NOT be blocked
        d3 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "kubectl get namespace production"},
        )
        assert d3.decision != "block"


class TestFilesystemAndDataProtection:
    """Test guardrail rules protecting filesystems, databases, and git histories."""

    def test_destructive_rm_root_blocked(self, temp_engine):
        d1 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "rm -rf /"},
        )
        assert d1.decision == "block"
        assert d1.risk_level == "critical"

        d2 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "rm -rf /*"},
        )
        assert d2.decision == "block"

    def test_destructive_rm_wildcard_blocked(self, temp_engine):
        d = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "rm -rf *"},
        )
        assert d.decision == "block"
        assert d.violating_rules[0].id == "destructive_fs_rm_all"

    def test_disk_formatting_blocked(self, temp_engine):
        d1 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "mkfs.ext4 /dev/sda1"},
        )
        assert d1.decision == "block"

        d2 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "dd if=/dev/zero of=/dev/sdb bs=1M"},
        )
        assert d2.decision == "block"

    def test_production_database_drop_blocked(self, temp_engine):
        d1 = temp_engine.evaluate(
            tool_name="sql_query",
            tool_args={"query": "DROP DATABASE production_users;"},
        )
        assert d1.decision == "block"
        assert d1.violating_rules[0].id == "db_drop_prod"

        d2 = temp_engine.evaluate(
            tool_name="sql_query",
            tool_args={"query": "TRUNCATE TABLE prod_payments;"},
        )
        assert d2.decision == "block"

    def test_secrets_file_access_blocked(self, temp_engine):
        d1 = temp_engine.evaluate(
            tool_name="read_file",
            tool_args={"path": "/home/user/project/.env"},
        )
        assert d1.decision == "block"
        assert d1.violating_rules[0].id == "secrets_env_access"

        d2 = temp_engine.evaluate(
            tool_name="write_to_file",
            tool_args={"path": "/etc/ssl/certs/server.key", "content": "secret"},
        )
        assert d2.decision == "block"

        d3 = temp_engine.evaluate(
            tool_name="view_file",
            tool_args={"AbsolutePath": "/home/user/.ssh/id_rsa"},
        )
        assert d3.decision == "block"

    def test_git_force_push_blocked(self, temp_engine):
        d1 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "git push --force origin master"},
        )
        assert d1.decision == "block"
        assert d1.violating_rules[0].id == "git_force_push"

        d2 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "git push -f origin main"},
        )
        assert d2.decision == "block"

        # Safe feature branch push allowed
        d3 = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "git push origin feature/safety-guardrails"},
        )
        assert d3.decision == "allow"


class TestConflictC6StagingAndRiskScorer:
    """Test dynamic risk scoring and C6 staging behavior."""

    def test_risk_scorer_tiers(self):
        # Low risk: viewing public documentation
        score, level, _ = RiskScorer.score_tool_call("view_file", {"path": "README.md"})
        assert score < 0.30
        assert level == RiskLevel.LOW

        # Medium risk: writing a regular python file
        score, level, _ = RiskScorer.score_tool_call("write_to_file", {"path": "src/app.py"})
        assert 0.30 <= score < 0.60
        assert level == RiskLevel.MEDIUM

        # High / Critical risk: deleting files or running shell in production
        score, level, _ = RiskScorer.score_tool_call(
            "run_command", {"command": "delete from users in production"}
        )
        assert score >= 0.70
        assert level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_conflict_c6_staged_by_default(self, temp_engine):
        """Conflict C6: Staged by default for high risk unless explicit opt-in."""
        # System package install requires staging per rule
        d = temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "sudo apt-get install -y nginx"},
        )
        assert d.decision == "stage"

    def test_safe_read_call_allowed(self, temp_engine):
        d = temp_engine.evaluate(
            tool_name="read_file",
            tool_args={"path": "package.json"},
        )
        assert d.decision == "allow"
        assert d.risk_level == "low"


class TestAuditLogging:
    """Test audit log persistence and retrieval."""

    def test_audit_log_flow(self, temp_engine, temp_storage):
        # Execute an allowed call and a blocked call
        temp_engine.evaluate(
            tool_name="read_file",
            tool_args={"path": "src/index.ts"},
            context={"session_id": "sess_audit_test"},
        )
        temp_engine.evaluate(
            tool_name="run_command",
            tool_args={"command": "kubectl delete namespace production"},
            context={"session_id": "sess_audit_test"},
        )

        logs = temp_storage.list_audit_logs(session_id="sess_audit_test")
        assert len(logs) == 2

        blocked_log = logs[0]  # Most recent
        assert blocked_log["decision"] == "block"
        assert blocked_log["tool_name"] == "run_command"
        assert blocked_log["policy_id"] == "k8s_prod_namespace_delete"
        assert blocked_log["risk_level"] == "critical"

        allowed_log = logs[1]
        assert allowed_log["decision"] == "allow"
        assert allowed_log["tool_name"] == "read_file"


class TestSafetyAPIEndpoints:
    """Test Sidecar REST API safety endpoints."""

    def test_api_safety_evaluate_endpoint(self, test_client):
        # Test evaluate endpoint with acceptance criteria command
        payload = {
            "tool_name": "run_command",
            "tool_args": {"command": "kubectl delete namespace production"},
            "session_id": "sess_api_k8s",
        }
        resp = test_client.post("/v1/safety/evaluate", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["decision"] == "block"
        assert data["risk_score"] >= 0.85
        assert data["risk_level"] == "critical"
        assert (
            data["suggestion"]
            == "kubectl rollout restart deployment/<deployment_name> -n <namespace>"
        )
        assert data["audit_id"] is not None

    def test_api_safety_policies_endpoint(self, test_client):
        resp = test_client.get("/v1/safety/policies")
        assert resp.status_code == 200
        policies = resp.json()
        assert len(policies) >= 7

        rule_ids = [p["id"] for p in policies]
        assert "k8s_prod_namespace_delete" in rule_ids
        assert "destructive_fs_rm_root" in rule_ids
        assert "secrets_env_access" in rule_ids

    def test_api_safety_audit_endpoint(self, test_client):
        resp = test_client.get("/v1/safety/audit?limit=10")
        assert resp.status_code == 200
        logs = resp.json()
        assert isinstance(logs, list)
        assert len(logs) >= 1
        assert "decision" in logs[0]
        assert "risk_score" in logs[0]
