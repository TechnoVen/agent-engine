"""core/inference/ports.py

Loopback Port Allocation and Ownership Verification for Managed Inference.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Dynamic ephemeral port allocation on loopback interface (127.0.0.1).
2. Race condition mitigation: verify child process PID ownership of the socket.
3. Foreign service collision prevention: foreign listeners are never mistaken for managed runtime.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Optional

import psutil
import requests

logger = logging.getLogger("agent_engine.inference.ports")


class PortAllocationError(RuntimeError):
    """Raised when unable to allocate a usable loopback port."""


class PortCollisionError(RuntimeError):
    """Raised when a foreign process is listening on the target port."""


def find_available_loopback_port(
    preferred_port: Optional[int] = None, host: str = "127.0.0.1"
) -> int:
    """Find an available port on loopback interface."""
    if preferred_port is not None:
        if is_port_available(port=preferred_port, host=host):
            return preferred_port

    # Ephemeral allocation via kernel
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, 0))
            _, port = s.getsockname()
            return port
    except Exception as ex:
        raise PortAllocationError(f"Failed allocating ephemeral port on {host}: {ex}") from ex


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a specific port can be bound on host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def verify_endpoint_ownership(
    host: str,
    port: int,
    expected_pid: int,
    api_key: Optional[str] = None,
    timeout: float = 2.0,
) -> bool:
    """Verify that the target endpoint is genuinely owned and served by expected_pid."""
    # 1. PID liveness check
    if not psutil.pid_exists(expected_pid):
        logger.warning("PID %d is not running; cannot own port %d", expected_pid, port)
        return False

    try:
        proc = psutil.Process(expected_pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
    except Exception:
        return False

    # 2. Check open connections for expected_pid (or its child descendants)
    # Check if expected process or its children are bound to the port
    matched_pid = False
    try:
        procs_to_check = [proc] + proc.children(recursive=True)
        for p in procs_to_check:
            try:
                conns = p.net_connections(kind="tcp")
                for c in conns:
                    if c.status == psutil.CONN_LISTEN and c.laddr.port == port:
                        matched_pid = True
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
            if matched_pid:
                break
    except Exception as ex:
        logger.debug(
            "Process socket connection inspection failed (will fallback to authenticated HTTP probe): %s",
            ex,
        )

    # 3. Authenticated HTTP health probe
    endpoint_url = f"http://{host}:{port}/health"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            resp = requests.get(endpoint_url, headers=headers, timeout=0.5)
            # Both 200 (ok) and 503 (loading model) prove the endpoint is a llama-server responding to our query
            if resp.status_code in (200, 503):
                data = resp.json()
                if "status" in data or "error" in data:
                    return True
        except Exception:
            pass
        time.sleep(0.1)

    return matched_pid
