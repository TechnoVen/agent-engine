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
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from core.sandbox.models import (
    ResourceIsolationUnavailableError,
    SandboxMountMode,
    SandboxResourcePolicy,
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
    """Read a binary stream up to max_bytes, signaling cancel_event and draining on breach (Section 8)."""
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
                # Continuous drain without storing so child process does not block on full pipe (Section 8)
                while True:
                    discard = stream.read(65536)
                    if not discard:
                        break
                break
            chunks.append(chunk)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


@dataclass
class ResourceControlHandle:
    """Canonical handle for inspecting and managing a sandbox cgroup v2 resource scope (R2.9).

    Tracks kernel counters (memory.events, pids.events, cpu.stat) and manages factual evidence
    prior to scope destruction (CTO Review Sections 1, 2, 5, 15).
    """

    unit_name: str
    policy: SandboxResourcePolicy
    cgroup_path: Optional[Path] = None
    latest_events: Dict[str, Any] = field(default_factory=dict)
    _discovered: bool = False
    cgroup_enabled: bool = False

    def discover_cgroup_path(self, proc_pid: int) -> Optional[Path]:
        """Resolve the cgroup v2 directory path for the given process PID."""
        if self.cgroup_path and self.cgroup_path.exists():
            return self.cgroup_path

        proc_cgroup = Path(f"/proc/{proc_pid}/cgroup")
        if not proc_cgroup.exists():
            return None

        unit_base = self.unit_name.removesuffix(".scope")
        try:
            with open(proc_cgroup, "r", encoding="utf-8") as f:
                for line in f:
                    # In cgroup v2 unified hierarchy: "0::<cgroup_path>"
                    parts = line.strip().split(":", 2)
                    if len(parts) == 3 and parts[0] == "0":
                        rel_path = parts[2].lstrip("/")
                        # Invariant: Must belong to our specific transient scope unit, NEVER the parent cgroup!
                        if unit_base in rel_path:
                            candidate = Path("/sys/fs/cgroup") / rel_path
                            if candidate.exists():
                                self.cgroup_path = candidate
                                self._discovered = True
                                return self.cgroup_path
        except Exception as e:
            logger.debug(f"Failed to read cgroup path for PID {proc_pid}: {e}")

        # Fallback to direct scope name resolution in user.slice
        try:
            user_id = os.getuid()
            for candidate_dir in (
                Path(
                    f"/sys/fs/cgroup/user.slice/user-{user_id}.slice/user@{user_id}.service/app.slice/{self.unit_name}"
                ),
                Path(
                    f"/sys/fs/cgroup/user.slice/user-{user_id}.slice/user@{user_id}.service/app.slice/{unit_base}.scope"
                ),
            ):
                if candidate_dir.exists():
                    self.cgroup_path = candidate_dir
                    self._discovered = True
                    return self.cgroup_path
        except Exception:
            pass

        return None

    def sample_evidence(self) -> Dict[str, Any]:
        """Sample current kernel counters from the cgroup hierarchy before destruction (Section 2)."""
        if not self._discovered or not self.cgroup_path or not self.cgroup_path.exists():
            return self.latest_events

        evidence = dict(self.latest_events)

        # 1. memory.events (oom, oom_kill, max)
        mem_events_path = self.cgroup_path / "memory.events"
        if mem_events_path.exists():
            try:
                with open(mem_events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            evidence[f"memory_events_{parts[0]}"] = int(parts[1])
            except Exception:
                pass

        # 2. memory.current & memory.peak
        for stat_name in ("current", "peak"):
            m_path = self.cgroup_path / f"memory.{stat_name}"
            if m_path.exists():
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        val = int(f.read().strip())
                        evidence[f"memory_{stat_name}_bytes"] = val
                        if stat_name == "current":
                            prev_peak = evidence.get("memory_peak_bytes", 0)
                            evidence["memory_peak_bytes"] = max(prev_peak, val)
                except Exception:
                    pass

        # 3. pids.events (max)
        pids_events_path = self.cgroup_path / "pids.events"
        if pids_events_path.exists():
            try:
                with open(pids_events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            evidence[f"pids_events_{parts[0]}"] = int(parts[1])
            except Exception:
                pass

        # 4. pids.current
        pids_curr_path = self.cgroup_path / "pids.current"
        if pids_curr_path.exists():
            try:
                with open(pids_curr_path, "r", encoding="utf-8") as f:
                    evidence["pids_current"] = int(f.read().strip())
            except Exception:
                pass

        # 5. cpu.stat (usage_usec, nr_throttled, throttled_usec)
        cpu_stat_path = self.cgroup_path / "cpu.stat"
        if cpu_stat_path.exists():
            try:
                with open(cpu_stat_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 2:
                            evidence[f"cpu_stat_{parts[0]}"] = int(parts[1])
                    if "cpu_stat_usage_usec" in evidence:
                        evidence["cpu_time_seconds"] = round(
                            evidence["cpu_stat_usage_usec"] / 1_000_000, 4
                        )
            except Exception:
                pass

        self.latest_events = evidence
        return evidence

    def check_cumulative_cpu_exceeded(self) -> bool:
        """Check if cumulative sandbox CPU usage has exceeded max_cpu_time_seconds (Section 1)."""
        if not self._discovered or self.policy.max_cpu_time_seconds is None:
            return False
        cpu_sec = self.latest_events.get("cpu_time_seconds", 0.0)
        return cpu_sec >= self.policy.max_cpu_time_seconds

    def has_oom_occurred(self) -> bool:
        """Factual check whether kernel cgroup memory controller triggered OOM (Section 2)."""
        oom_kill = self.latest_events.get("memory_events_oom_kill", 0)
        oom = self.latest_events.get("memory_events_oom", 0)
        return oom_kill > 0 or oom > 0

    def has_pids_max_occurred(self) -> bool:
        """Factual check whether kernel cgroup pids controller blocked tasks (Section 2)."""
        pids_max = self.latest_events.get("pids_events_max", 0)
        return pids_max > 0

    def read_final_evidence(self) -> Dict[str, Any]:
        """Capture final kernel evidence before cgroup destruction (Section 19)."""
        self.sample_evidence()

        # Query systemd unit properties for durable post-termination evidence
        if self.cgroup_enabled and self.unit_name:
            try:
                out = subprocess.check_output(
                    [
                        "systemctl",
                        "--user",
                        "show",
                        self.unit_name,
                        "-p",
                        "LoadState",
                        "-p",
                        "Result",
                        "-p",
                        "OOMKills",
                        "-p",
                        "MemoryPeak",
                        "-p",
                        "CPUUsageNSec",
                    ],
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                ).decode("utf-8", errors="replace")

                lines = dict(item.split("=", 1) for item in out.strip().splitlines() if "=" in item)

                if lines.get("LoadState") == "loaded":
                    if lines.get("Result") == "oom-kill":
                        self.latest_events["memory_events_oom_kill"] = max(
                            self.latest_events.get("memory_events_oom_kill", 0), 1
                        )
                        self.latest_events["memory_events_oom"] = max(
                            self.latest_events.get("memory_events_oom", 0), 1
                        )

                    oom_kills = lines.get("OOMKills", "0")
                    if (
                        oom_kills
                        and oom_kills.isdigit()
                        and 0 < int(oom_kills) < 18446744073709551615
                    ):
                        self.latest_events["memory_events_oom_kill"] = max(
                            self.latest_events.get("memory_events_oom_kill", 0), int(oom_kills)
                        )
                        self.latest_events["memory_events_oom"] = max(
                            self.latest_events.get("memory_events_oom", 0), 1
                        )

                    peak = lines.get("MemoryPeak")
                    if peak and peak.isdigit() and int(peak) < 18446744073709551615:
                        self.latest_events["memory_peak_bytes"] = max(
                            self.latest_events.get("memory_peak_bytes", 0), int(peak)
                        )

                    cpu_nsec = lines.get("CPUUsageNSec")
                    if cpu_nsec and cpu_nsec.isdigit() and int(cpu_nsec) < 18446744073709551615:
                        usec = int(cpu_nsec) // 1000
                        self.latest_events["cpu_stat_usage_usec"] = max(
                            self.latest_events.get("cpu_stat_usage_usec", 0), usec
                        )
                        self.latest_events["cpu_time_seconds"] = round(
                            self.latest_events["cpu_stat_usage_usec"] / 1_000_000, 4
                        )

                    subprocess.run(
                        ["systemctl", "--user", "reset-failed", self.unit_name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0,
                    )
            except Exception as e:
                logger.debug(f"Failed to query systemd unit {self.unit_name}: {e}")

        return self.latest_events

    def get_audit_safe_metrics(self) -> Dict[str, Any]:
        """Return audit-safe sanitized resource usage metrics without host paths (Section 15)."""
        return {
            "cpu_time_seconds": self.latest_events.get("cpu_time_seconds", 0.0),
            "peak_memory_bytes": self.latest_events.get("memory_peak_bytes", 0),
            "pids_max_events": self.latest_events.get("pids_events_max", 0),
            "oom_events": self.latest_events.get("memory_events_oom", 0),
            "oom_kill_events": self.latest_events.get("memory_events_oom_kill", 0),
            "nr_throttled": self.latest_events.get("cpu_stat_nr_throttled", 0),
            "throttled_usec": self.latest_events.get("cpu_stat_throttled_usec", 0),
        }


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
        self._controller_capabilities: Optional[Dict[str, bool]] = None

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

    def probe_controllers(self, force_refresh: bool = False) -> Dict[str, bool]:
        """Probe actual required cgroup v2 controllers and capabilities (CTO Review Section 3).

        Probes:
        - user_scope: transient unit creation via systemd-run --user --scope
        - memory: MemoryMax controller property application
        - swap: MemorySwapMax property application
        - cpu: CPUQuota controller property application
        - pids: TasksMax controller property application
        """
        if self._controller_capabilities is not None and not force_refresh:
            return self._controller_capabilities

        if not sys.platform.startswith("linux"):
            self._controller_capabilities = {
                "user_scope": False,
                "memory": False,
                "swap": False,
                "cpu": False,
                "pids": False,
            }
            return self._controller_capabilities

        caps: Dict[str, bool] = {
            "user_scope": False,
            "memory": False,
            "swap": False,
            "cpu": False,
            "pids": False,
        }

        # 1. Probe user scope transient unit creation
        try:
            res = subprocess.run(
                ["systemd-run", "--user", "--scope", "-q", "--", "/usr/bin/true"],
                capture_output=True,
                timeout=3.0,
            )
            caps["user_scope"] = res.returncode == 0
        except Exception:
            pass

        if not caps["user_scope"]:
            self._controller_capabilities = caps
            return caps

        # 2. Probe memory controller
        try:
            res = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "-p",
                    "MemoryMax=1G",
                    "-q",
                    "--",
                    "/usr/bin/true",
                ],
                capture_output=True,
                timeout=3.0,
            )
            caps["memory"] = res.returncode == 0
        except Exception:
            pass

        # 3. Probe swap controller
        try:
            res = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "-p",
                    "MemorySwapMax=0",
                    "-q",
                    "--",
                    "/usr/bin/true",
                ],
                capture_output=True,
                timeout=3.0,
            )
            caps["swap"] = res.returncode == 0
        except Exception:
            pass

        # 4. Probe cpu controller
        try:
            res = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "-p",
                    "CPUQuota=100%",
                    "-q",
                    "--",
                    "/usr/bin/true",
                ],
                capture_output=True,
                timeout=3.0,
            )
            caps["cpu"] = res.returncode == 0
        except Exception:
            pass

        # 5. Probe pids controller
        try:
            res = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "-p",
                    "TasksMax=100",
                    "-q",
                    "--",
                    "/usr/bin/true",
                ],
                capture_output=True,
                timeout=3.0,
            )
            caps["pids"] = res.returncode == 0
        except Exception:
            pass

        self._controller_capabilities = caps
        return caps

    def is_cgroup_available(self) -> bool:
        """Check whether systemd user scope cgroup v2 is operational."""
        caps = self.probe_controllers()
        return caps.get("user_scope", False)

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

        # Check required controllers against actual capabilities (Section 3: No silent degradation)
        caps = self.probe_controllers()
        cgroup_required = (
            spec.resource_policy.max_memory_bytes is not None
            or spec.resource_policy.cpu_quota_percent is not None
            or spec.resource_policy.max_processes is not None
            or spec.resource_policy.max_cpu_time_seconds is not None
        )

        if cgroup_required:
            if not self.is_cgroup_available() or not caps.get("user_scope", False):
                raise ResourceIsolationUnavailableError(
                    "Systemd user scope cgroup v2 is unavailable on this host. "
                    "Execution rejected fail-closed to enforce configured resource quotas (R2.9)."
                )
            if spec.resource_policy.max_memory_bytes is not None:
                if not caps.get("memory", False):
                    raise ResourceIsolationUnavailableError(
                        "Required cgroup v2 controller 'memory' is unavailable on this host. "
                        "Execution rejected fail-closed (R2.9 Section 3)."
                    )
                if spec.resource_policy.require_swap_disabled and not caps.get("swap", False):
                    raise ResourceIsolationUnavailableError(
                        "Required swap isolation (MemorySwapMax=0) is unavailable on this host. "
                        "Execution rejected fail-closed (R2.9 Section 13)."
                    )
            if (
                spec.resource_policy.cpu_quota_percent is not None
                or spec.resource_policy.max_cpu_time_seconds is not None
            ):
                if not caps.get("cpu", False):
                    raise ResourceIsolationUnavailableError(
                        "Required cgroup v2 controller 'cpu' is unavailable on this host. "
                        "Execution rejected fail-closed (R2.9 Section 3)."
                    )
            if spec.resource_policy.max_processes is not None:
                if not caps.get("pids", False):
                    raise ResourceIsolationUnavailableError(
                        "Required cgroup v2 controller 'pids' is unavailable on this host. "
                        "Execution rejected fail-closed (R2.9 Section 3)."
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

            # Assemble full command including systemd-run cgroup scope if needed (Section 5)
            sanitized_id = "".join(c if c.isalnum() else "_" for c in execution_id)
            unit_name = f"ae-sbx-{sanitized_id}.scope"
            full_argv: List[str]
            if cgroup_required:
                cgroup_prefix = ["systemd-run", "--user", "--scope", "-u", unit_name, "-q"]
                if spec.resource_policy.max_memory_bytes is not None:
                    cgroup_prefix.extend(
                        ["-p", f"MemoryMax={int(spec.resource_policy.max_memory_bytes)}"]
                    )
                    if spec.resource_policy.require_swap_disabled and caps.get("swap", False):
                        cgroup_prefix.extend(["-p", "MemorySwapMax=0"])
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

            # Prepare preexec_fn for RLIMIT_CPU if requested (Section 1 & 7: per-process hardware trap)
            preexec_fn = None
            rlimit_cpu = spec.resource_policy.rlimit_cpu_seconds
            if rlimit_cpu is not None:

                def _set_cpu_limit():
                    try:
                        import resource

                        sec = max(1, int(rlimit_cpu))
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

            handle = ResourceControlHandle(
                unit_name=unit_name,
                policy=spec.resource_policy,
                cgroup_enabled=cgroup_required,
            )
            time.sleep(0.01)
            handle.discover_cgroup_path(proc.pid)

            # Output buffers and bounded reader threads (R2.9 backpressure, Section 8)
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
            cpu_limit_breached = False

            while proc.poll() is None:
                if not handle._discovered:
                    handle.discover_cgroup_path(proc.pid)

                # Sample cgroup evidence (Section 2)
                handle.sample_evidence()

                # Check cumulative CPU time limit (CTO Review Section 1)
                if handle.check_cumulative_cpu_exceeded():
                    cpu_limit_breached = True
                    _kill_process_group(proc)
                    break

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

            # Cleanup order (CTO Review Section 19):
            # 1. Stop/kill proc if still running
            if proc.poll() is None:
                _kill_process_group(proc)

            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                proc.wait()

            # 2. Drain/join reader threads safely
            t_stdout.join(timeout=1.0)
            t_stderr.join(timeout=1.0)

            # 3. Capture final kernel/resource evidence while cgroup exists
            handle.read_final_evidence()

            duration = time.time() - start_time
            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            is_truncated = stdout_truncated[0] or stderr_truncated[0]

            # Determine canonical status and terminal reason based on FACTUAL evidence (CTO Review Section 2)
            status = SandboxStatus.COMPLETED
            terminal_reason = SandboxTerminalReason.NORMAL
            exit_code = proc.returncode if proc.returncode is not None else -1

            if output_limit_breached or is_truncated:
                status = SandboxStatus.FAILED
                terminal_reason = SandboxTerminalReason.OUTPUT_LIMIT
            elif cpu_limit_breached:
                status = SandboxStatus.FAILED
                terminal_reason = SandboxTerminalReason.CPU_LIMIT
            elif timed_out:
                status = SandboxStatus.TIMED_OUT
                terminal_reason = SandboxTerminalReason.WALL_TIME_LIMIT
            elif cancelled:
                status = SandboxStatus.CANCELLED
                terminal_reason = SandboxTerminalReason.USER_CANCELLED
            elif exit_code != 0:
                status = SandboxStatus.FAILED
                # Factual check using kernel evidence (Section 2)
                if handle.has_oom_occurred():
                    terminal_reason = SandboxTerminalReason.MEMORY_LIMIT
                elif (
                    "MemoryError" in stderr_str
                    and spec.resource_policy.max_memory_bytes is not None
                ):
                    terminal_reason = SandboxTerminalReason.MEMORY_LIMIT
                elif handle.has_pids_max_occurred():
                    terminal_reason = SandboxTerminalReason.PROCESS_LIMIT
                elif (
                    any(
                        msg in stderr_str
                        for msg in (
                            "can't start new thread",
                            "BlockingIOError",
                            "Resource temporarily unavailable",
                        )
                    )
                    and spec.resource_policy.max_processes is not None
                ):
                    terminal_reason = SandboxTerminalReason.PROCESS_LIMIT
                elif exit_code in (-24, 152):
                    # Kernel SIGXCPU via RLIMIT_CPU
                    terminal_reason = SandboxTerminalReason.CPU_LIMIT
                elif handle.check_cumulative_cpu_exceeded():
                    terminal_reason = SandboxTerminalReason.CPU_LIMIT
                elif exit_code in (-9, 137):
                    # SIGKILL received, but NOT from OOM!
                    # Honest reporting: do not manufacture MEMORY_LIMIT from signal alone
                    terminal_reason = SandboxTerminalReason.BACKEND_ERROR
                else:
                    terminal_reason = SandboxTerminalReason.BACKEND_ERROR

            safe_metrics = handle.get_audit_safe_metrics()
            resource_usage = {
                "wall_time_seconds": round(duration, 3),
                "cpu_time_seconds": safe_metrics.get("cpu_time_seconds", round(duration, 3)),
                "peak_memory_bytes": safe_metrics.get("peak_memory_bytes", 0),
                "stdout_bytes": len(stdout_bytes),
                "stderr_bytes": len(stderr_bytes),
                "exit_code": exit_code,
                "oom_events": safe_metrics.get("oom_events", 0),
                "oom_kill_events": safe_metrics.get("oom_kill_events", 0),
                "pids_max_events": safe_metrics.get("pids_max_events", 0),
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
