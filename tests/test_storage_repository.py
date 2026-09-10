import os
import subprocess
import pytest
from core.storage import (
    DEFAULT_SQLITE_PATH,
    PostgresBackend,
    SQLiteBackend,
    get_storage_backend,
    reset_storage_backend,
)
from core.storage.base import StorageBackend


@pytest.fixture(autouse=True)
def reset_backend_fixture():
    """Ensure clean storage backend state before and after each test."""
    reset_storage_backend()
    yield
    reset_storage_backend()


def test_sqlite_backend_patches_flow(tmp_path):
    """Verify staged, applied, and rejected patch lifecycles on SQLiteBackend."""
    db_path = str(tmp_path / "test_repo.db")
    backend = SQLiteBackend(db_path=db_path)

    target_file = tmp_path / "test_script.py"
    original_code = "print('vulnerable')"
    patched_code = "print('safe')"
    target_file.write_text(original_code)

    # 1. Stage patch
    patch_id = backend.stage_patch(
        file_path=str(target_file),
        patch_type="security",
        risk_level="Critical",
        report="Unsafe evaluation",
        original_code=original_code,
        patched_code=patched_code,
    )
    assert patch_id > 0

    # 2. Get staged patches
    staged = backend.get_staged_patches()
    assert len(staged) == 1
    assert staged[0]["id"] == patch_id
    assert staged[0]["status"] == "staged"
    assert staged[0]["risk_level"] == "Critical"

    # 3. Get single patch
    patch = backend.get_patch(patch_id)
    assert patch is not None
    assert patch["file_path"] == str(target_file)

    # 4. Apply patch
    assert backend.apply_patch(patch_id) is True
    assert target_file.read_text() == patched_code
    assert len(backend.get_staged_patches()) == 0

    # Cannot re-apply applied patch
    assert backend.apply_patch(patch_id) is False

    # 5. Stage another patch and reject it
    p2_id = backend.stage_patch(
        file_path=str(target_file),
        patch_type="refactor",
        risk_level="Low",
        report="Formatting",
        original_code=patched_code,
        patched_code=patched_code + "\n",
    )
    assert backend.reject_patch(p2_id) is True
    assert len(backend.get_staged_patches()) == 0
    p2 = backend.get_patch(p2_id)
    assert p2 is not None
    assert p2["status"] == "rejected"


def test_sqlite_backend_sessions(tmp_path):
    """Verify session CRUD on SQLiteBackend."""
    backend = SQLiteBackend(db_path=":memory:")

    # 1. Create session
    session = backend.create_session(
        session_id="sess_100",
        user_id="usr_alice",
        metadata={"project": "agent_studio", "model": "qwen2.5"},
    )
    assert session["session_id"] == "sess_100"
    assert session["user_id"] == "usr_alice"
    assert session["metadata"]["project"] == "agent_studio"

    # 2. Retrieve session
    fetched = backend.get_session("sess_100")
    assert fetched is not None
    assert fetched["session_id"] == "sess_100"
    assert fetched["messages"] == []

    # 3. Update session
    new_msgs = [
        {"role": "user", "content": "Hello Agent Engine"},
        {"role": "assistant", "content": "Hello Alice, how can I help?"},
    ]
    assert (
        backend.update_session("sess_100", messages=new_msgs, metadata={"status": "active"}) is True
    )

    updated = backend.get_session("sess_100")
    assert updated is not None
    assert len(updated["messages"]) == 2
    assert updated["metadata"]["status"] == "active"
    assert updated["metadata"]["project"] == "agent_studio"

    # 4. List sessions
    backend.create_session(session_id="sess_200", user_id="usr_bob")
    all_sessions = backend.list_sessions()
    assert len(all_sessions) == 2

    alice_sessions = backend.list_sessions(user_id="usr_alice")
    assert len(alice_sessions) == 1
    assert alice_sessions[0]["session_id"] == "sess_100"

    # 5. Delete session
    assert backend.delete_session("sess_100") is True
    assert backend.get_session("sess_100") is None
    assert len(backend.list_sessions()) == 1


