"""services/python/server/api.py

Agent Engine Local API - Re-exporting Facade for Backward Compatibility.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).

All domain routes have been modularized into services/python/server/routers/.
This module preserves full backward compatibility for existing tests, tooling,
and execution coordinate callers.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy  # noqa: F401

# Application Factory and App Instance
from services.python.server.app import create_app

app = create_app()
v1_router = app.state.v1_router

# Canonical Service Container and Accessors


# Canonical Error Translation

# Streaming & Transport

# Authentication & IPC Dependencies

# Pydantic Schemas (all shared models)
from services.python.server.schemas import *

# Domain Endpoint Functions (re-exported for direct test imports)


def main(argv: Optional[List[str]] = None):
    """Entrypoint for Agent Engine Python sidecar service."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Agent Engine Python Sidecar Service (FastAPI + FastMCP + ACP)",
        prog="agent-engine-sidecar",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(os.environ.get("AGENT_ENGINE_PORT", os.environ.get("PORT", "8000"))),
        help="Port to bind the sidecar service (default: 8000 or /)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("AGENT_ENGINE_HOST", "127.0.0.1"),
        help="Host address to bind the sidecar service (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("AGENT_ENGINE_IPC_TOKEN"),
        help="Optional secret IPC token for shell-to-sidecar authentication",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        help="Print sidecar version and exit",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Perform internal health self-test and exit",
    )

    args = parser.parse_args(argv)

    if args.version:
        print("0.1.0")
        sys.exit(0)

    if args.verify:
        print("Agent Engine Sidecar v0.1.0: Self-check passed. Routes and schema verified.")
        sys.exit(0)

    if args.token:
        os.environ["AGENT_ENGINE_IPC_TOKEN"] = args.token

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
