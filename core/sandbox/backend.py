"""core/sandbox/backend.py

Platform Backend implementations for the Sandbox Worker Runtime and Resource Limits.
Part of Milestone R2 Tasks R2.8 (Sandbox worker runtime) and R2.9 (Sandbox resource limits).

Design Invariants:
1. Bubblewrap (bwrap) on Linux provides genuine kernel namespace isolation (PID, mount, UTS, IPC, network).
2. Fail-closed on unsupported platforms (macOS / Windows): Never fall back to host execution.
3. Default-deny environment: Clean environment via --clearenv and explicit --setenv allowlisting.
4. Process tree lifecycle: start_new_session=True and killpg ensure all child and grandchild processes terminate.
5. Cooperative and force termination: Handles CancellationToken, wall time, CPU limit, memory limit, process limit, and output backpressure.
6. Audited bwrap mount set: Private HOME/TMPDIR/XDG_RUNTIME_DIR; host /home, /run, /var, /etc (root) are never mounted.
7. Enforced OS resource limits: cgroup v2 scopes via systemd-run --user and process rlimits.
"""

from __future__ import annotations

import abc
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from core.sandbox.models import (
    ResourceIsolationUnavailableError,
    SandboxMountMode,
    SandboxResult,
    SandboxSpec,
    SandboxStatus,
    SandboxTerminalReason,
    SandboxUnavailableError,
)

logger = logging.getLogger("agent_engine.sandbox.backend")


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Terminate the entire process group cleanly with SIGTERM then SIGKILL."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as e:
        logger.debug(f"Error sending SIGTERM to process group {proc.pid}: {e}")

    deadline = time.time() + 0.3
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.debug(f"Error sending SIGKILL to process group {proc.pid}: {e}")


def _read_stream_bounded(
    stream,
    max_bytes: int,
    cancel_event: threading.Event,
    chunks: List[bytes],
    truncated_flag: List[bool],
) -> None:
    """Read a binary stream up to max_bytes, signaling cancel_event if exceeded."""
    total = 0
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                excess = total - max_bytes
                keep_len = len(chunk) - excess
                if keep_len > 0:
                    chunks.append(chunk[:keep_len])
                truncated_flag[0] = True
                cancel_event.set()
                break
            chunks.append(chunk)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