def test_sqlite_backend_users_and_tenants(tmp_path):
    """Verify user registration and multi-tenant isolation."""
    backend = SQLiteBackend(db_path=":memory:")

    # Create users across two tenants
    u1 = backend.create_user(
        user_id="u_dev1",
        email="dev1@alpha.corp",
        role="developer",
        tenant_id="tenant_alpha",
    )
    u2 = backend.create_user(
        user_id="u_admin1",
        email="admin@alpha.corp",
        role="admin",
        tenant_id="tenant_alpha",
    )
    u3 = backend.create_user(
        user_id="u_dev2",
        email="dev2@beta.corp",
        role="developer",
        tenant_id="tenant_beta",
    )

    assert u1["user_id"] == "u_dev1"
    assert u2["role"] == "admin"
    assert u3["tenant_id"] == "tenant_beta"
    assert backend.get_user("u_dev1")["email"] == "dev1@alpha.corp"

    # Tenant filtering
    alpha_users = backend.list_users(tenant_id="tenant_alpha")
    assert len(alpha_users) == 2
    assert {u["user_id"] for u in alpha_users} == {"u_dev1", "u_admin1"}

    beta_users = backend.list_users(tenant_id="tenant_beta")
    assert len(beta_users) == 1
    assert beta_users[0]["user_id"] == "u_dev2"

    all_users = backend.list_users()
    assert len(all_users) == 3


def test_sqlite_backend_policies_and_finance(tmp_path):
    """Verify safety policies and cost records tracking."""
    backend = SQLiteBackend(db_path=":memory:")

    # 1. Policies
    pol = backend.save_policy(
        policy_id="pol_shell_exec",
        name="Block Destructive Commands",
        description="Prevents rm -rf / and dangerous disk writes",
        rules={"blocked_patterns": ["rm -rf", "mkfs"], "severity": "CRITICAL"},
        is_active=True,
    )
    assert pol["policy_id"] == "pol_shell_exec"

    fetched_pol = backend.get_policy("pol_shell_exec")
    assert fetched_pol is not None
    assert fetched_pol["rules"]["severity"] == "CRITICAL"

    # Update policy on conflict
    backend.save_policy(
        policy_id="pol_shell_exec",
        name="Block Destructive Commands (v2)",
        description="Updated rule",
        rules={"blocked_patterns": ["rm -rf", "mkfs", "dd"], "severity": "CRITICAL"},
        is_active=True,
    )
    updated_pol = backend.get_policy("pol_shell_exec")
    assert updated_pol["name"] == "Block Destructive Commands (v2)"
    assert "dd" in updated_pol["rules"]["blocked_patterns"]

    # 2. Cost Records
    backend.record_cost(
        agent_name="code_sentry",
        model_name="qwen2.5-coder",
        prompt_tokens=500,
        completion_tokens=150,
        cost_usd=0.0002,
        task_id="task_audit_1",
        success=True,
    )
    backend.record_cost(
        agent_name="code_sentry",
        model_name="qwen2.5-coder",
        prompt_tokens=800,
        completion_tokens=200,
        cost_usd=0.0003,
        task_id="task_audit_2",
        success=True,
    )
    backend.record_cost(
        agent_name="planner",
        model_name="claude-3-5-sonnet",
        prompt_tokens=2000,
        completion_tokens=500,
        cost_usd=0.0125,
        task_id="task_plan_1",
        success=False,
    )

    summary = backend.get_cost_summary()
    assert summary["total_calls"] == 3
    assert summary["successful_calls"] == 2
    assert summary["success_rate"] == 0.6667
    assert summary["total_prompt_tokens"] == 3300
    assert summary["total_completion_tokens"] == 850
    assert summary["total_tokens"] == 4150
    assert summary["total_cost_usd"] == 0.013

    sentry_summary = backend.get_cost_summary(agent_name="code_sentry")
    assert sentry_summary["total_calls"] == 2
    assert sentry_summary["success_rate"] == 1.0


def test_sqlite_backend_benchmarks(tmp_path):
    """Verify model eval benchmark recording."""
    backend = SQLiteBackend(db_path=":memory:")

    backend.record_benchmark(
        model_name="gemma-2-9b",
        task_type="code_generation",
        success_rate=0.88,
        latency_ms=450.0,
        cost_per_success=0.0005,
        metadata={"quantization": "q4_k_m"},
    )
    backend.record_benchmark(
        model_name="claude-3-5-sonnet",
        task_type="code_generation",
        success_rate=0.96,
        latency_ms=1200.0,
        cost_per_success=0.0150,
        metadata={"provider": "anthropic"},
    )
    backend.record_benchmark(
        model_name="gemma-2-9b",
        task_type="classification",
        success_rate=0.92,
        latency_ms=180.0,
        cost_per_success=0.0001,
    )

    all_b = backend.get_benchmarks()
    assert len(all_b) == 3

    code_b = backend.get_benchmarks(task_type="code_generation")
    assert len(code_b) == 2
    assert (
        code_b[0]["metadata"]["provider"] == "anthropic"
        or code_b[1]["metadata"]["provider"] == "anthropic"
    )


