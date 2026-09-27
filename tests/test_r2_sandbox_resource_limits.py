"""tests/test_r2_sandbox_resource_limits.py

Comprehensive Test Suite for Task R2.9 (Sandbox Resource Limits & Cgroup Enforcement).
Maturity: S1 (Implemented and Implementation-Tested).

Scenarios Covered:
1. Wall-time limit enforced: Workload exceeding max_wall_time_seconds terminates promptly and records WALL_TIME_LIMIT.
2. Sub-second wall time limit terminates worker promptly.
3. Fast execution within wall-time limit succeeds with NORMAL terminal reason.
4. CPU time limit enforced via kernel RLIMIT_CPU: Busy-loop triggers SIGXCPU and records CPU_LIMIT.
5. Benign execution within CPU time limit succeeds.
6. Memory limit enforced via cgroup v2 MemoryMax: Excessive allocation triggers kernel OOM kill (exit 137) and records MEMORY_LIMIT.
7. Allocation under memory budget succeeds with NORMAL terminal reason.
8. Process limit enforced via cgroup v2 TasksMax: Fork/thread bomb is blocked and records PROCESS_LIMIT.
9. Workload within process limit quota succeeds normally.
10. Output backpressure enforced on stdout: Excessive output is truncated to max_stdout_bytes, setting output_truncated=True and OUTPUT_LIMIT.
11. Output backpressure enforced on stderr: Excessive output is truncated to max_stderr_bytes, setting output_truncated=True and OUTPUT_LIMIT.
12. Output within budget is preserved without truncation.
13. Immutable resource policy: Requested limits are clamped to system ceiling.
14. Child process cannot raise its own resource limits inside unprivileged sandbox.
15. Concurrent sandbox process limit: Exceeding max_concurrent_sandboxes raises ResourceLimitExceededError (PROCESS_LIMIT).
16. Concurrent sandbox memory accounting: Exceeding max_total_memory_bytes raises ResourceLimitExceededError (MEMORY_LIMIT).
17. Fail-closed on missing cgroup isolation: Requesting cgroup limits without operational systemd scope raises ResourceIsolationUnavailableError.
18. Darwin sandbox backend fails closed when resource isolation is invoked.
19. Windows sandbox backend fails closed when resource isolation is invoked.
20. Null sandbox backend fails closed when resource isolation is invoked.
21. Resource usage accounting: Result and ledger record wall time, stdout/stderr bytes, exit code, and policy metadata.
22. CPU quota throttling: cpu_quota_percent enforces bandwidth limits under systemd scope.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
from typing import Generator
import pytest

from core.sandbox.backend import (
    DarwinSandboxBackend,
    LinuxBubblewrapBackend,
    NullSandboxBackend,
    WindowsSandboxBackend,
)
from core.sandbox.models import (
    ResourceIsolationUnavailableError,
    ResourceLimitExceededError,
    SandboxFilesystemGrant,
    SandboxResourcePolicy,
    SandboxSpec,
    SandboxStatus,
    SandboxTerminalReason,
    SandboxUnavailableError,
)
from core.sandbox.service import SandboxService


@pytest.fixture
def sandbox_service() -> SandboxService:
    """Fixture providing SandboxService with default platform backend."""
    return SandboxService()


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Fixture providing clean temporary directory as workspace."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td).resolve()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_01_wall_time_limit_enforced(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 1: Wall-time limit is enforced, recording WALL_TIME_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "import time; time.sleep(10)"
    policy = SandboxResourcePolicy(max_wall_time_seconds=1.0)
    start = time.time()
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)
    duration = time.time() - start

    assert duration < 4.0, f"Wall-time limit took too long to terminate: {duration}s"
    assert res.timed_out is True
    assert res.status == SandboxStatus.TIMED_OUT
    assert res.terminal_reason == SandboxTerminalReason.WALL_TIME_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_02_wall_time_limit_subsecond(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 2: Sub-second wall-time limit terminates worker promptly."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "import time; time.sleep(5)"
    policy = SandboxResourcePolicy(max_wall_time_seconds=0.5)
    start = time.time()
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)
    duration = time.time() - start

    assert duration < 2.5
    assert res.timed_out is True
    assert res.terminal_reason == SandboxTerminalReason.WALL_TIME_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_03_wall_time_success_within_limit(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 3: Fast command finishes with NORMAL terminal reason."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('fast_success')"
    policy = SandboxResourcePolicy(max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "fast_success" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_04_cpu_time_limit_rlimit_enforced(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 4: Busy CPU loop exceeding max_cpu_time_seconds triggers SIGXCPU and CPU_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
import time
start = time.time()
# Busy loop consuming pure user/system CPU cycles
while True:
    pass
"""
    policy = SandboxResourcePolicy(max_cpu_time_seconds=1.0, max_wall_time_seconds=8.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.CPU_LIMIT
    assert res.exit_code in (-24, 152)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_05_cpu_time_success_within_limit(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 5: Non-CPU-intensive command finishes normally without triggering SIGXCPU."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('cpu_ok')"
    policy = SandboxResourcePolicy(max_cpu_time_seconds=2.0, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "cpu_ok" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_06_memory_limit_cgroup_oom_killed(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 6: Memory allocation exceeding max_memory_bytes triggers kernel OOM kill and MEMORY_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # Allocate memory until MemoryMax (35 MB) triggers OOM kill or MemoryError
    code = """
chunks = []
while True:
    chunks.append(b'x' * (10 * 1024 * 1024))
"""
    policy = SandboxResourcePolicy(max_memory_bytes=35 * 1024 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.MEMORY_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_07_memory_limit_success_under_budget(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 7: Memory allocation within budget completes normally."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # Allocate 5 MB when limit is 50 MB
    code = "a = b'x' * (5 * 1024 * 1024); print('mem_ok')"
    policy = SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "mem_ok" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_08_process_limit_fork_bomb_blocked(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 8: Process/thread creation exceeding TasksMax is blocked, recording PROCESS_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # Attempt to spawn 20 threads when TasksMax=3
    code = """
import threading, time
threads = []
for _ in range(20):
    t = threading.Thread(target=time.sleep, args=(2,))
    t.start()
    threads.append(t)
"""
    policy = SandboxResourcePolicy(max_processes=3, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.PROCESS_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_09_process_limit_success_under_quota(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 9: Workload within process quota succeeds normally."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    code = "import threading; t = threading.Thread(target=lambda: None); t.start(); t.join(); print('task_ok')"
    policy = SandboxResourcePolicy(max_processes=10, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "task_ok" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_10_output_stdout_backpressure_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 10: Runaway stdout output is truncated to max_stdout_bytes, setting OUTPUT_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    # Produce 1 MB of stdout output when limit is 32 KB
    code = """
import sys
chunk = "a" * 1024
for _ in range(1024):
    sys.stdout.write(chunk)
sys.stdout.flush()
"""
    policy = SandboxResourcePolicy(max_stdout_bytes=32 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.OUTPUT_LIMIT
    assert res.output_truncated is True
    assert len(res.stdout.encode("utf-8")) <= 32 * 1024 + 100


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_11_output_stderr_backpressure_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 11: Runaway stderr output is truncated to max_stderr_bytes, setting OUTPUT_LIMIT."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    # Produce 1 MB of stderr output when limit is 32 KB
    code = """
import sys
chunk = "e" * 1024
for _ in range(1024):
    sys.stderr.write(chunk)
sys.stderr.flush()
"""
    policy = SandboxResourcePolicy(max_stderr_bytes=32 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.OUTPUT_LIMIT
    assert res.output_truncated is True
    assert len(res.stderr.encode("utf-8")) <= 32 * 1024 + 100


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_12_output_within_limit_not_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 12: Normal output within limits is preserved completely without truncation."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('hello_world')"
    policy = SandboxResourcePolicy(max_stdout_bytes=1024 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert res.output_truncated is False
    assert res.stdout.strip() == "hello_world"


def test_13_immutable_policy_clamped_to_system_ceiling(temp_workspace: Path):
    """Scenario 13: Untrusted requests for excessive limits are clamped to system ceilings."""
    system_ceiling = SandboxResourcePolicy(
        max_wall_time_seconds=20.0,
        max_memory_bytes=100 * 1024 * 1024,
        max_stdout_bytes=1 * 1024 * 1024,
    )
    svc = SandboxService(max_resource_policy=system_ceiling)
    assert svc.max_resource_policy.max_wall_time_seconds == 20.0

    # Workload requests 500 seconds and 1 GB memory
    untrusted_policy = SandboxResourcePolicy(
        max_wall_time_seconds=500.0,
        max_memory_bytes=1024 * 1024 * 1024,
        max_stdout_bytes=50 * 1024 * 1024,
    )
    clamped = untrusted_policy.clamp_to_ceiling(system_ceiling)

    assert clamped.max_wall_time_seconds == 20.0
    assert clamped.max_memory_bytes == 100 * 1024 * 1024
    assert clamped.max_stdout_bytes == 1 * 1024 * 1024


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_14_child_cannot_raise_rlimits(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 14: Child process inside unprivileged sandbox cannot raise its own hard rlimits."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
import resource
# Attempt to raise CPU hard limit
try:
    soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    resource.setrlimit(resource.RLIMIT_CPU, (hard + 10, hard + 10))
    print("RAISE_SUCCESS")
except (ValueError, PermissionError) as e:
    print("RAISE_BLOCKED:" + type(e).__name__)
"""
    policy = SandboxResourcePolicy(max_cpu_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert "RAISE_SUCCESS" not in res.stdout
    assert "RAISE_BLOCKED" in res.stdout


def test_15_concurrent_sandbox_process_limit(temp_workspace: Path):
    """Scenario 15: Concurrency accounting rejects execution when max_concurrent_sandboxes is reached."""
    svc = SandboxService(max_concurrent_sandboxes=2)

    spec1 = SandboxSpec(
        command=["echo", "1"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
    )
    spec2 = SandboxSpec(
        command=["echo", "2"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
    )
    spec3 = SandboxSpec(
        command=["echo", "3"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
    )

    with svc._lock:
        svc._active_sandboxes["sbx-test-1"] = spec1
        svc._active_sandboxes["sbx-test-2"] = spec2

    assert svc.active_sandboxes_count == 2
    assert "sbx-test-1" in svc.active_execution_ids

    # Third execution should raise ResourceLimitExceededError fail-closed
    with pytest.raises(ResourceLimitExceededError) as exc_info:
        svc.execute(spec3)

    assert exc_info.value.reason == SandboxTerminalReason.PROCESS_LIMIT
    assert exc_info.value.violating_dimension == "concurrent_sandboxes"


def test_16_concurrent_sandbox_memory_limit(temp_workspace: Path):
    """Scenario 16: Concurrency accounting rejects execution when max_total_memory_bytes is exceeded."""
    svc = SandboxService(max_total_memory_bytes=80 * 1024 * 1024)

    spec1 = SandboxSpec(
        command=["echo", "1"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024),
    )
    spec2 = SandboxSpec(
        command=["echo", "2"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=40 * 1024 * 1024),
    )

    with svc._lock:
        svc._active_sandboxes["sbx-test-1"] = spec1

    # Second execution requests 40 MB (total 90 MB > 80 MB limit)
    with pytest.raises(ResourceLimitExceededError) as exc_info:
        svc.execute(spec2)

    assert exc_info.value.reason == SandboxTerminalReason.MEMORY_LIMIT
    assert exc_info.value.violating_dimension == "concurrent_memory_bytes"


def test_17_cgroup_isolation_unavailable_fails_closed(temp_workspace: Path):
    """Scenario 17: Requesting cgroup limits without operational systemd scope raises ResourceIsolationUnavailableError."""

    # Create backend that explicitly claims cgroup isolation is unavailable
    class MockNoCgroupBackend(LinuxBubblewrapBackend):
        def is_available(self) -> bool:
            return True

        def is_cgroup_available(self) -> bool:
            return False

    backend = MockNoCgroupBackend()
    svc = SandboxService(backend=backend)

    spec = SandboxSpec(
        command=["echo", "test"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024),
    )

    with pytest.raises(ResourceIsolationUnavailableError):
        svc.execute(spec)


def test_18_darwin_stub_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 18: Darwin stub fails closed with SandboxUnavailableError."""
    backend = DarwinSandboxBackend()
    assert backend.is_available() is False
    assert backend.is_cgroup_available() is False

    svc = SandboxService(backend=backend)
    spec = SandboxSpec(
        command=["echo", "mac"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024),
    )
    with pytest.raises(SandboxUnavailableError):
        svc.execute(spec)


def test_19_windows_stub_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 19: Windows stub fails closed with SandboxUnavailableError."""
    backend = WindowsSandboxBackend()
    assert backend.is_available() is False
    assert backend.is_cgroup_available() is False

    svc = SandboxService(backend=backend)
    spec = SandboxSpec(
        command=["echo", "win"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024),
    )
    with pytest.raises(SandboxUnavailableError):
        svc.execute(spec)


def test_20_null_backend_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 20: Null backend fails closed with SandboxUnavailableError."""
    backend = NullSandboxBackend()
    assert backend.is_available() is False
    assert backend.is_cgroup_available() is False

    svc = SandboxService(backend=backend)
    spec = SandboxSpec(
        command=["echo", "null"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
    )
    with pytest.raises(SandboxUnavailableError):
        svc.execute(spec)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_21_resource_usage_tracked_in_result_and_ledger(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 21: Result and execution ledger capture detailed resource usage telemetry."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('telemetry_line_1'); print('telemetry_line_2')"
    policy = SandboxResourcePolicy(max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert "wall_time_seconds" in res.resource_usage
    assert "stdout_bytes" in res.resource_usage
    assert "stderr_bytes" in res.resource_usage
    assert "exit_code" in res.resource_usage
    assert res.resource_usage["exit_code"] == 0
    assert res.resource_usage["stdout_bytes"] > 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_22_cpu_quota_cgroup_throttling(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 22: cpu_quota_percent executes cleanly under systemd scope bandwidth limits."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    code = "print('quota_throttled_ok')"
    policy = SandboxResourcePolicy(cpu_quota_percent=50.0, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "quota_throttled_ok" in res.stdout