class SandboxBackend(abc.ABC):
    """Abstract interface for platform-specific sandbox execution backends."""

    name: str

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check whether this backend is functional and secure on the current host."""
        pass

    @abc.abstractmethod
    def is_cgroup_available(self) -> bool:
        """Check whether OS cgroup v2 resource isolation is functional on this host."""
        pass

    @abc.abstractmethod
    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        """Execute a workload according to spec in isolated sandbox container."""
        pass


class LinuxBubblewrapBackend(SandboxBackend):
    """Linux kernel namespace isolation backend using Bubblewrap (bwrap).

    Requires unprivileged user namespaces and bwrap binary located in trusted system paths.
    Enforces resource limits via systemd-run cgroup v2 scopes and process rlimits (R2.9).
    """

    name = "linux_bubblewrap"

    def __init__(self, bwrap_path: Optional[str] = None):
        if bwrap_path is not None:
            self._bwrap_path = bwrap_path
        else:
            # Audit check: Only search trusted system directories, never untrusted CWD or relative paths
            for candidate in ("/usr/bin/bwrap", "/bin/bwrap"):
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    self._bwrap_path = candidate
                    break
            else:
                self._bwrap_path = "/usr/bin/bwrap"

        self._available: Optional[bool] = None
        self._cgroup_available: Optional[bool] = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        if not sys.platform.startswith("linux"):
            self._available = False
            return False

        if not os.path.isfile(self._bwrap_path) or not os.access(self._bwrap_path, os.X_OK):
            self._available = False
            return False

        # Probe minimal execution with unprivileged user namespaces
        try:
            probe_cmd = [
                self._bwrap_path,
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/usr",
                "/usr",
            ]
            if os.path.islink("/lib"):
                probe_cmd.extend(["--symlink", "usr/lib", "/lib"])
            if os.path.islink("/lib64"):
                probe_cmd.extend(["--symlink", "usr/lib64", "/lib64"])
            if os.path.islink("/bin"):
                probe_cmd.extend(["--symlink", "usr/bin", "/bin"])

            probe_cmd.extend(["/usr/bin/true"])
            res = subprocess.run(
                probe_cmd,
                capture_output=True,
                timeout=5.0,
            )
            self._available = res.returncode == 0
        except Exception:
            self._available = False

        return self._available

    def is_cgroup_available(self) -> bool:
        """Check whether systemd user scope cgroup v2 is operational."""
        if self._cgroup_available is not None:
            return self._cgroup_available

        if not sys.platform.startswith("linux"):
            self._cgroup_available = False
            return False

        try:
            probe_cmd = ["systemd-run", "--user", "--scope", "-q", "--", "/usr/bin/true"]
            res = subprocess.run(probe_cmd, capture_output=True, timeout=5.0)
            self._cgroup_available = res.returncode == 0
        except Exception:
            self._cgroup_available = False

        return self._cgroup_available

    def _build_bwrap_argv(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        script_file_in_workspace: Optional[str] = None,
    ) -> List[str]:
        argv = [
            self._bwrap_path,
            "--unshare-all",
            "--clearenv",
            "--die-with-parent",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
        ]

        # 1. Network isolation (default-deny)
        if not spec.network.allowed:
            argv.append("--unshare-net")
        else:
            # Network allowed: provide basic DNS and certificate paths only (audited, not host /etc root)
            for net_path in [
                "/etc/resolv.conf",
                "/etc/hosts",
                "/etc/nsswitch.conf",
                "/etc/ssl",
                "/etc/pki",
                "/etc/ca-certificates",
            ]:
                if os.path.exists(net_path):
                    argv.extend(["--ro-bind-try", net_path, net_path])

        # 2. Tmpfs & Private User Dirs (Audited bwrap mount set)
        # Invariant: Host /home, /run, /var, /etc are NEVER mounted into sandbox.
        if spec.filesystem.allow_tmpfs:
            argv.extend(["--tmpfs", "/tmp"])
            argv.extend(["--dir", "/tmp/home"])
            argv.extend(["--dir", "/tmp/run"])

        # 3. Base system read-only mounts
        argv.extend(["--ro-bind", "/usr", "/usr"])

        # Usr-merge handling (Arch, Debian modern, Fedora)
        if os.path.islink("/lib"):
            argv.extend(["--symlink", "usr/lib", "/lib"])
        elif os.path.isdir("/lib"):
            argv.extend(["--ro-bind-try", "/lib", "/lib"])

        if os.path.islink("/lib64"):
            argv.extend(["--symlink", "usr/lib64", "/lib64"])
        elif os.path.isdir("/lib64"):
            argv.extend(["--ro-bind-try", "/lib64", "/lib64"])

        if os.path.islink("/bin"):
            argv.extend(["--symlink", "usr/bin", "/bin"])
        elif os.path.isdir("/bin"):
            argv.extend(["--ro-bind-try", "/bin", "/bin"])

        if os.path.islink("/sbin"):
            argv.extend(["--symlink", "usr/bin", "/sbin"])
        elif os.path.isdir("/sbin"):
            argv.extend(["--ro-bind-try", "/sbin", "/sbin"])

        if os.path.exists("/etc/ld.so.cache"):
            argv.extend(["--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache"])
        if os.path.exists("/etc/alternatives"):
            argv.extend(["--ro-bind-try", "/etc/alternatives", "/etc/alternatives"])

        # Bind active Python environment / virtualenv if distinct from /usr
        venv_path = os.environ.get("VIRTUAL_ENV") or sys.prefix
        if venv_path and not venv_path.startswith("/usr"):
            vpath = os.path.abspath(venv_path)
            if os.path.exists(vpath):
                argv.extend(["--ro-bind", vpath, vpath])

        # 4. Workspace filesystem mounts (Item 1: Project input READ_ONLY by default)
        ws_path = str(spec.filesystem.workspace_dir.resolve())
        project_root = (
            str(spec.filesystem.project_root.resolve()) if spec.filesystem.project_root else None
        )

        # Primary project root mount
        if project_root:
            if spec.filesystem.project_mount_mode == SandboxMountMode.READ_ONLY:
                argv.extend(["--ro-bind", project_root, project_root])
            else:
                argv.extend(["--bind", project_root, project_root])

        # Workspace dir mount (if distinct from project_root)
        if not project_root or ws_path != project_root:
            if spec.filesystem.project_mount_mode == SandboxMountMode.READ_ONLY:
                argv.extend(["--ro-bind", ws_path, ws_path])
            else:
                argv.extend(["--bind", ws_path, ws_path])

        # Scratch directory mount (writable for private scratch work)
        if spec.filesystem.scratch_dir:
            scratch_path = str(spec.filesystem.scratch_dir.resolve())
            argv.extend(["--bind", scratch_path, scratch_path])

        # Output directory mount (writable for generated artifact staging)
        if spec.filesystem.output_dir:
            output_path = str(spec.filesystem.output_dir.resolve())
            argv.extend(["--bind", output_path, output_path])

        # 5. Additional explicit mounts
        for mount in spec.filesystem.mounts:
            src_str = str(mount.source.resolve())
            tgt_str = str(mount.target)
            if mount.mode == SandboxMountMode.READ_ONLY or mount.read_only:
                argv.extend(["--ro-bind", src_str, tgt_str])
            else:
                argv.extend(["--bind", src_str, tgt_str])

        # 6. Working directory
        cwd_path = str((spec.cwd or spec.filesystem.workspace_dir).resolve())
        argv.extend(["--chdir", cwd_path])

        # 7. Environment variable allowlist (Default-Deny)
        safe_env = {
            "PATH": os.environ.get(
                "PATH",
                f"{venv_path}/bin:/usr/local/bin:/usr/bin:/bin"
                if venv_path
                else "/usr/local/bin:/usr/bin:/bin",
            ),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TMPDIR": "/tmp",
            "HOME": "/tmp/home",
            "XDG_RUNTIME_DIR": "/tmp/run",
        }
        if venv_path:
            safe_env["VIRTUAL_ENV"] = venv_path

        # Add explicit spec allowlist
        safe_env.update(spec.env_allowlist)

        # Inject authorized secrets
        safe_env.update(resolved_secrets)

        for k, v in safe_env.items():
            argv.extend(["--setenv", k, v])

        # 8. Command
        if script_file_in_workspace:
            argv.extend([sys.executable, script_file_in_workspace])
        elif spec.command:
            argv.extend(spec.command)
        elif spec.script:
            argv.extend([sys.executable, "-c", spec.script])

        return argv

    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        if not self.is_available():
            raise SandboxUnavailableError(
                "Linux Bubblewrap backend is unavailable or lacks unprivileged namespace support."
            )

        start_time = time.time()
        script_file: Optional[Path] = None

        # Check if cgroup v2 resource limits are requested
        cgroup_required = (
            spec.resource_policy.max_memory_bytes is not None
            or spec.resource_policy.cpu_quota_percent is not None
            or spec.resource_policy.max_processes is not None
        )

        if cgroup_required and not self.is_cgroup_available():
            raise ResourceIsolationUnavailableError(
                "Kernel cgroup v2 resource isolation via systemd-run is unavailable on this host. "
                "Execution rejected fail-closed to enforce configured resource quotas (R2.9)."
            )

        # Pre-execution cancellation check
        if spec.cancellation_token and spec.cancellation_token.is_cancelled:
            return SandboxResult(
                execution_id=execution_id,
                exit_code=-1,
                stdout="",
                stderr="Execution cancelled before start.",
                status=SandboxStatus.CANCELLED,
                cancelled=True,
                terminal_reason=SandboxTerminalReason.USER_CANCELLED,
                duration_seconds=time.time() - start_time,
            )

        try:
            # If script provided as text, write to temporary file outside sandbox before starting
            script_name: Optional[str] = None
            if spec.script and not spec.command:
                # Prefer scratch_dir or output_dir if available, else workspace_dir
                target_dir = (
                    spec.filesystem.scratch_dir
                    or spec.filesystem.output_dir
                    or spec.filesystem.workspace_dir
                )
                target_dir.mkdir(parents=True, exist_ok=True)
                script_file = target_dir / f"._sbx_script_{execution_id}.py"
                script_file.write_text(spec.script, encoding="utf-8")
                script_name = str(script_file)

            bwrap_argv = self._build_bwrap_argv(
                spec, resolved_secrets, script_file_in_workspace=script_name
            )

            # Assemble full command including systemd-run cgroup scope if needed
            full_argv: List[str]
            if cgroup_required:
                cgroup_prefix = ["systemd-run", "--user", "--scope", "-q"]
                if spec.resource_policy.max_memory_bytes is not None:
                    cgroup_prefix.extend(
                        [
                            "-p",
                            f"MemoryMax={int(spec.resource_policy.max_memory_bytes)}",
                            "-p",
                            "MemorySwapMax=0",
                        ]
                    )
                if spec.resource_policy.cpu_quota_percent is not None:
                    cgroup_prefix.extend(
                        ["-p", f"CPUQuota={int(spec.resource_policy.cpu_quota_percent)}%"]
                    )
                if spec.resource_policy.max_processes is not None:
                    cgroup_prefix.extend(
                        ["-p", f"TasksMax={int(spec.resource_policy.max_processes)}"]
                    )
                cgroup_prefix.append("--")
                full_argv = cgroup_prefix + bwrap_argv
            else:
                full_argv = bwrap_argv

            # Prepare preexec_fn for RLIMIT_CPU if requested
            preexec_fn = None
            cpu_seconds = spec.resource_policy.max_cpu_time_seconds
            if cpu_seconds is not None:

                def _set_cpu_limit():
                    try:
                        import resource

                        sec = max(1, int(cpu_seconds))
                        resource.setrlimit(resource.RLIMIT_CPU, (sec, sec + 1))
                    except Exception as ex:
                        logger.debug(f"Failed to set RLIMIT_CPU in child: {ex}")

                preexec_fn = _set_cpu_limit

            proc = subprocess.Popen(
                full_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # Process group isolation for robust tree cleanup
                preexec_fn=preexec_fn,
                close_fds=True,
            )

            # Output buffers and bounded reader threads (R2.9 backpressure)
            stdout_chunks: List[bytes] = []
            stderr_chunks: List[bytes] = []
            stdout_truncated = [False]
            stderr_truncated = [False]
            output_limit_event = threading.Event()

            t_stdout = threading.Thread(
                target=_read_stream_bounded,
                args=(
                    proc.stdout,
                    spec.resource_policy.max_stdout_bytes,
                    output_limit_event,
                    stdout_chunks,
                    stdout_truncated,
                ),
                daemon=True,
            )
            t_stderr = threading.Thread(
                target=_read_stream_bounded,
                args=(
                    proc.stderr,
                    spec.resource_policy.max_stderr_bytes,
                    output_limit_event,
                    stderr_chunks,
                    stderr_truncated,
                ),
                daemon=True,
            )
            t_stdout.start()
            t_stderr.start()

            # Main execution monitoring loop
            timeout_limit = spec.resource_policy.max_wall_time_seconds or spec.timeout_seconds
            deadline = time.time() + timeout_limit
            poll_interval = 0.02
            timed_out = False
            cancelled = False
            output_limit_breached = False

            while proc.poll() is None:
                if output_limit_event.is_set():
                    output_limit_breached = True
                    _kill_process_group(proc)
                    break

                if spec.cancellation_token and spec.cancellation_token.is_cancelled:
                    cancelled = True
                    _kill_process_group(proc)
                    break

                if time.time() >= deadline:
                    timed_out = True
                    _kill_process_group(proc)
                    break

                time.sleep(poll_interval)

            # Ensure process group has terminated
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                proc.wait()

            t_stdout.join(timeout=1.0)
            t_stderr.join(timeout=1.0)

            duration = time.time() - start_time
            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            is_truncated = stdout_truncated[0] or stderr_truncated[0]

            # Determine canonical status and terminal reason
            status = SandboxStatus.COMPLETED
            terminal_reason = SandboxTerminalReason.NORMAL
            exit_code = proc.returncode if proc.returncode is not None else -1

            if output_limit_breached:
                status = SandboxStatus.FAILED
                terminal_reason = SandboxTerminalReason.OUTPUT_LIMIT
            elif timed_out:
                status = SandboxStatus.TIMED_OUT
                terminal_reason = SandboxTerminalReason.WALL_TIME_LIMIT
            elif cancelled:
                status = SandboxStatus.CANCELLED
                terminal_reason = SandboxTerminalReason.USER_CANCELLED
            elif exit_code != 0:
                status = SandboxStatus.FAILED
                # Map exit codes to precise resource limits
                if exit_code in (-9, 137) or "MemoryError" in stderr_str:
                    # Kernel OOM killer via cgroup memory.max sends SIGKILL, or malloc failed under memory limit
                    if spec.resource_policy.max_memory_bytes is not None:
                        terminal_reason = SandboxTerminalReason.MEMORY_LIMIT
                    else:
                        terminal_reason = SandboxTerminalReason.BACKEND_ERROR
                elif exit_code in (-24, 152):
                    # Kernel SIGXCPU via RLIMIT_CPU
                    terminal_reason = SandboxTerminalReason.CPU_LIMIT
                elif any(
                    msg in stderr_str
                    for msg in (
                        "can't start new thread",
                        "BlockingIOError",
                        "Resource temporarily unavailable",
                    )
                ):
                    if spec.resource_policy.max_processes is not None:
                        terminal_reason = SandboxTerminalReason.PROCESS_LIMIT
                    else:
                        terminal_reason = SandboxTerminalReason.BACKEND_ERROR
                else:
                    terminal_reason = SandboxTerminalReason.BACKEND_ERROR

            resource_usage = {
                "wall_time_seconds": round(duration, 3),
                "stdout_bytes": len(stdout_bytes),
                "stderr_bytes": len(stderr_bytes),
                "exit_code": exit_code,
            }

            return SandboxResult(
                execution_id=execution_id,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                status=status,
                timed_out=timed_out,
                cancelled=cancelled,
                terminal_reason=terminal_reason,
                output_truncated=is_truncated,
                duration_seconds=duration,
                resource_usage=resource_usage,
            )

        finally:
            if script_file and script_file.exists():
                try:
                    script_file.unlink()
                except Exception:
                    pass


class DarwinSandboxBackend(SandboxBackend):
    """macOS platform sandbox stub.

    Per CTO directive: Fail closed until native macOS sandbox container is implemented.
    """

    name = "darwin_stub"

    def is_available(self) -> bool:
        return False

    def is_cgroup_available(self) -> bool:
        return False

    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        raise SandboxUnavailableError(
            "macOS secure container sandbox is not available on this platform. "
            "Host fallback is rejected fail-closed (R2.8)."
        )


class WindowsSandboxBackend(SandboxBackend):
    """Windows platform sandbox stub.

    Per CTO directive: Fail closed until Windows container / AppContainer backend is implemented.
    """

    name = "windows_stub"

    def is_available(self) -> bool:
        return False

    def is_cgroup_available(self) -> bool:
        return False

    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        raise SandboxUnavailableError(
            "Windows secure container sandbox is not available on this platform. "
            "Host fallback is rejected fail-closed (R2.8)."
        )


class NullSandboxBackend(SandboxBackend):
    """Explicitly unavailable sandbox backend for testing fail-closed handling."""

    name = "null_unavailable"

    def is_available(self) -> bool:
        return False

    def is_cgroup_available(self) -> bool:
        return False

    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        raise SandboxUnavailableError(
            "No secure sandbox backend configured. Host fallback is rejected fail-closed (R2.8)."
        )
