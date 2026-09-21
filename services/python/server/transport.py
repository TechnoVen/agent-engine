"""services/python/server/transport.py

Reusable SSE Streaming & Event Transport Utilities.
Governing ADR: ADR-016 (Single Authoritative Execution Kernel Invariant)
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import json
from typing import Any, Optional


def format_sse_chunk(event: Optional[str], data: Any) -> str:
    """Format an SSE message chunk conformant with the W3C EventSource spec."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    if isinstance(data, (dict, list)):
        payload_str = json.dumps(data)
    else:
        payload_str = str(data)
    for line in payload_str.split("\n"):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def format_sse_comment(comment: str) -> str:
    """Format a keepalive or informational SSE comment."""
    return f": {comment}\n\n"


def format_sse_error(code: str, message: str, execution_id: Optional[str] = None) -> str:
    """Format an SSE error event."""
    payload = {"error": message, "error_code": code}
    if execution_id:
        payload["execution_id"] = execution_id
    return format_sse_chunk("error", payload)
