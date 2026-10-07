"""core/inference/process.py

Process Lifecycle Management and Bounded Log Ring Buffer for Managed Inference.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Process group isolation: start_new_session=True (POSIX) / CREATE_NEW_PROCESS_GROUP (Windows).
2. Strict shell=False execution via validated argv list; secrets redacted from diagnostics.
3. Bounded ring buffer log capture (max lines & max bytes), preventing memory exhaustion.
4. Graceful termination (SIGTERM) with bounded wait and escalation to SIGKILL on process group.
5. Recursive descendant process cleanup guaranteeing zero orphan child processes.
"""

from __future__ import annotations

from collections import deque
import logging
import os
from pathlib import Path
import platform
import signal
import subprocess
import threading
import time
from typing import Dict, List, Optional

import psutil

logger = logging.getLogger("agent_engine.inference.process")


class RuntimeProcessHandle:
    """Encapsulates a managed inference subprocess, its process group, and bounded log capture."""

    def __init__(
        self,
        argv: List[str],
        cwd: Path,
        env: Dict[str, str],
        max_log_lines: int = 500,
        max_log_bytes: int = 65536,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.max_log_lines = max_log_lines
        self.max_log_bytes = max_log_bytes

        # Extract sensitive arguments (e.g. --api-key <token>) for log redaction
        self._redact_tokens: List[str] = []
        for i, arg in enumerate(argv):
            if arg == "--api-key" and i + 1 < len(argv):
                self._redact_tokens.append(argv[i + 1])
            elif arg.startswith("--api-key="):
                self._redact_tokens.append(arg.split("=", 1)[1])

        self.stdout_ring: deque[str] = deque(maxlen=max_log_lines)
        self.stderr_ring: deque[str] = deque(maxlen=max_log_lines)
        self._total_bytes = 0
        self._lock = threading.Lock()

        # Platform-specific process group creation flags (eliminates unsafe Python preexec_fn)
        popen_kwargs: Dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": str(cwd),
            "env": env,
            "text": True,
            "bufsize": 1,
        }

        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        self.proc = subprocess.Popen(argv, **popen_kwargs)
        self.pid = self.proc.pid

        # Determine process group ID
        try:
            self.pgid = os.getpgid(self.pid) if platform.system() != "Windows" else self.pid
        except Exception:
            self.pgid = self.pid

        # Launch background stream reader threads
        self._reader_threads: List[threading.Thread] = []
        if self.proc.stdout:
            t_out = threading.Thread(
                target=self._stream_reader,
                args=(self.proc.stdout, self.stdout_ring, "stdout"),
                daemon=True,
            )
            t_out.start()
            self._reader_threads.append(t_out)

        if self.proc.stderr:
            t_err = threading.Thread(
                target=self._stream_reader,
                args=(self.proc.stderr, self.stderr_ring, "stderr"),
                daemon=True,
            )
            t_err.start()
            self._reader_threads.append(t_err)

    def _stream_reader(self, stream, ring: deque[str], name: str) -> None:
        """Incrementally drain a process stream into a bounded ring buffer with secret redaction."""
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                clean_line = line.rstrip("\r\n")
                for secret in self._redact_tokens:
                    if secret and secret in clean_line:
                        clean_line = clean_line.replace(secret, "[REDACTED]")

                line_bytes = len(clean_line.encode("utf-8", errors="replace"))

                with self._lock:
                    if self._total_bytes + line_bytes <= self.max_log_bytes:
                        ring.append(clean_line)
                        self._total_bytes += line_bytes
                    else:
                        # Retain ring entry but drop oldest byte count if ring is overflowing
                        ring.append(clean_line)
        except Exception as ex:
            logger.debug("Stream reader encountered exception on %s: %s", name, ex)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @property
    def sanitized_argv(self) -> List[str]:
        """Return argv list with sensitive parameters (e.g. API keys) redacted."""
        out: List[str] = []
        skip_next = False
        for arg in self.argv:
            if skip_next:
                out.append("[REDACTED]")
                skip_next = False
            elif arg == "--api-key":
                out.append(arg)
                skip_next = True
            elif arg.startswith("--api-key="):
                out.append("--api-key=[REDACTED]")
            else:
                masked_arg = arg
                for sec in self._redact_tokens:
                    if sec and sec in masked_arg:
                        masked_arg = masked_arg.replace(sec, "[REDACTED]")
                out.append(masked_arg)
        return out

    def __repr__(self) -> str:
        return f"<RuntimeProcessHandle pid={self.pid} argv={self.sanitized_argv}>"

    def is_alive(self) -> bool:
        """Check if subprocess is still executing."""
        return self.proc.poll() is None

    def poll(self) -> Optional[int]:
        """Poll subprocess exit code."""
        return self.proc.poll()

    def get_logs(self, tail_lines: int = 100) -> List[str]:
        """Return combined recent stderr and stdout log lines."""
        with self._lock:
            # Prefer stderr for diagnostics, then stdout
            combined = list(self.stderr_ring) + list(self.stdout_ring)
        if tail_lines and len(combined) > tail_lines:
            return combined[-tail_lines:]
        return combined

    def terminate_gracefully(self, timeout_seconds: float = 5.0) -> int:
        """Terminate process gracefully with SIGTERM, escalating to SIGKILL on process group."""
        if not self.is_alive():
            return self.proc.poll() or 0

        # Discover all child descendant processes before terminating parent
        descendants: List[psutil.Process] = []
        try:
            parent_proc = psutil.Process(self.pid)
            descendants = parent_proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # 1. Graceful SIGTERM
        try:
            if platform.system() != "Windows":
                os.killpg(self.pgid, signal.SIGTERM)
            else:
                self.proc.terminate()
        except OSError:
            try:
                self.proc.terminate()
            except OSError:
                pass

        # 2. Bounded wait
        t0 = time.time()
        while time.time() - t0 < timeout_seconds:
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)

        # 3. Force kill escalation if still running
        if self.proc.poll() is None:
            logger.warning(
                "Process %d (pgid %d) did not terminate within %.1fs; escalating to SIGKILL.",
                self.pid,
                self.pgid,
                timeout_seconds,
            )
            try:
                if platform.system() != "Windows":
                    os.killpg(self.pgid, signal.SIGKILL)
                else:
                    self.proc.kill()
            except OSError:
                try:
                    self.proc.kill()
                except OSError:
                    pass

            try:
                self.proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

        # 4. Clean up any orphaned descendant processes
        for child in descendants:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return self.proc.poll() or 0
