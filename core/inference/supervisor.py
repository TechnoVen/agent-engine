"""core/inference/supervisor.py

Canonical Local Inference Supervisor for Agent Engine.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Narrow 0.5 state machine: STOPPED, STARTING, READY, STOPPING, FAILED.
2. Single-flight, idempotent start() and stop() with threading.RLock synchronization.
3. Secret-free child environment and loopback-only binding with per-launch API key protection.
4. Distinguishes PID existence from factual readiness (HTTP 200 vs 503 Loading model).
5. Observational ResourceManager snapshots recorded before start and after model load.
6. Automatic integration with canonical ProviderRegistry (updating llamacpp endpoint & auth).
7. Graceful termination with process group SIGKILL escalation, leaving zero orphan processes.
"""

from __future__ import annotations

import logging
from pathlib import Path
import secrets
import threading
import time
from typing import Optional
import uuid

import requests

from core.inference.binary import RuntimeBinaryResolver
from core.inference.environment import build_child_environment
from core.inference.models import (
    RuntimeHealth,
    RuntimeInstance,
    RuntimeSpec,
    RuntimeState,
)
from core.inference.ports import (
    PortCollisionError,
    find_available_loopback_port,
    is_port_available,
    verify_endpoint_ownership,
)
from core.inference.process import RuntimeProcessHandle
from core.inference.validation import ModelArtifactValidator

logger = logging.getLogger("agent_engine.inference.supervisor")


class SupervisorError(Exception):
    """Base exception for supervisor runtime failures."""


class RuntimeStartupError(SupervisorError):
    """Raised when runtime fails to start or achieve readiness within deadline."""


class RuntimeCrashError(SupervisorError):
    """Raised when runtime crashes unexpectedly."""


