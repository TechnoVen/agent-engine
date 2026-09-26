"""core/sandbox/backend.py

Platform Backend implementations for the Sandbox Worker Runtime.
Part of Milestone R2 Task R2.8 (Sandbox worker runtime).

Design Invariants:
1. Bubblewrap (bwrap) on Linux provides genuine kernel namespace isolation (PID, mount, UTS, IPC, network).
2. Fail-closed on unsupported platforms (macOS / Windows): Never fall back to host execution.
3. Default-deny environment: Clean environment via --clearenv and explicit --setenv allowlisting.
4. Process tree lifecycle: --die-with-parent ensures child processes terminate with the parent.
5. Cooperative and force termination: Handles CancellationToken and timeout enforcement.
"""

from __future__ import annotations

import abc
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional

from core.sandbox.models import (
    SandboxResult,
    SandboxSpec,
    SandboxStatus,
    SandboxUnavailableError,
)


class SandboxBackend(abc.ABC):
    """Abstract interface for platform-specific sandbox execution backends."""

    name: str

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check whether this backend is functional and secure on the current host."""
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

    Requires unprivileged user namespaces and bwrap binary.
    """

    name = "linux_bubblewrap"

    def __init__(self, bwrap_path: Optional[str] = None):
        self._bwrap_path = bwrap_path or shutil.which("bwrap") or "/usr/bin/bwrap"
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        if not sys.platform.startswith("linux"):
            self._available = False
            return False

        if not os.path.isfile(self._bwrap_path) or not os.access(self._bwrap_path, os.X_OK):
            self._available = False
            return False

        # Probe minimal execution with user namespaces
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
                probe_cmd.extend(["--symlink", "usr/lib", "/lib64"])
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
            # Network allowed: provide basic DNS and certificate paths
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

        # 2. Tmpfs
        if spec.filesystem.allow_tmpfs:
            argv.extend(["--tmpfs", "/tmp"])

        # 3. Base system read-only mounts
        argv.extend(["--ro-bind", "/usr", "/usr"])

        # Usr-merge handling (Arch, Debian modern, Fedora)
        if os.path.islink("/lib"):
            argv.extend(["--symlink", "usr/lib", "/lib"])
        elif os.path.isdir("/lib"):
            argv.extend(["--ro-bind-try", "/lib", "/lib"])

        if os.path.islink("/lib64"):
            argv.extend(["--symlink", "usr/lib", "/lib64"])
        elif os.path.isdir("/lib64"):
            argv.extend(["--ro-bind-try", "/lib64", "/lib64"])

        if os.path.islink("/bin"):
            argv.extend(["--symlink", "usr/bin", "/bin"])
        elif os.path.isdir("/bin"):
            argv.extend(["--ro-bind-try", "/bin", "/bin"])

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

        # 4. Workspace filesystem binding (Read-Write)
        ws_path = str(spec.filesystem.workspace_dir.resolve())
        argv.extend(["--bind", ws_path, ws_path])

        # 5. Additional explicit mounts
        for mount in spec.filesystem.mounts:
            src_str = str(mount.source.resolve())
            tgt_str = str(mount.target)
            if mount.read_only:
                argv.extend(["--ro-bind", src_str, tgt_str])
            else:
                argv.extend(["--bind", src_str, tgt_str])

        # 6. Working directory
        cwd_path = str((spec.cwd or spec.filesystem.workspace_dir).resolve())
        argv.extend(["--chdir", cwd_path])

        # 7. Environment variable allowlist (Default-Deny)
        # Standard minimal runtime env
        safe_env = {
            "PATH": os.environ.get(
                "PATH",
                f"{venv_path}/bin:/usr/local/bin:/usr/bin:/bin"
                if venv_path
                else "/usr/local/bin:/usr/bin:/bin",
            ),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TMPDIR": "/tmp",
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

        try:
            # If script provided as text, write to temporary file inside the granted workspace
            script_name: Optional[str] = None
            if spec.script and not spec.command:
                script_file = spec.filesystem.workspace_dir / f"._sbx_script_{execution_id}.py"
                script_file.write_text(spec.script, encoding="utf-8")
                script_name = str(script_file)

            argv = self._build_bwrap_argv(
                spec, resolved_secrets, script_file_in_workspace=script_name
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
                    duration_seconds=time.time() - start_time,
                )

            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
            )

            # Register cancellation handler
            cancel_hook = None
            if spec.cancellation_token:

                def _on_cancel():
                    try:
                        proc.terminate()
                        time.sleep(0.1)
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass

                cancel_hook = spec.cancellation_token.register_callback(_on_cancel)

            timed_out = False
            cancelled = False
            stdout, stderr = "", ""

            try:
                stdout, stderr = proc.communicate(timeout=spec.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                stdout, stderr = proc.communicate()
            finally:
                if cancel_hook and spec.cancellation_token:
                    # In our cancellation token implementation, register_callback returns None or callable
                    pass

            duration = time.time() - start_time
            if spec.cancellation_token and spec.cancellation_token.is_cancelled:
                cancelled = True

            status = SandboxStatus.COMPLETED
            if timed_out:
                status = SandboxStatus.TIMED_OUT
            elif cancelled:
                status = SandboxStatus.CANCELLED
            elif proc.returncode != 0:
                status = SandboxStatus.FAILED

            return SandboxResult(
                execution_id=execution_id,
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout or "",
                stderr=stderr or "",
                status=status,
                timed_out=timed_out,
                cancelled=cancelled,
                duration_seconds=duration,
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

    def execute(
        self,
        spec: SandboxSpec,
        resolved_secrets: Dict[str, str],
        execution_id: str,
    ) -> SandboxResult:
        raise SandboxUnavailableError(
            "No secure sandbox backend configured. Host fallback is rejected fail-closed (R2.8)."
        )
