"""tests/test_r4_1_job_domain.py

Milestone R4 (Task R4.1 - Canonical Job Domain) Comprehensive Test Suite.

Verifies:
1. Canonical Job Domain Models, typed IDs, and UTC timestamps.
2. Job state machine validation and illegal transition enforcement.
3. Payload credential sanitization and payload size bounding.
4. Versioned SQLite schema migrations, idempotency, and version tracking.
5. Job CRUD, project/status filtering, and atomic lifecycle event generation.
6. Job Attempt atomic monotonic numbering and execution_id binding.
7. Job Event audit append, secret redaction, and chronological retrieval.
8. Job Dependency graph validation: self-dependency, duplicate, and cycle detection (DFS).
9. Canonical Job Artifact associations and lifecycle audit.
10. Job Schedule persistence and querying.
11. Restart and persistence proof across separate repository connection lifecycles.
12. Foreign key cascade constraints and thread safety.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sqlite3
import pytest

from core.jobs.exceptions import (
    DependencyCycleError,
    DuplicateDependencyError,
    InvalidStateTransitionError,
    JobDomainError,
    JobNotFoundError,
    SelfDependencyError,
)
from core.jobs.migrations import (
    apply_job_migrations,
    get_current_job_schema_version,
)
from core.jobs.models import (
    TERMINAL_JOB_STATES,
    VALID_JOB_TRANSITIONS,
    Job,
    JobArtifact,
    JobAttempt,
    JobAttemptStatus,
    JobDependency,
    JobDependencyType,
    JobEvent,
    JobEventType,
    JobSchedule,
    JobStatus,
    generate_attempt_id,
    generate_dependency_id,
    generate_event_id,
    generate_job_artifact_id,
    generate_job_id,
    generate_schedule_id,
    sanitize_bounded_dict,
    validate_job_state_transition,
)
from core.jobs.sqlite import SQLiteJobRepository


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def memory_repo() -> SQLiteJobRepository:
    """Fixture providing an isolated in-memory SQLiteJobRepository."""
    repo = SQLiteJobRepository(db_path=":memory:")
    yield repo
    repo.close()


@pytest.fixture
def file_repo(tmp_path: Path) -> SQLiteJobRepository:
    """Fixture providing a file-backed SQLiteJobRepository for persistence verification."""
    db_file = tmp_path / "test_jobs.db"
    repo = SQLiteJobRepository(db_path=str(db_file))
    yield repo
    repo.close()


# ==============================================================================
# 1. Model & ID Generation Tests
# ==============================================================================


def test_canonical_id_prefixes() -> None:
    """Validate standard prefix conventions across all job domain entities."""
    assert generate_job_id().startswith("job_")
    assert generate_attempt_id().startswith("att_")
    assert generate_event_id().startswith("jev_")
    assert generate_dependency_id().startswith("jdp_")
    assert generate_job_artifact_id().startswith("jar_")
    assert generate_schedule_id().startswith("sch_")


def test_job_model_instantiation_defaults() -> None:
    """Validate Job model fields and default values."""
    job = Job(job_type="eval_run")
    assert job.job_id.startswith("job_")
    assert job.job_type == "eval_run"
    assert job.status == JobStatus.CREATED
    assert job.created_by == "authority:local_user"
    assert job.created_at is not None
    assert job.updated_at is not None
    assert job.completed_at is None
    assert job.payload_summary == {}

    attempt = JobAttempt(job_id=job.job_id, attempt_number=1)
    assert attempt.attempt_id.startswith("att_")
    assert attempt.attempt_number == 1
    assert attempt.status == JobAttemptStatus.PENDING

    assert issubclass(JobNotFoundError, JobDomainError)
    assert issubclass(InvalidStateTransitionError, JobDomainError)


# ==============================================================================
# 2. State Machine Transition Tests
# ==============================================================================


def test_valid_state_transitions() -> None:
    """Verify all defined valid state transitions pass validation without error."""
    for current_status, valid_targets in VALID_JOB_TRANSITIONS.items():
        # Self transitions are valid noops
        validate_job_state_transition(current_status, current_status)
        for target in valid_targets:
            validate_job_state_transition(current_status, target)


@pytest.mark.parametrize(
    "invalid_from, invalid_to",
    [
        (JobStatus.CREATED, JobStatus.COMPLETED),
        (JobStatus.CREATED, JobStatus.RUNNING),
        (JobStatus.CREATED, JobStatus.FAILED),
        (JobStatus.READY, JobStatus.COMPLETED),
        (JobStatus.COMPLETED, JobStatus.RUNNING),
        (JobStatus.COMPLETED, JobStatus.READY),
        (JobStatus.FAILED, JobStatus.RUNNING),
        (JobStatus.CANCELLED, JobStatus.READY),
        (JobStatus.PARTIAL, JobStatus.RUNNING),
    ],
)
def test_illegal_state_transitions_raise(invalid_from: JobStatus, invalid_to: JobStatus) -> None:
    """Verify illegal transitions raise InvalidStateTransitionError."""
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        validate_job_state_transition(invalid_from, invalid_to)
    assert "Illegal job state transition" in str(exc_info.value)


def test_terminal_states_have_no_outbound_transitions() -> None:
    """Verify terminal states (COMPLETED, PARTIAL, FAILED, CANCELLED) cannot transition out."""
    for terminal_state in TERMINAL_JOB_STATES:
        assert len(VALID_JOB_TRANSITIONS[terminal_state]) == 0
        for other_state in JobStatus:
            if other_state != terminal_state:
                with pytest.raises(InvalidStateTransitionError):
                    validate_job_state_transition(terminal_state, other_state)


# ==============================================================================
# 3. Credential Redaction & Payload Bounding Tests
# ==============================================================================


def test_credential_sanitization_redacts_sensitive_keys() -> None:
    """Verify sensitive keys in dictionaries are redacted."""
    raw = {
        "model": "qwen2.5:7b",
        "api_key": "sk-secret-12345",
        "nested": {
            "bearer_token": "bearer xyz",
            "password": "supersecretpassword",
            "safe_val": 42,
        },
        "auth_header": "Basic dXNlcjpwYXNz",
    }
    sanitized = sanitize_bounded_dict(raw)
    assert sanitized["model"] == "qwen2.5:7b"
    assert sanitized["api_key"] == "[REDACTED_CREDENTIAL]"
    assert sanitized["nested"]["bearer_token"] == "[REDACTED_CREDENTIAL]"
    assert sanitized["nested"]["password"] == "[REDACTED_CREDENTIAL]"
    assert sanitized["nested"]["safe_val"] == 42
    assert sanitized["auth_header"] == "[REDACTED_CREDENTIAL]"


def test_payload_bounding_truncates_long_strings() -> None:
    """Verify strings longer than 2048 characters are truncated."""
    long_string = "a" * 3000
    raw = {"data": long_string, "short": "ok"}
    sanitized = sanitize_bounded_dict(raw)
    assert sanitized["short"] == "ok"
    assert len(sanitized["data"]) < 2100
    assert sanitized["data"].endswith("... [TRUNCATED]")


# ==============================================================================
# 4. Migrations & Version Tracking Tests
# ==============================================================================


def test_migrations_applied_and_idempotent() -> None:
    """Verify SQLite migrations apply cleanly and are completely idempotent."""
    conn = sqlite3.connect(":memory:")
    try:
        # First application
        applied_1 = apply_job_migrations(conn)
        assert applied_1 == 1
        assert get_current_job_schema_version(conn) == 1

        # Second application should do nothing
        applied_2 = apply_job_migrations(conn)
        assert applied_2 == 0
        assert get_current_job_schema_version(conn) == 1
    finally:
        conn.close()


# ==============================================================================
# 5. Job CRUD & Lifecycle Event Tests
# ==============================================================================


def test_create_and_get_job(memory_repo: SQLiteJobRepository) -> None:
    """Verify Job persistence, retrieval, and automatic initial event creation."""
    job = Job(
        job_type="batch_eval",
        project_id="prj_default",
        payload_summary={"target": "eval_1", "api_key": "leaked_secret"},
    )
    created = memory_repo.create_job(job)
    assert created.job_id == job.job_id

    retrieved = memory_repo.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id
    assert retrieved.job_type == "batch_eval"
    assert retrieved.project_id == "prj_default"
    assert retrieved.status == JobStatus.CREATED
    # Verifies payload sanitization occurred at persistence layer
    assert retrieved.payload_summary["api_key"] == "[REDACTED_CREDENTIAL]"

    # Initial event check
    events = memory_repo.list_events(job.job_id)
    assert len(events) == 1
    assert events[0].event_type == JobEventType.JOB_CREATED
    assert events[0].metadata["initial_status"] == "created"


def test_get_nonexistent_job_returns_none(memory_repo: SQLiteJobRepository) -> None:
    """Verify querying non-existent job returns None."""
    assert memory_repo.get_job("job_doesnotexist") is None


def test_update_job_state_valid(memory_repo: SQLiteJobRepository) -> None:
    """Verify valid state progression and automatic terminal timestamp setting."""
    job = memory_repo.create_job(Job(job_type="etl"))

    # CREATED -> READY
    ready_job = memory_repo.update_state(job.job_id, JobStatus.READY)
    assert ready_job.status == JobStatus.READY
    assert ready_job.completed_at is None

    # READY -> RUNNING
    running_job = memory_repo.update_state(job.job_id, JobStatus.RUNNING)
    assert running_job.status == JobStatus.RUNNING
    assert running_job.completed_at is None

    # RUNNING -> COMPLETED
    completed_job = memory_repo.update_state(job.job_id, JobStatus.COMPLETED)
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.completed_at is not None

    # Check events emitted
    events = memory_repo.list_events(job.job_id)
    assert len(events) == 4  # CREATED + 3 state changes
    state_events = [e for e in events if e.event_type == JobEventType.JOB_STATE_CHANGED]
    assert len(state_events) == 3
    assert state_events[0].metadata["from_status"] == "created"
    assert state_events[0].metadata["to_status"] == "ready"
    assert state_events[2].metadata["from_status"] == "running"
    assert state_events[2].metadata["to_status"] == "completed"


def test_update_job_state_illegal_transition_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify attempting an illegal transition raises InvalidStateTransitionError and does not update job."""
    job = memory_repo.create_job(Job(job_type="indexing"))

    # CREATED -> COMPLETED is illegal
    with pytest.raises(InvalidStateTransitionError):
        memory_repo.update_state(job.job_id, JobStatus.COMPLETED)

    # Status must remain CREATED
    fresh = memory_repo.get_job(job.job_id)
    assert fresh is not None
    assert fresh.status == JobStatus.CREATED


