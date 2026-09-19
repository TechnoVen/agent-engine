"""Canonical Cancellation Subsystem (Task R1.9).

Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
References: docs/EXECUTION_MODEL.md, docs/DATA_MODEL.md, docs/ROADMAP.md
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Callable, List, Optional

logger = logging.getLogger("agent_engine.execution.cancellation")


class CancellationReason(str, Enum):
    """Canonical reasons for execution cancellation."""

    USER_REQUEST = "user_request"
    CLIENT_DISCONNECT = "client_disconnect"
    TIMEOUT = "timeout"
    POLICY = "policy"
    SYSTEM_SHUTDOWN = "system_shutdown"
    PARENT_EXECUTION = "parent_execution"


class ProviderCancellationMode(str, Enum):
    """Classification of cancellation capability per provider/runtime."""

    NATIVE = "native"
    COOPERATIVE_ASYNC = "cooperative_async"
    CONNECTION_CLOSE = "connection_close"
    SUBPROCESS_TERMINATION = "subprocess_termination"
    UNSUPPORTED = "unsupported"


def get_provider_cancellation_mode(provider: str) -> ProviderCancellationMode:
    """Classify cancellation support for a given provider."""
    p = (provider or "").lower()
    if p in ("local", "deterministic", "deterministic_code", "cache", "code"):
        return ProviderCancellationMode.COOPERATIVE_ASYNC
    elif p in ("anthropic", "openai", "gemini", "deepseek", "groq", "ollama", "llamacpp"):
        return ProviderCancellationMode.CONNECTION_CLOSE
    elif p in ("claude_code", "codex", "goose", "openclaw"):
        return ProviderCancellationMode.SUBPROCESS_TERMINATION
    return ProviderCancellationMode.COOPERATIVE_ASYNC


class ExecutionCancelledError(Exception):
    """Raised when an execution phase detects cancellation."""

    def __init__(
        self,
        message: str = "Execution was cancelled",
        execution_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.execution_id = execution_id
        self.reason = reason


class CancellationToken:
    """Execution-scoped, idempotent, thread-safe cancellation primitive."""

    def __init__(self, execution_id: str, process_kill_timeout: float = 1.5):
        self.execution_id = execution_id
        self.process_kill_timeout = process_kill_timeout
        self._is_cancelled = False
        self._reason: Optional[str] = None
        self._actor: Optional[str] = None
        self._cancelled_at: Optional[str] = None
        self._event = asyncio.Event()
        self._callbacks: List[Callable[[], Any]] = []
        self._registered_processes: List[asyncio.subprocess.Process] = []

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._is_cancelled

    def is_set(self) -> bool:
        """Compatibility alias matching asyncio.Event / threading.Event."""
        return self._is_cancelled

    @property
    def reason(self) -> Optional[str]:
        """The canonical reason cancellation was requested."""
        return self._reason

    @property
    def actor(self) -> Optional[str]:
        """The initiator of cancellation (e.g. 'user', 'client', 'system')."""
        return self._actor

    @property
    def cancelled_at(self) -> Optional[str]:
        """ISO 8601 timestamp when cancellation occurred."""
        return self._cancelled_at

    def cancel(
        self,
        reason: str | CancellationReason = CancellationReason.USER_REQUEST,
        actor: Optional[str] = "user",
    ) -> bool:
        """Idempotently trigger cancellation.

        Returns True on the first call that transitions state to cancelled,
        and False on subsequent calls.
        """
        if self._is_cancelled:
            return False

        self._is_cancelled = True
        self._reason = reason.value if isinstance(reason, CancellationReason) else str(reason)
        self._actor = actor or "user"
        self._cancelled_at = datetime.now(timezone.utc).isoformat()
        self._event.set()

        # Terminate any registered subprocesses to prevent orphan processes
        # Cross-platform abstraction: graceful termination -> bounded wait -> force termination
        for proc in self._registered_processes:
            try:
                if proc.returncode is None:
                    proc.terminate()
                    # Schedule bounded force-termination escalation in background if still running
                    asyncio.create_task(
                        self._ensure_process_terminated(proc, timeout=self.process_kill_timeout)
                    )
            except Exception as e:
                logger.warning("Error terminating process %s: %s", getattr(proc, "pid", "?"), e)

        # Trigger registered callbacks
        for cb in self._callbacks:
            try:
                res = cb()
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.warning("Error in cancellation callback: %s", e)

        return True

    async def _ensure_process_terminated(
        self, proc: asyncio.subprocess.Process, timeout: Optional[float] = None
    ) -> None:
        """Cross-platform termination contract:

        1. Request graceful termination (terminate() / SIGTERM / TerminateProcess).
        2. Bounded wait for process completion.
        3. Escalate to forced termination (kill() / SIGKILL / TerminateProcess) if unyielding.
        """
        effective_timeout = self.process_kill_timeout if timeout is None else timeout
        try:
            await asyncio.wait_for(proc.wait(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            try:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
            except Exception as ex:
                logger.debug("Error force-killing process: %s", ex)
        except ProcessLookupError:
            pass
        except Exception as ex:
            logger.debug("Error during process termination wait: %s", ex)

    # Backward-compatible alias
    _ensure_process_killed = _ensure_process_terminated

    def register_process(self, proc: asyncio.subprocess.Process) -> None:
        """Register a subprocess for graceful termination upon cancellation."""
        if self._is_cancelled:
            try:
                if proc.returncode is None:
                    proc.terminate()
                    asyncio.create_task(
                        self._ensure_process_terminated(proc, timeout=self.process_kill_timeout)
                    )
            except Exception:
                pass
        else:
            self._registered_processes.append(proc)

    def add_callback(self, cb: Callable[[], Any]) -> None:
        """Register a callback invoked when cancellation triggers."""
        if self._is_cancelled:
            try:
                res = cb()
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.warning("Error executing immediate cancellation callback: %s", e)
        else:
            self._callbacks.append(cb)

    async def wait(self) -> None:
        """Await cancellation signal."""
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        """Raise ExecutionCancelledError if cancellation has been triggered."""
        if self._is_cancelled:
            raise ExecutionCancelledError(
                message=f"Execution {self.execution_id} was cancelled: {self._reason}",
                execution_id=self.execution_id,
                reason=self._reason,
            )