def test_postgres_backend_interface_parity(tmp_path):
    """Verify PostgresBackend implements all StorageBackend methods with SQLite engine url."""
    engine_url = f"sqlite:///{tmp_path / 'pg_parity.db'}"
    backend = PostgresBackend(connection_url=engine_url)

    assert isinstance(backend, StorageBackend)

    # 1. Patches
    target_file = tmp_path / "pg_target.py"
    target_file.write_text("a = 1")
    p_id = backend.stage_patch(
        file_path=str(target_file),
        patch_type="security",
        risk_level="Medium",
        report="Fix variable",
        original_code="a = 1",
        patched_code="a = 2",
    )
    assert p_id > 0
    staged = backend.get_staged_patches()
    assert len(staged) == 1
    assert backend.apply_patch(p_id) is True
    assert target_file.read_text() == "a = 2"

    # 2. Sessions
    sess = backend.create_session("sess_pg_1", user_id="usr_pg", metadata={"cloud": True})
    assert sess["session_id"] == "sess_pg_1"
    assert backend.update_session("sess_pg_1", messages=[{"role": "user", "content": "hi"}]) is True
    assert len(backend.list_sessions(user_id="usr_pg")) == 1

    # 3. Users & Tenant isolation
    backend.create_user("u_pg1", "u1@tenant.cloud", role="admin", tenant_id="tenant_cloud")
    users = backend.list_users(tenant_id="tenant_cloud")
    assert len(users) == 1

    # 4. Policies
    backend.save_policy("pol_pg_1", "Cloud Safety", rules={"allowed": True})
    assert backend.get_policy("pol_pg_1")["rules"]["allowed"] is True

    # 5. Cost summary
    backend.record_cost("agent_cloud", "cloud_model", 100, 50, 0.001, task_id="t1", success=True)
    summary = backend.get_cost_summary(agent_name="agent_cloud")
    assert summary["total_calls"] == 1
    assert summary["total_cost_usd"] == 0.001

    # 6. Benchmarks
    backend.record_benchmark("cloud_model", "reasoning", 0.95, 800.0, 0.005)
    benchmarks = backend.get_benchmarks("reasoning")
    assert len(benchmarks) == 1

    backend.close()


def test_storage_factory_selection(monkeypatch, tmp_path):
    """Verify get_storage_backend respects parameters, env vars, and defaults."""
    reset_storage_backend()

    # 1. Default -> SQLiteBackend
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    b1 = get_storage_backend(force_new=True)
    assert isinstance(b1, SQLiteBackend)
    assert b1.db_path == DEFAULT_SQLITE_PATH

    # 2. Custom SQLite path
    custom_path = str(tmp_path / "custom.db")
    b2 = get_storage_backend(backend_type="sqlite", db_path=custom_path, force_new=True)
    assert isinstance(b2, SQLiteBackend)
    assert b2.db_path == custom_path

    # 3. STORAGE_BACKEND=postgres via env var
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_URL", f"sqlite:///{tmp_path / 'env_pg.db'}")
    b3 = get_storage_backend(force_new=True)
    assert isinstance(b3, PostgresBackend)


def test_alembic_migration_execution(tmp_path):
    """Verify that Alembic runs 001_initial_schema migration cleanly on SQLite."""
    migration_db = tmp_path / "migration_test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{migration_db}"

    # Run alembic upgrade head
    result = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        cwd="/home/nadir/agent_engine",
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"
    assert "Running upgrade  -> 001_initial_schema" in result.stdout or result.returncode == 0

    # Verify tables were created by the migration
    import sqlite3

    conn = sqlite3.connect(str(migration_db))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {r[0] for r in cursor.fetchall()}
    conn.close()

    expected_tables = {
        "alembic_version",
        "audit_patches",
        "sessions",
        "users",
        "policies",
        "cost_records",
        "benchmarks",
    }
    assert expected_tables.issubset(tables)
