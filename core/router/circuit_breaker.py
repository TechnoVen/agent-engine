import enum
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("agent_engine.router.circuit_breaker")


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    half_open_success_threshold: int = 1


class CircuitBreaker:
    """Thread-safe circuit breaker tracking LLM provider availability."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self.config = config or CircuitBreakerConfig()
        self._lock = threading.RLock()
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, int] = {}
        self._half_open_successes: dict[str, int] = {}
        self._last_failure_time: dict[str, float] = {}
        self._last_error: dict[str, str] = {}

    def get_state(self, provider: str) -> CircuitState:
        with self._lock:
            state = self._states.get(provider, CircuitState.CLOSED)
            if state == CircuitState.OPEN:
                last_fail = self._last_failure_time.get(provider, 0.0)
                if time.time() - last_fail >= self.config.recovery_timeout:
                    # Transition to HALF_OPEN to permit a trial probe
                    self._states[provider] = CircuitState.HALF_OPEN
                    self._half_open_successes[provider] = 0
                    logger.info(
                        "Circuit for provider '%s' transitioned OPEN -> HALF_OPEN (recovery timeout elapsed)",
                        provider,
                    )
                    return CircuitState.HALF_OPEN
            return state

    def can_attempt(self, provider: str) -> bool:
        """Return True if an invocation can be attempted for this provider."""
        state = self.get_state(provider)
        if state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            return True
        # Circuit is OPEN and recovery timeout has not yet elapsed
        return False

    def record_success(self, provider: str) -> None:
        """Record successful invocation. Closes circuit if in HALF_OPEN."""
        with self._lock:
            current_state = self.get_state(provider)
            if current_state == CircuitState.HALF_OPEN:
                successes = self._half_open_successes.get(provider, 0) + 1
                self._half_open_successes[provider] = successes
                if successes >= self.config.half_open_success_threshold:
                    self._states[provider] = CircuitState.CLOSED
                    self._failures[provider] = 0
                    self._last_error.pop(provider, None)
                    logger.info(
                        "Circuit for provider '%s' transitioned HALF_OPEN -> CLOSED after successful verification",
                        provider,
                    )
            elif current_state == CircuitState.CLOSED:
                self._failures[provider] = 0
                self._last_error.pop(provider, None)

    def record_failure(self, provider: str, error: Exception | str | None = None) -> None:
        """Record invocation failure. May trip circuit to OPEN."""
        err_msg = str(error) if error is not None else "Unknown error"
        with self._lock:
            current_state = self.get_state(provider)
            now = time.time()
            self._last_failure_time[provider] = now
            self._last_error[provider] = err_msg

            if current_state == CircuitState.HALF_OPEN:
                # Trial attempt failed, immediately trip back to OPEN
                self._states[provider] = CircuitState.OPEN
                logger.warning(
                    "Circuit for provider '%s' re-tripped HALF_OPEN -> OPEN on trial failure: %s",
                    provider,
                    err_msg,
                )
                return

            failures = self._failures.get(provider, 0) + 1
            self._failures[provider] = failures
            if failures >= self.config.failure_threshold:
                self._states[provider] = CircuitState.OPEN
                logger.warning(
                    "Circuit for provider '%s' TRIPPED to OPEN after %d consecutive failures. Last error: %s",
                    provider,
                    failures,
                    err_msg,
                )
            else:
                logger.debug(
                    "Provider '%s' failure recorded (%d/%d): %s",
                    provider,
                    failures,
                    self.config.failure_threshold,
                    err_msg,
                )

    def trip(self, provider: str, reason: str = "manual") -> None:
        """Manually trip a provider's circuit to OPEN."""
        with self._lock:
            self._states[provider] = CircuitState.OPEN
            self._last_failure_time[provider] = time.time()
            self._last_error[provider] = f"Tripped manually: {reason}"
            logger.warning(
                "Circuit for provider '%s' tripped manually to OPEN: %s", provider, reason
            )

    def reset(self, provider: str | None = None) -> None:
        """Reset circuit state to CLOSED."""
        with self._lock:
            if provider:
                self._states[provider] = CircuitState.CLOSED
                self._failures[provider] = 0
                self._half_open_successes[provider] = 0
                self._last_failure_time.pop(provider, None)
                self._last_error.pop(provider, None)
            else:
                self._states.clear()
                self._failures.clear()
                self._half_open_successes.clear()
                self._last_failure_time.clear()
                self._last_error.clear()

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of all provider circuit states."""
        with self._lock:
            providers = set(self._states.keys()) | set(self._failures.keys())
            status = {}
            for p in providers:
                state = self.get_state(p)
                status[p] = {
                    "state": state.value,
                    "consecutive_failures": self._failures.get(p, 0),
                    "last_failure_time": self._last_failure_time.get(p),
                    "last_error": self._last_error.get(p),
                    "can_attempt": state in (CircuitState.CLOSED, CircuitState.HALF_OPEN),
                }
            return status