def test_update_state_nonexistent_job_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify update_state on missing job raises JobNotFoundError."""
    with pytest.raises(JobNotFoundError):
        memory_repo.update_state("job_unknown", JobStatus.READY)


def test_list_jobs_filtering(memory_repo: SQLiteJobRepository) -> None:
    """Verify filtering jobs by project and status, and ordering by created_at DESC."""
    job1 = memory_repo.create_job(Job(job_type="type_a", project_id="p1"))
    job2 = memory_repo.create_job(Job(job_type="type_b", project_id="p2"))
    job3 = memory_repo.create_job(Job(job_type="type_c", project_id="p1"))

    memory_repo.update_state(job2.job_id, JobStatus.READY)

    # Filter by project_id
    p1_jobs = memory_repo.list_jobs(project_id="p1")
    assert len(p1_jobs) == 2
    assert {j.job_id for j in p1_jobs} == {job1.job_id, job3.job_id}

    # Filter by status
    ready_jobs = memory_repo.list_jobs(status=JobStatus.READY)
    assert len(ready_jobs) == 1
    assert ready_jobs[0].job_id == job2.job_id

    # Filter by both
    p2_ready = memory_repo.list_jobs(project_id="p2", status=JobStatus.READY)
    assert len(p2_ready) == 1
    assert p2_ready[0].job_id == job2.job_id

    # Pagination
    paginated = memory_repo.list_jobs(limit=1, offset=0)
    assert len(paginated) == 1


# ==============================================================================
# 6. Job Attempts & Execution Binding Tests
# ==============================================================================


def test_create_attempts_monotonic_numbering(memory_repo: SQLiteJobRepository) -> None:
    """Verify attempts increment monotonically per job (1, 2, 3...) and link to executions."""
    job = memory_repo.create_job(Job(job_type="retryable_task"))

    # Attempt 1 without execution_id
    att1 = memory_repo.create_attempt(job.job_id)
    assert att1.attempt_number == 1
    assert att1.execution_id is None
    assert att1.status == JobAttemptStatus.PENDING

    # Attempt 2 with canonical execution_id
    att2 = memory_repo.create_attempt(job.job_id, execution_id="exec_9a8b7c")
    assert att2.attempt_number == 2
    assert att2.execution_id == "exec_9a8b7c"

    # List attempts
    attempts = memory_repo.list_attempts(job.job_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_number == 1
    assert attempts[1].attempt_number == 2

    # Events emitted
    events = memory_repo.list_events(job.job_id)
    attempt_events = [e for e in events if e.event_type == JobEventType.ATTEMPT_CREATED]
    assert len(attempt_events) == 2
    exec_events = [e for e in events if e.event_type == JobEventType.EXECUTION_BOUND]
    assert len(exec_events) == 1
    assert exec_events[0].metadata["execution_id"] == "exec_9a8b7c"


def test_update_attempt_status(memory_repo: SQLiteJobRepository) -> None:
    """Verify updating attempt status and failure classification."""
    job = memory_repo.create_job(Job(job_type="fragile_task"))
    att = memory_repo.create_attempt(job.job_id)

    updated = memory_repo.update_attempt_status(
        attempt_id=att.attempt_id,
        status=JobAttemptStatus.FAILED,
        finished_at="2026-10-10T12:00:00Z",
        failure_classification="TimeoutError",
        failure_message="Execution exceeded 300s deadline",
    )
    assert updated.status == JobAttemptStatus.FAILED
    assert updated.finished_at == "2026-10-10T12:00:00Z"
    assert updated.failure_classification == "TimeoutError"
    assert updated.failure_message == "Execution exceeded 300s deadline"

    # Verify retrieval
    retrieved = memory_repo.get_attempt(att.attempt_id)
    assert retrieved is not None
    assert retrieved.status == JobAttemptStatus.FAILED


def test_create_attempt_for_nonexistent_job_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify create_attempt raises JobNotFoundError on missing job."""
    with pytest.raises(JobNotFoundError):
        memory_repo.create_attempt("job_nonexistent")


