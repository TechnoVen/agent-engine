"""tests/test_r2_sandbox_resource_limits.py

Comprehensive Test Suite for Task R2.9 (Sandbox Resource Limits & Cgroup Enforcement).
Maturity: S1 (Implemented and Implementation-Tested).

Scenarios Covered (CTO Review Section 17 Precision Scenarios):
1. Wall-time limit enforced: Workload exceeding max_wall_time_seconds terminates promptly and records WALL_TIME_LIMIT.
2. Sub-second wall time limit terminates worker promptly.
3. Fast execution within wall-time limit succeeds with NORMAL terminal reason.
4. Cumulative CPU budget enforced: Exceeding max_cpu_time_seconds terminates scope and records CPU_LIMIT (Section 1).
5. Fast execution within CPU budget succeeds normally.
6. CPUQuota rate limiting distinct from budget kill: Throttles execution rate without killing (Section 1).
7. Wall timeout on busy loop records WALL_TIME_LIMIT, NOT CPU_LIMIT (Section 1).
8. RLIMIT_CPU hardware limit trap triggers SIGXCPU (-24/152) and records CPU_LIMIT (Section 1 & 7).
9. Memory limit enforced via cgroup v2 MemoryMax: Excessive allocation triggers kernel OOM kill and records MEMORY_LIMIT (Section 2 & 13).
10. Non-OOM SIGKILL is honestly classified as BACKEND_ERROR, NEVER MEMORY_LIMIT (Section 2).
11. Memory allocation within budget completes normally.
12. Process limit enforced via cgroup v2 TasksMax: Fork/thread bomb is blocked and records PROCESS_LIMIT (Section 7).
13. Workload within process limit quota succeeds normally.
14. Resource group overhead semantics documented: TasksMax counts all tasks in scope (bwrap + worker) (Section 6).
15. Output backpressure on stdout: Runaway output truncated to max_stdout_bytes, setting OUTPUT_LIMIT and FAILED status (Section 8 & 18).
16. Output backpressure on stderr: Runaway output truncated to max_stderr_bytes, setting OUTPUT_LIMIT and FAILED status (Section 8 & 18).
17. Concurrent stdout and stderr flood drains without pipe deadlock (Section 8).
18. Output byte counting counts bytes, not characters, for multi-byte UTF-8 (Section 8).
19. Normal output within limits is preserved completely without truncation.
20. Immutable resource policy: Requested limits are clamped to system ceiling (Section 4).
21. Untrusted policy validation: validate_for_untrusted() requires all limits bounded (Section 4).
22. Child process cannot raise its own hard RLIMIT_CPU inside unprivileged sandbox.
23. Worker cannot alter cgroup hierarchy (/sys/fs/cgroup write blocked).
24. Worker cannot escape cgroup hierarchy (cgroup.procs write blocked).
25. Concurrent sandbox process limit: Exceeding max_concurrent_sandboxes raises ResourceLimitExceededError (PROCESS_LIMIT).
26. Concurrent sandbox memory limit: Exceeding max_total_memory_bytes raises ResourceLimitExceededError (MEMORY_LIMIT).
27. Fail-closed on missing cgroup isolation: Requesting cgroup limits without operational systemd scope raises ResourceIsolationUnavailableError (Section 3).
28. Fail-closed on partial controller unavailability: Missing requested controller raises ResourceIsolationUnavailableError (Section 3).
29. Darwin sandbox backend fails closed when resource isolation is invoked.
30. Windows sandbox backend fails closed when resource isolation is invoked.
31. Null sandbox backend fails closed when resource isolation is invoked.
32. Resource usage accounting: Result captures wall time, stdout/stderr bytes, exit code, and audit-safe metrics (Section 15).
33. Network ALLOW_UNRESTRICTED requires policy approval (Section 14).
34. Secret grant to arbitrary untrusted code blocked (Section 10).
35. Non-blocking event loop: execute_async runs off-thread and does not block event loop ticks (Section 9).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import time
from typing import Dict, Generator
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
    SandboxNetworkGrant,
    SandboxNetworkMode,
    SandboxResourcePolicy,
    SandboxSecurityError,
    SandboxSpec,
    SandboxStatus,
    SandboxTerminalReason,
    SandboxUnavailableError,
)
from core.sandbox.service import SandboxService
from core.security.secrets import SecretReference


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
    assert res.status == SandboxStatus.TIMED_OUT
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
def test_04_cpu_time_budget_enforced(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 4: Cumulative CPU budget exceeded terminates with CPU_LIMIT (CTO Review Section 1)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    code = """
import time
# Busy loop consuming cumulative CPU time
while True:
    pass