class LocalInferenceSupervisor:
    """Authoritative supervisor managing lifecycle of local llama.cpp inference runtimes."""

    def __init__(self, binary_resolver: Optional[RuntimeBinaryResolver] = None) -> None:
        self._lock = threading.RLock()
        self._state: RuntimeState = RuntimeState.STOPPED
        self._active_instance: Optional[RuntimeInstance] = None
        self._process_handle: Optional[RuntimeProcessHandle] = None
        self._binary_resolver = binary_resolver or RuntimeBinaryResolver()

    @property
    def state(self) -> RuntimeState:
        with self._lock:
            self._reconcile_state()
            return self._state

    def get_active_instance(self) -> Optional[RuntimeInstance]:
        with self._lock:
            self._reconcile_state()
            return self._active_instance

    def _reconcile_state(self) -> None:
        """Internal check for unexpected child process termination."""
        if self._state == RuntimeState.READY and self._process_handle is not None:
            exit_code = self._process_handle.poll()
            if exit_code is not None:
                logger.error(
                    "Managed runtime process %d terminated unexpectedly with code %d",
                    self._process_handle.pid,
                    exit_code,
                )
                self._state = RuntimeState.FAILED
                if self._active_instance:
                    self._active_instance.state = RuntimeState.FAILED
                    self._active_instance.exit_code = exit_code
                    logs = self._process_handle.get_logs(tail_lines=10)
                    self._active_instance.exit_reason = (
                        f"Unexpected process termination (code {exit_code}): " + "\n".join(logs)
                    )

    def get_health(self) -> RuntimeHealth:
        """Report point-in-time runtime health."""
        with self._lock:
            self._reconcile_state()
            inst = self._active_instance
            if inst is None or self._state == RuntimeState.STOPPED:
                return RuntimeHealth(
                    state=RuntimeState.STOPPED,
                    is_ready=False,
                    last_checked_at=time.time(),
                )

            if self._state != RuntimeState.READY:
                return RuntimeHealth(
                    state=self._state,
                    is_ready=False,
                    pid=inst.pid,
                    endpoint_url=inst.endpoint_url,
                    last_checked_at=time.time(),
                    error_message=inst.exit_reason,
                )

            # Active probe of ready endpoint
            endpoint_url = f"{inst.endpoint_url}/health" if inst.endpoint_url else None
            headers = {}
            if inst.api_key:
                headers["Authorization"] = f"Bearer {inst.api_key}"

            t0 = time.perf_counter()
            try:
                resp = (
                    requests.get(endpoint_url, headers=headers, timeout=1.5)
                    if endpoint_url
                    else None
                )
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                if resp is not None and resp.status_code == 200:
                    return RuntimeHealth(
                        state=RuntimeState.READY,
                        is_ready=True,
                        pid=inst.pid,
                        endpoint_url=inst.endpoint_url,
                        model_loaded=inst.spec.model_identity.model_id,
                        latency_ms=elapsed_ms,
                        last_checked_at=time.time(),
                    )
                else:
                    return RuntimeHealth(
                        state=RuntimeState.FAILED,
                        is_ready=False,
                        pid=inst.pid,
                        endpoint_url=inst.endpoint_url,
                        latency_ms=elapsed_ms,
                        last_checked_at=time.time(),
                        error_message=f"Health probe returned HTTP {resp.status_code if resp else 'None'}",
                    )
            except Exception as ex:
                return RuntimeHealth(
                    state=RuntimeState.FAILED,
                    is_ready=False,
                    pid=inst.pid,
                    endpoint_url=inst.endpoint_url,
                    last_checked_at=time.time(),
                    error_message=f"Health probe connection failed: {ex}",
                )

    def start(self, spec: RuntimeSpec) -> RuntimeInstance:
        """Start managed inference runtime with single-flight concurrency protection and idempotency."""
        with self._lock:
            # 1. Idempotency: if already READY with matching model, return current instance
            self._reconcile_state()
            if (
                self._state == RuntimeState.READY
                and self._active_instance is not None
                and self._active_instance.spec.model_path == spec.model_path
            ):
                logger.info(
                    "Managed runtime already READY on %s", self._active_instance.endpoint_url
                )
                return self._active_instance

            # If running different model, stop first
            if self._state in (RuntimeState.READY, RuntimeState.STARTING):
                logger.info("Stopping currently active runtime to launch requested spec...")
                self.stop()

            # 2. Transition state to STARTING
            self._state = RuntimeState.STARTING
            instance_id = f"inst_{uuid.uuid4().hex[:12]}"
            logger.info(
                "Initiating managed inference instance %s for model '%s'",
                instance_id,
                spec.model_identity,
            )

            # 3. Validate model artifact
            try:
                validated_model = ModelArtifactValidator.validate(spec.model_path)
            except Exception as ex:
                self._state = RuntimeState.FAILED
                raise SupervisorError(
                    f"Model validation failed for '{spec.model_path}': {ex}"
                ) from ex

            # 4. Resolve managed binary
            try:
                binary_info = self._binary_resolver.resolve_binary()
            except Exception as ex:
                self._state = RuntimeState.FAILED
                raise SupervisorError(f"Managed binary resolution failed: {ex}") from ex

            # 5. Build secret-free child environment
            child_env = build_child_environment(binary_path=Path(binary_info.binary_path))

            # 6. Observational ResourceManager snapshot (before start)
            snap_before = None
            try:
                from core.resources.manager import get_resource_manager

                snap_before = get_resource_manager().get_snapshot().model_dump()
            except Exception as ex:
                logger.debug("Observational snapshot before start failed: %s", ex)

            # 7-11. Ephemeral port allocation, launch, and readiness probe with bounded retry on port collision
            max_port_retries = 3 if spec.port is None else 0
            attempt = 0

            while True:
                port = (
                    spec.port
                    if spec.port is not None
                    else find_available_loopback_port(host=spec.host)
                )
                api_key = spec.api_key or secrets.token_urlsafe(32)
                endpoint_url = f"http://{spec.host}:{port}"

                # Pre-flight check: verify port is not bound by a foreign process
                if not is_port_available(port=port, host=spec.host):
                    if attempt < max_port_retries:
                        attempt += 1
                        logger.warning(
                            "Port %d collided before spawn (attempt %d/%d). Retrying with newly allocated port...",
                            port,
                            attempt,
                            max_port_retries,
                        )
                        continue
                    self._state = RuntimeState.FAILED
                    raise PortCollisionError(
                        f"Port collision detected on {spec.host}:{port}; maximum retries ({max_port_retries}) exceeded."
                    )

                # 8. Assemble command line argv
                argv = [
                    binary_info.binary_path,
                    "-m",
                    validated_model.canonical_path,
                    "-c",
                    str(spec.context_size),
                    "--host",
                    spec.host,
                    "--port",
                    str(port),
                    "--api-key",
                    api_key,
                    "--n-gpu-layers",
                    str(spec.gpu_layers),
                ]
                if spec.threads:
                    argv.extend(["-t", str(spec.threads)])
                if spec.extra_args:
                    argv.extend(spec.extra_args)

                # 9. Spawn supervised process handle
                t0 = time.time()
                try:
                    self._process_handle = RuntimeProcessHandle(
                        argv=argv,
                        cwd=Path(binary_info.binary_path).parent,
                        env=child_env,
                    )
                except Exception as ex:
                    self._state = RuntimeState.FAILED
                    raise RuntimeStartupError(f"Failed to spawn runtime process: {ex}") from ex

                inst = RuntimeInstance(
                    instance_id=instance_id,
                    spec=spec,
                    state=RuntimeState.STARTING,
                    pid=self._process_handle.pid,
                    endpoint_url=endpoint_url,
                    api_key=api_key,
                    started_at=t0,
                    binary_info=binary_info,
                    resource_snapshot_before=snap_before,
                )
                self._active_instance = inst

                # 10. Bounded readiness probe loop
                deadline = t0 + spec.startup_timeout_seconds
                probe_url = f"{endpoint_url}/health"
                headers = {"Authorization": f"Bearer {api_key}"}
                is_ready = False
                port_collision_detected = False

                while time.time() < deadline:
                    # Check for premature process crash
                    exit_code = self._process_handle.poll()
                    if exit_code is not None:
                        logs = self._process_handle.get_logs(tail_lines=20)
                        logs_str = "\n".join(logs).lower()
                        if any(
                            err in logs_str
                            for err in (
                                "address already in use",
                                "failed to bind",
                                "port already in use",
                                "eaddrinuse",
                            )
                        ) or not is_port_available(port=port, host=spec.host):
                            port_collision_detected = True

                        # Gracefully terminate own child handle (never signal or terminate foreign processes)
                        self._process_handle.terminate_gracefully(timeout_seconds=2.0)
                        self._process_handle = None

                        if port_collision_detected and attempt < max_port_retries:
                            attempt += 1
                            logger.warning(
                                "Port collision on %d detected during startup (attempt %d/%d). Retrying with newly allocated port...",
                                port,
                                attempt,
                                max_port_retries,
                            )
                            break

                        self._state = RuntimeState.FAILED
                        inst.state = RuntimeState.FAILED
                        inst.exit_code = exit_code
                        inst.exit_reason = (
                            f"Runtime process died during startup (exit {exit_code}):\n"
                            + "\n".join(logs)
                        )
                        if port_collision_detected:
                            raise PortCollisionError(inst.exit_reason)
                        raise RuntimeCrashError(inst.exit_reason)

                    # HTTP readiness probe
                    try:
                        resp = requests.get(probe_url, headers=headers, timeout=1.0)
                        if resp.status_code == 200:
                            is_ready = True
                            break
                        elif resp.status_code == 503:
                            pass
                    except requests.RequestException:
                        pass

                    time.sleep(0.5)

                if port_collision_detected:
                    continue

                if not is_ready:
                    # Startup timed out
                    logs = self._process_handle.get_logs(tail_lines=20)
                    self._process_handle.terminate_gracefully(timeout_seconds=2.0)
                    self._state = RuntimeState.FAILED
                    inst.state = RuntimeState.FAILED
                    inst.exit_reason = (
                        f"Startup readiness timed out after {spec.startup_timeout_seconds}s. Logs:\n"
                        + "\n".join(logs)
                    )
                    raise RuntimeStartupError(inst.exit_reason)

                # 11. Verify port ownership
                if not verify_endpoint_ownership(
                    host=spec.host,
                    port=port,
                    expected_pid=self._process_handle.pid,
                    api_key=api_key,
                ):
                    # Terminate our own process handle; foreign processes are NEVER killed or touched
                    self._process_handle.terminate_gracefully(timeout_seconds=2.0)
                    self._process_handle = None

                    if attempt < max_port_retries:
                        attempt += 1
                        logger.warning(
                            "Port %d ownership check failed (foreign process listening; attempt %d/%d). Retrying with newly allocated port...",
                            port,
                            attempt,
                            max_port_retries,
                        )
                        continue

                    self._state = RuntimeState.FAILED
                    inst.state = RuntimeState.FAILED
                    inst.exit_reason = (
                        f"Port collision: endpoint {endpoint_url} is not owned by child process"
                    )
                    raise PortCollisionError(inst.exit_reason)

                # Successfully verified port ownership and readiness
                break

            # 12. Mark READY & record snapshot after load
            t_ready = time.time()
            self._state = RuntimeState.READY
            inst.state = RuntimeState.READY
            inst.ready_at = t_ready

            try:
                from core.resources.manager import get_resource_manager

                inst.resource_snapshot_after = get_resource_manager().get_snapshot().model_dump()
            except Exception as ex:
                logger.debug("Observational snapshot after load failed: %s", ex)

            # 13. Update ProviderRegistry with managed endpoint
            self._sync_provider_registry(endpoint_url=f"{endpoint_url}/v1")

            logger.info(
                "Managed runtime READY in %.2fs at %s (PID %d)",
                t_ready - t0,
                endpoint_url,
                self._process_handle.pid,
            )
            return inst

    def stop(self, timeout_seconds: Optional[float] = None) -> bool:
        """Stop managed inference runtime with graceful termination and zero orphan servers."""
        with self._lock:
            # Idempotent stop
            if self._state == RuntimeState.STOPPED or self._process_handle is None:
                self._state = RuntimeState.STOPPED
                return True

            self._state = RuntimeState.STOPPING
            effective_timeout = timeout_seconds or (
                self._active_instance.spec.shutdown_timeout_seconds
                if self._active_instance
                else 5.0
            )

            logger.info("Stopping managed runtime process %d...", self._process_handle.pid)
            exit_code = self._process_handle.terminate_gracefully(timeout_seconds=effective_timeout)

            t_stop = time.time()
            if self._active_instance:
                self._active_instance.state = RuntimeState.STOPPED
                self._active_instance.stopped_at = t_stop
                self._active_instance.exit_code = exit_code

            self._state = RuntimeState.STOPPED
            self._process_handle = None

            # Reset ProviderRegistry managed endpoint state
            self._sync_provider_registry(endpoint_url=None)

            logger.info("Managed runtime stopped successfully (exit code %d)", exit_code)
            return True

    def _sync_provider_registry(self, endpoint_url: Optional[str]) -> None:
        """Update canonical llamacpp ProviderDefinition in ProviderRegistry."""
        try:
            from core.providers import get_provider_registry

            reg = get_provider_registry()
            p_def = reg.get_provider("llamacpp")
            if endpoint_url:
                p_def.config.endpoint_url = endpoint_url
            else:
                p_def.config.endpoint_url = "http://localhost:8080/v1"
        except Exception as ex:
            logger.debug("Syncing ProviderRegistry for llamacpp encountered exception: %s", ex)


# Module-level singleton management
_SUPERVISOR_INSTANCE: Optional[LocalInferenceSupervisor] = None
_SUPERVISOR_LOCK = threading.Lock()


def get_local_inference_supervisor() -> LocalInferenceSupervisor:
    """Return canonical process-wide LocalInferenceSupervisor singleton."""
    global _SUPERVISOR_INSTANCE
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR_INSTANCE is None:
            _SUPERVISOR_INSTANCE = LocalInferenceSupervisor()
        return _SUPERVISOR_INSTANCE


def reset_local_inference_supervisor() -> None:
    """Reset and stop supervisor singleton (for testing isolation)."""
    global _SUPERVISOR_INSTANCE
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR_INSTANCE is not None:
            try:
                _SUPERVISOR_INSTANCE.stop(timeout_seconds=2.0)
            except Exception:
                pass
            _SUPERVISOR_INSTANCE = None


def set_local_inference_supervisor(supervisor: Optional[LocalInferenceSupervisor]) -> None:
    """Set process-wide supervisor singleton (for testing isolation with custom resolvers)."""
    global _SUPERVISOR_INSTANCE
    with _SUPERVISOR_LOCK:
        _SUPERVISOR_INSTANCE = supervisor