# ==============================================================================
# 7. Job Event Audit Tests
# ==============================================================================


def test_append_event_and_list_with_attempt_filter(memory_repo: SQLiteJobRepository) -> None:
    """Verify custom audit events with attempt-level filtering and redaction."""
    job = memory_repo.create_job(Job(job_type="audit_test"))
    att = memory_repo.create_attempt(job.job_id)

    custom_event = JobEvent(
        job_id=job.job_id,
        attempt_id=att.attempt_id,
        event_type=JobEventType.EXECUTION_BOUND,
        metadata={"token": "secret_token_123", "step": "step_1"},
    )
    memory_repo.append_event(custom_event)

    all_events = memory_repo.list_events(job.job_id)
    # job_created + attempt_created + custom_event = 3
    assert len(all_events) == 3

    # Filter by attempt_id
    att_events = memory_repo.list_events(job.job_id, attempt_id=att.attempt_id)
    assert len(att_events) == 2
    # Verify metadata redaction
    bound_event = [e for e in att_events if e.event_id == custom_event.event_id][0]
    assert bound_event.metadata["token"] == "[REDACTED_CREDENTIAL]"
    assert bound_event.metadata["step"] == "step_1"


# ==============================================================================
# 8. Dependency Graph & Cycle Detection Tests
# ==============================================================================