"""
    # max_cpu_time_seconds = 1.0; wall time is larger (8.0s) so CPU budget triggers first
    policy = SandboxResourcePolicy(max_cpu_time_seconds=1.0, max_wall_time_seconds=8.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.CPU_LIMIT
    assert res.timed_out is False
    assert res.resource_usage.get("cpu_time_seconds", 0.0) >= 0.95


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_05_cpu_time_success_within_limit(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 5: Benign execution finishes normally within CPU budget."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('cpu_ok')"
    policy = SandboxResourcePolicy(max_cpu_time_seconds=2.0, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert "cpu_ok" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_06_cpu_quota_rate_limiting_distinct_from_budget_kill(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 6: CPUQuota throttles rate without budget kill; succeeds with NORMAL (CTO Review Section 1)."""
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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_07_wall_time_on_busy_loop_does_not_report_cpu_limit(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 7: Wall timeout on busy loop records WALL_TIME_LIMIT, NOT CPU_LIMIT (CTO Review Section 1)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "while True: pass"
    # No max_cpu_time_seconds; only max_wall_time_seconds is set
    policy = SandboxResourcePolicy(max_wall_time_seconds=0.5)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.timed_out is True
    assert res.status == SandboxStatus.TIMED_OUT
    assert res.terminal_reason == SandboxTerminalReason.WALL_TIME_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_08_rlimit_cpu_hardware_trap(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 8: Per-process hardware limit trap via rlimit_cpu_seconds triggers SIGXCPU (CTO Review Section 1 & 7)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "while True: pass"
    policy = SandboxResourcePolicy(rlimit_cpu_seconds=1, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.CPU_LIMIT
    assert res.exit_code in (-24, 152)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_09_memory_limit_cgroup_oom_killed(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 9: Memory allocation exceeding max_memory_bytes triggers kernel OOM kill and MEMORY_LIMIT (CTO Review Section 2 & 13)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    code = """
chunks = []
while True:
    chunks.append(b'x' * (10 * 1024 * 1024))
"""
    policy = SandboxResourcePolicy(
        max_memory_bytes=35 * 1024 * 1024,
        max_wall_time_seconds=10.0,
        require_swap_disabled=True,
    )
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.MEMORY_LIMIT
    assert (
        res.resource_usage.get("oom_kill_events", 0) >= 1
        or res.resource_usage.get("oom_events", 0) >= 1
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_10_non_oom_sigkill_not_classified_as_memory_limit(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 10: External SIGKILL without OOM events records BACKEND_ERROR, NEVER MEMORY_LIMIT (CTO Review Section 2)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # Command sends itself SIGKILL without allocating any memory
    code = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
    policy = SandboxResourcePolicy(max_memory_bytes=100 * 1024 * 1024, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.exit_code in (-9, 137)
    assert res.terminal_reason == SandboxTerminalReason.BACKEND_ERROR
    assert res.terminal_reason != SandboxTerminalReason.MEMORY_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_11_memory_allocation_within_limit(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 11: Memory allocation within budget completes normally."""
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
def test_12_process_limit_tasksmax_blocked(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 12: Process/thread creation exceeding TasksMax is blocked, recording PROCESS_LIMIT (CTO Review Section 7)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # Attempt to spawn 25 threads when TasksMax=5
    code = """
import threading, time
threads = []
for _ in range(25):
    t = threading.Thread(target=time.sleep, args=(2,))
    t.start()
    threads.append(t)
"""
    policy = SandboxResourcePolicy(max_processes=5, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.PROCESS_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_13_process_limit_success_under_quota(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 13: Workload within process quota succeeds normally."""
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
def test_14_resource_group_overhead_semantics_documented(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 14: Document and verify that TasksMax counts all tasks in the scope (CTO Review Section 6)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    backend = sandbox_service.backend
    if not backend.is_cgroup_available():
        pytest.skip("systemd user scope cgroup v2 not available on this host")

    # TasksMax=2 is too restrictive for supervisor + python runtime
    code = "print('too_low')"
    policy = SandboxResourcePolicy(max_processes=2, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    # Execution fails because scope tasks limit is exceeded by runtime startup overhead
    assert res.status == SandboxStatus.FAILED


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_15_output_stdout_backpressure_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 15: Runaway stdout output is truncated to max_stdout_bytes, setting OUTPUT_LIMIT (CTO Review Section 8 & 18)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

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
def test_16_output_stderr_backpressure_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 16: Runaway stderr output is truncated to max_stderr_bytes, setting OUTPUT_LIMIT (CTO Review Section 8 & 18)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

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
def test_17_concurrent_stdout_stderr_flood_no_deadlock(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 17: Simultaneous flood on stdout and stderr drains without deadlock (CTO Review Section 8)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
import sys, threading

def flood(stream, char):
    chunk = char * 1024
    for _ in range(512):
        stream.write(chunk)
        stream.flush()

t1 = threading.Thread(target=flood, args=(sys.stdout, "O"))
t2 = threading.Thread(target=flood, args=(sys.stderr, "E"))
t1.start()
t2.start()
t1.join()
t2.join()
"""
    policy = SandboxResourcePolicy(
        max_stdout_bytes=16 * 1024,
        max_stderr_bytes=16 * 1024,
        max_wall_time_seconds=8.0,
    )
    start = time.time()
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)
    duration = time.time() - start

    assert duration < 5.0, f"Concurrent flood deadlocked! Duration: {duration}s"
    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.OUTPUT_LIMIT
    assert res.output_truncated is True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_18_output_byte_counting_multibyte_utf8(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 18: Multi-byte UTF-8 emojis are counted by bytes, not characters (CTO Review Section 8)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    # 🦀 is 4 bytes. 10 crabs = 40 bytes. Limit = 20 bytes.
    code = 'import sys; sys.stdout.write("🦀" * 10); sys.stdout.flush()'
    policy = SandboxResourcePolicy(max_stdout_bytes=20, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.status == SandboxStatus.FAILED
    assert res.terminal_reason == SandboxTerminalReason.OUTPUT_LIMIT
    assert res.output_truncated is True
    assert len(res.stdout.encode("utf-8")) <= 20


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_19_output_within_limit_not_truncated(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 19: Normal output within limits is preserved completely without truncation."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = "print('hello_world')"
    policy = SandboxResourcePolicy(max_stdout_bytes=1024 * 1024, max_wall_time_seconds=10.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert res.terminal_reason == SandboxTerminalReason.NORMAL
    assert res.output_truncated is False
    assert res.stdout.strip() == "hello_world"


def test_20_immutable_policy_clamped_to_system_ceiling():
    """Scenario 20: Untrusted requests for excessive limits are clamped to system ceilings (CTO Review Section 4)."""
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


def test_21_untrusted_policy_validation_requires_all_limits():
    """Scenario 21: validate_for_untrusted() ensures all mandatory limits are explicitly set (CTO Review Section 4)."""
    valid = SandboxResourcePolicy.untrusted_default()
    valid.validate_for_untrusted()

    # None for any mandatory dimension must fail validation
    invalid = SandboxResourcePolicy(
        max_wall_time_seconds=None,
        max_cpu_time_seconds=30.0,
        max_memory_bytes=512 * 1024 * 1024,
        max_processes=32,
        max_stdout_bytes=10 * 1024 * 1024,
        max_stderr_bytes=10 * 1024 * 1024,
    )
    with pytest.raises((ValueError, ResourceLimitExceededError), match="max_wall_time_seconds"):
        invalid.validate_for_untrusted()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_22_child_cannot_raise_rlimits(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 22: Child process inside unprivileged sandbox cannot raise its own hard rlimits."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
import resource
try:
    soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    resource.setrlimit(resource.RLIMIT_CPU, (hard + 10, hard + 10))
    print("RAISE_SUCCESS")
except (ValueError, PermissionError) as e:
    print("RAISE_BLOCKED:" + type(e).__name__)
"""
    policy = SandboxResourcePolicy(rlimit_cpu_seconds=5, max_wall_time_seconds=5.0)
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace, resource_policy=policy)

    assert res.is_success
    assert "RAISE_SUCCESS" not in res.stdout
    assert "RAISE_BLOCKED" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_23_worker_cannot_alter_cgroup(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 23: Worker inside sandbox cannot alter or write to /sys/fs/cgroup (CTO Review Section 17)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
try:
    with open("/sys/fs/cgroup/cgroup.procs", "w") as f:
        f.write("1")
    print("WROTE_CGROUP")
except Exception as e:
    print("CGROUP_WRITE_BLOCKED:" + type(e).__name__)
"""
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace)
    assert res.is_success
    assert "WROTE_CGROUP" not in res.stdout
    assert "CGROUP_WRITE_BLOCKED" in res.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
def test_24_worker_cannot_escape_cgroup(sandbox_service: SandboxService, temp_workspace: Path):
    """Scenario 24: Worker inside sandbox cannot move PID into parent cgroup (CTO Review Section 17)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    code = """
import os
try:
    with open("/sys/fs/cgroup/user.slice/cgroup.procs", "w") as f:
        f.write(str(os.getpid()))
    print("ESCAPED_CGROUP")
except Exception as e:
    print("ESCAPE_BLOCKED:" + type(e).__name__)
"""
    res = sandbox_service.run_code(code, workspace_dir=temp_workspace)
    assert res.is_success
    assert "ESCAPED_CGROUP" not in res.stdout
    assert "ESCAPE_BLOCKED" in res.stdout


def test_25_concurrent_sandbox_process_limit(temp_workspace: Path):
    """Scenario 25: Concurrency accounting rejects execution when max_concurrent_sandboxes is reached."""
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


def test_26_concurrent_sandbox_memory_limit(temp_workspace: Path):
    """Scenario 26: Concurrency accounting rejects execution when max_total_memory_bytes is exceeded."""
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


def test_27_cgroup_isolation_unavailable_fails_closed(temp_workspace: Path):
    """Scenario 27: Requesting cgroup limits without operational systemd scope raises ResourceIsolationUnavailableError."""

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


def test_28_controller_partially_unavailable_fails_closed(temp_workspace: Path):
    """Scenario 28: Missing a requested cgroup controller raises ResourceIsolationUnavailableError (CTO Review Section 3)."""

    class PartialCgroupBackend(LinuxBubblewrapBackend):
        def is_available(self) -> bool:
            return True

        def probe_controllers(self, force_refresh: bool = False) -> Dict[str, bool]:
            caps = super().probe_controllers(force_refresh=force_refresh).copy()
            caps["memory"] = False  # simulate memory controller missing
            return caps

    backend = PartialCgroupBackend()
    svc = SandboxService(backend=backend)

    spec = SandboxSpec(
        command=["echo", "test"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        resource_policy=SandboxResourcePolicy(max_memory_bytes=50 * 1024 * 1024),
    )

    with pytest.raises(
        ResourceIsolationUnavailableError, match="Required cgroup v2 controller 'memory'"
    ):
        svc.execute(spec)


def test_29_darwin_stub_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 29: Darwin stub fails closed with SandboxUnavailableError."""
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


def test_30_windows_stub_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 30: Windows stub fails closed with SandboxUnavailableError."""
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


def test_31_null_backend_fails_closed_on_resource_limits(temp_workspace: Path):
    """Scenario 31: Null backend fails closed with SandboxUnavailableError."""
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
def test_32_resource_usage_tracked_in_result_and_ledger(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 32: Result captures wall time, stdout/stderr bytes, exit code, and audit-safe metrics (CTO Review Section 15)."""
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
    # Audit-safe metrics: ensure no raw host paths in resource_usage
    for k, v in res.resource_usage.items():
        assert not str(v).startswith("/sys/fs/cgroup")


def test_33_network_allow_unrestricted_requires_policy_approval(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 33: Unapproved ALLOW_UNRESTRICTED network grant is rejected fail-closed (CTO Review Section 14)."""
    spec = SandboxSpec(
        command=["echo", "net"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        network=SandboxNetworkGrant(
            mode=SandboxNetworkMode.ALLOW_UNRESTRICTED,
            authorized_by_policy=False,
        ),
    )
    with pytest.raises(SandboxSecurityError, match="explicit PolicyEngine authorization"):
        sandbox_service.execute(spec)


def test_34_secret_grant_to_arbitrary_untrusted_code_blocked(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 34: Injecting secrets into arbitrary code without capability_id is blocked (CTO Review Section 10)."""
    spec = SandboxSpec(
        command=["python3", "-c", "print('hacked')"],
        filesystem=SandboxFilesystemGrant(workspace_dir=temp_workspace),
        secret_grants=[SecretReference(provider="openai", name="api_key", project_id="p1")],
        capability_id=None,
    )
    with pytest.raises(SandboxSecurityError, match="capability_id"):
        sandbox_service.execute(spec)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap requires Linux")
@pytest.mark.anyio
async def test_35_event_loop_responsiveness_during_sandbox_execution(
    sandbox_service: SandboxService, temp_workspace: Path
):
    """Scenario 35: execute_async offloads execution and does not block the asyncio event loop (CTO Review Section 9)."""
    if not sandbox_service.is_available():
        pytest.skip("Bubblewrap backend is not available on this host")

    ticks = 0
    stop_event = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not stop_event.is_set():
            ticks += 1
            await asyncio.sleep(0.04)

    ticker_task = asyncio.create_task(ticker())

    res = await sandbox_service.run_code_async(
        "import time; time.sleep(0.4)",
        workspace_dir=temp_workspace,
        resource_policy=SandboxResourcePolicy(max_wall_time_seconds=2.0),
    )
    stop_event.set()
    await ticker_task

    assert res.is_success
    assert ticks >= 3, f"Event loop ticks was starved! ticks={ticks}"