def test_self_dependency_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify a job cannot depend on itself."""
    job = memory_repo.create_job(Job(job_type="solo"))
    dep = JobDependency(job_id=job.job_id, depends_on_job_id=job.job_id)
    with pytest.raises(SelfDependencyError):
        memory_repo.add_dependency(dep)


def test_missing_job_dependency_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify referencing nonexistent jobs in dependencies raises JobNotFoundError."""
    job = memory_repo.create_job(Job(job_type="dep_test"))
    with pytest.raises(JobNotFoundError):
        memory_repo.add_dependency(
            JobDependency(job_id=job.job_id, depends_on_job_id="job_missing")
        )
    with pytest.raises(JobNotFoundError):
        memory_repo.add_dependency(
            JobDependency(job_id="job_missing", depends_on_job_id=job.job_id)
        )


def test_duplicate_dependency_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify duplicate dependency registration is rejected."""
    job1 = memory_repo.create_job(Job(job_type="step1"))
    job2 = memory_repo.create_job(Job(job_type="step2"))

    dep = JobDependency(job_id=job2.job_id, depends_on_job_id=job1.job_id)
    memory_repo.add_dependency(dep)

    with pytest.raises(DuplicateDependencyError):
        memory_repo.add_dependency(dep)


def test_direct_dependency_cycle_detection(memory_repo: SQLiteJobRepository) -> None:
    """Verify direct cycle (A -> B, B -> A) is rejected with DependencyCycleError."""
    job_a = memory_repo.create_job(Job(job_type="task_a"))
    job_b = memory_repo.create_job(Job(job_type="task_b"))

    # A depends on B
    memory_repo.add_dependency(JobDependency(job_id=job_a.job_id, depends_on_job_id=job_b.job_id))

    # B depends on A would create cycle A -> B -> A
    with pytest.raises(DependencyCycleError) as exc_info:
        memory_repo.add_dependency(
            JobDependency(job_id=job_b.job_id, depends_on_job_id=job_a.job_id)
        )
    assert "creates a cycle" in str(exc_info.value)


def test_transitive_dependency_cycle_detection(memory_repo: SQLiteJobRepository) -> None:
    """Verify indirect multi-node cycle (A -> B -> C -> D, D -> A) is detected and rejected."""
    j_a = memory_repo.create_job(Job(job_type="a"))
    j_b = memory_repo.create_job(Job(job_type="b"))
    j_c = memory_repo.create_job(Job(job_type="c"))
    j_d = memory_repo.create_job(Job(job_type="d"))

    # A depends on B, B depends on C, C depends on D
    memory_repo.add_dependency(JobDependency(job_id=j_a.job_id, depends_on_job_id=j_b.job_id))
    memory_repo.add_dependency(JobDependency(job_id=j_b.job_id, depends_on_job_id=j_c.job_id))
    memory_repo.add_dependency(JobDependency(job_id=j_c.job_id, depends_on_job_id=j_d.job_id))

    # D depends on A would create cycle A -> B -> C -> D -> A
    with pytest.raises(DependencyCycleError):
        memory_repo.add_dependency(JobDependency(job_id=j_d.job_id, depends_on_job_id=j_a.job_id))


def test_valid_dag_diamond_allowed(memory_repo: SQLiteJobRepository) -> None:
    """Verify valid diamond dependency structures (A -> B, A -> C, B -> D, C -> D) are permitted."""
    j_a = memory_repo.create_job(Job(job_type="a"))
    j_b = memory_repo.create_job(Job(job_type="b"))
    j_c = memory_repo.create_job(Job(job_type="c"))
    j_d = memory_repo.create_job(Job(job_type="d"))

    # Diamond:
    #      j_a
    #     /   \
    #   j_b   j_c
    #     \   /
    #      j_d
    memory_repo.add_dependency(JobDependency(job_id=j_a.job_id, depends_on_job_id=j_b.job_id))
    memory_repo.add_dependency(JobDependency(job_id=j_a.job_id, depends_on_job_id=j_c.job_id))
    memory_repo.add_dependency(JobDependency(job_id=j_b.job_id, depends_on_job_id=j_d.job_id))
    memory_repo.add_dependency(JobDependency(job_id=j_c.job_id, depends_on_job_id=j_d.job_id))

    deps_a = memory_repo.list_dependencies(j_a.job_id)
    assert len(deps_a) == 2
    assert {d.depends_on_job_id for d in deps_a} == {j_b.job_id, j_c.job_id}


# ==============================================================================
# 9. Artifact Association Tests
# ==============================================================================


def test_attach_and_list_artifacts(memory_repo: SQLiteJobRepository) -> None:
    """Verify associating canonical R1 artifacts (art_...) with a job."""
    job = memory_repo.create_job(Job(job_type="code_generator"))

    art1 = JobArtifact(
        job_id=job.job_id,
        artifact_id="art_8f3a1b0c",
        role="output",
    )
    art2 = JobArtifact(
        job_id=job.job_id,
        artifact_id="art_1a2b3c4d",
        role="checkpoint",
    )

    memory_repo.attach_artifact(art1)
    memory_repo.attach_artifact(art2)

    artifacts = memory_repo.list_artifacts(job.job_id)
    assert len(artifacts) == 2
    assert {a.artifact_id for a in artifacts} == {"art_8f3a1b0c", "art_1a2b3c4d"}

    events = memory_repo.list_events(job.job_id)
    art_events = [e for e in events if e.event_type == JobEventType.ARTIFACT_ATTACHED]
    assert len(art_events) == 2


def test_attach_artifact_nonexistent_job_raises(memory_repo: SQLiteJobRepository) -> None:
    """Verify attaching an artifact to a missing job raises JobNotFoundError."""
    art = JobArtifact(job_id="job_nonexistent", artifact_id="art_123")
    with pytest.raises(JobNotFoundError):
        memory_repo.attach_artifact(art)


# ==============================================================================
# 10. Schedule Definition Tests
# ==============================================================================


def test_create_and_list_schedules(memory_repo: SQLiteJobRepository) -> None:
    """Verify schedule creation, filtering, and retrieval."""
    sch1 = JobSchedule(
        job_type="nightly_cleanup",
        cron_expression="0 2 * * *",
        timezone="UTC",
        enabled=True,
    )
    sch2 = JobSchedule(
        job_type="weekly_report",
        cron_expression="0 0 * * 0",
        timezone="America/New_York",
        enabled=False,
    )

    memory_repo.create_schedule(sch1)
    memory_repo.create_schedule(sch2)

    retrieved = memory_repo.get_schedule(sch1.schedule_id)
    assert retrieved is not None
    assert retrieved.job_type == "nightly_cleanup"
    assert retrieved.cron_expression == "0 2 * * *"
    assert retrieved.enabled is True

    all_schedules = memory_repo.list_schedules(enabled_only=False)
    assert len(all_schedules) == 2

    enabled_schedules = memory_repo.list_schedules(enabled_only=True)
    assert len(enabled_schedules) == 1
    assert enabled_schedules[0].schedule_id == sch1.schedule_id


# ==============================================================================
# 11. Database Restart & Reopen Persistence Evidence
# ==============================================================================


def test_restart_persistence_proof(tmp_path: Path) -> None:
    """Evidence test: Write complete job domain data to file-backed DB,

    close the repository completely, re-open with a brand new repository instance,
    and verify every entity, relation, and audit log is 100% durable and intact.
    """
    db_path = str(tmp_path / "persistence_evidence.db")

    # PHASE 1: Write data in first session
    repo_session1 = SQLiteJobRepository(db_path=db_path)

    # 1. Create two jobs
    job_parent = repo_session1.create_job(
        Job(job_type="upstream_fetch", project_id="p_persist", payload_summary={"key": "val1"})
    )
    job_child = repo_session1.create_job(
        Job(job_type="downstream_process", project_id="p_persist", payload_summary={"key": "val2"})
    )

    # Progress parent job state
    repo_session1.update_state(job_parent.job_id, JobStatus.READY)
    repo_session1.update_state(job_parent.job_id, JobStatus.RUNNING)
    repo_session1.update_state(job_parent.job_id, JobStatus.COMPLETED)

    # 2. Create attempts on parent
    att1 = repo_session1.create_attempt(job_parent.job_id, execution_id="exec_p1")
    repo_session1.update_attempt_status(
        att1.attempt_id, JobAttemptStatus.COMPLETED, finished_at="2026-10-10T01:00:00Z"
    )

    # 3. Create dependency: child depends on parent
    repo_session1.add_dependency(
        JobDependency(
            job_id=job_child.job_id,
            depends_on_job_id=job_parent.job_id,
            dependency_type=JobDependencyType.COMPLETION,
        )
    )

    # 4. Attach artifact
    repo_session1.attach_artifact(
        JobArtifact(
            job_id=job_parent.job_id,
            artifact_id="art_proof_12345",
            role="final_report",
        )
    )

    # 5. Create schedule
    schedule = repo_session1.create_schedule(
        JobSchedule(
            job_type="downstream_process",
            cron_expression="*/15 * * * *",
            enabled=True,
        )
    )

    # Explicitly shutdown session 1
    repo_session1.close()

    # PHASE 2: Start brand new session pointing to identical DB file
    repo_session2 = SQLiteJobRepository(db_path=db_path)
    try:
        # Verify schema version
        conn = repo_session2._get_connection()
        try:
            assert get_current_job_schema_version(conn) == 1
        finally:
            conn.close()

        # Verify parent job
        reopened_parent = repo_session2.get_job(job_parent.job_id)
        assert reopened_parent is not None
        assert reopened_parent.job_id == job_parent.job_id
        assert reopened_parent.status == JobStatus.COMPLETED
        assert reopened_parent.completed_at is not None
        assert reopened_parent.payload_summary == {"key": "val1"}

        # Verify child job
        reopened_child = repo_session2.get_job(job_child.job_id)
        assert reopened_child is not None
        assert reopened_child.job_id == job_child.job_id
        assert reopened_child.status == JobStatus.CREATED

        # Verify attempts
        reopened_attempts = repo_session2.list_attempts(job_parent.job_id)
        assert len(reopened_attempts) == 1
        assert reopened_attempts[0].attempt_id == att1.attempt_id
        assert reopened_attempts[0].attempt_number == 1
        assert reopened_attempts[0].execution_id == "exec_p1"
        assert reopened_attempts[0].status == JobAttemptStatus.COMPLETED
        assert reopened_attempts[0].finished_at == "2026-10-10T01:00:00Z"

        # Verify dependencies
        reopened_deps = repo_session2.list_dependencies(job_child.job_id)
        assert len(reopened_deps) == 1
        assert reopened_deps[0].depends_on_job_id == job_parent.job_id
        assert reopened_deps[0].dependency_type == JobDependencyType.COMPLETION

        # Verify artifacts
        reopened_arts = repo_session2.list_artifacts(job_parent.job_id)
        assert len(reopened_arts) == 1
        assert reopened_arts[0].artifact_id == "art_proof_12345"
        assert reopened_arts[0].role == "final_report"

        # Verify schedules
        reopened_sch = repo_session2.get_schedule(schedule.schedule_id)
        assert reopened_sch is not None
        assert reopened_sch.job_type == "downstream_process"
        assert reopened_sch.cron_expression == "*/15 * * * *"
        assert reopened_sch.enabled is True

        # Verify audit events
        reopened_events = repo_session2.list_events(job_parent.job_id)
        # Events: job_created, 3x job_state_changed, attempt_created, execution_bound, artifact_attached = 7
        assert len(reopened_events) >= 6
        event_types = [e.event_type for e in reopened_events]
        assert JobEventType.JOB_CREATED in event_types
        assert JobEventType.JOB_STATE_CHANGED in event_types
        assert JobEventType.ATTEMPT_CREATED in event_types
        assert JobEventType.EXECUTION_BOUND in event_types
        assert JobEventType.ARTIFACT_ATTACHED in event_types
    finally:
        repo_session2.close()


# ==============================================================================
# 12. Foreign Key Cascade & Thread Safety Tests
# ==============================================================================


def test_foreign_key_cascades_on_job_deletion(tmp_path: Path) -> None:
    """Verify deleting a Job cascades and removes child attempts, events, and artifacts."""
    db_path = str(tmp_path / "cascade_test.db")
    repo = SQLiteJobRepository(db_path=db_path)
    try:
        job = repo.create_job(Job(job_type="to_delete"))
        repo.create_attempt(job.job_id)
        repo.attach_artifact(JobArtifact(job_id=job.job_id, artifact_id="art_cascade"))

        # Verify existence
        assert len(repo.list_attempts(job.job_id)) == 1
        assert len(repo.list_artifacts(job.job_id)) == 1
        assert len(repo.list_events(job.job_id)) >= 2

        # Delete job directly via raw SQL
        conn = repo._get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM jobs WHERE job_id = ?", (job.job_id,))
        finally:
            conn.close()

        # Verify child records were cascaded
        conn2 = repo._get_connection()
        try:
            cur = conn2.cursor()
            cur.execute("SELECT COUNT(*) FROM job_attempts WHERE job_id = ?", (job.job_id,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM job_events WHERE job_id = ?", (job.job_id,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM job_artifacts WHERE job_id = ?", (job.job_id,))
            assert cur.fetchone()[0] == 0
        finally:
            conn2.close()
    finally:
        repo.close()


def test_concurrent_attempt_creation_thread_safety(tmp_path: Path) -> None:
    """Verify thread safety: concurrent threads adding attempts get monotonic numbers with zero collisions."""
    db_path = str(tmp_path / "concurrent_attempts.db")
    repo = SQLiteJobRepository(db_path=db_path)
    try:
        job = repo.create_job(Job(job_type="concurrent_job"))

        num_threads = 8

        def worker(idx: int) -> int:
            att = repo.create_attempt(job.job_id, execution_id=f"exec_worker_{idx}")
            return att.attempt_number

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == num_threads
        assert sorted(results) == list(range(1, num_threads + 1))
    finally:
        repo.close()
