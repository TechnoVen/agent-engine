"""Diagnostics Bundle Exporter Module for Agent Engine.

Builds a comprehensive diagnostics bundle including:
- system_info.json: host OS, Python, CPU/RAM/VRAM hardware telemetry, process stats
- schema_versions.json: OpenAPI, storage tables, schema versions
- config_redacted.json: encrypted local settings with all credentials/tokens sanitized
- logs_redacted.txt: recent audit trail records with authorization and secrets redacted

Supports packaging as a compressed .zip archive or structured JSON.
"""

import datetime
import io
import json
import logging
import os
import platform
import re
import sys
from typing import Any, Dict, List, Tuple
import zipfile

import psutil

from core.config.settings import get_settings_manager
from core.telemetry.hardware import get_hardware_telemetry_tracker

logger = logging.getLogger(__name__)


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively sanitize dictionaries and lists, masking secret keys, tokens, and URLs."""
    sensitive_keywords = [
        "key",
        "secret",
        "token",
        "password",
        "auth",
        "webhook",
        "credential",
        "bearer",
        "private",
    ]

    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in sensitive_keywords):
                sanitized[k] = "***REDACTED***" if v else None
            elif isinstance(v, (dict, list)):
                sanitized[k] = redact_sensitive_data(v)
            elif isinstance(v, str) and (
                v.startswith("sk-") or "Bearer " in v or "ghp_" in v or len(v) > 50
            ):
                # Generic pattern masking for token-like values
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        # Mask common auth headers and token parameters if found in string lines
        cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1***REDACTED***", obj)
        cleaned = re.sub(r"(sk-[A-Za-z0-9_\-]{8,})", r"***REDACTED***", cleaned)
        cleaned = re.sub(
            r"((?:X-IPC-Token|token)[:=]\s*)[A-Fa-f0-9_\-]{16,}",
            r"\1***REDACTED***",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned
    return obj


def gather_system_info() -> Dict[str, Any]:
    """Gather non-sensitive host system specifications and process telemetry."""
    hw = get_hardware_telemetry_tracker().get_telemetry()
    proc = psutil.Process(os.getpid())
    mem_info = proc.memory_info()

    return {
        "agent_engine_version": "0.1.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
            "node": platform.node(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "process": {
            "pid": os.getpid(),
            "cpu_percent": proc.cpu_percent(interval=None),
            "memory_rss_mb": round(mem_info.rss / (1024 * 1024), 2),
            "memory_vms_mb": round(mem_info.vms / (1024 * 1024), 2),
            "threads": proc.num_threads(),
            "create_time": datetime.datetime.fromtimestamp(proc.create_time()).isoformat(),
        },
        "hardware": {
            "cpu_logical_cores": hw.cpu_cores_logical,
            "cpu_physical_cores": hw.cpu_cores_physical,
            "cpu_usage_percent": hw.cpu_usage_percent,
            "ram_total_gb": hw.ram_total_gb,
            "ram_used_gb": hw.ram_used_gb,
            "ram_available_gb": hw.ram_available_gb,
            "ram_used_percent": hw.ram_used_percent,
            "gpu_detected": hw.gpu_detected,
            "gpu_model": hw.gpu_model,
            "gpu_vendor": hw.gpu_vendor,
            "vram_total_gb": hw.vram_total_gb,
            "vram_used_gb": hw.vram_used_gb,
            "vram_free_gb": hw.vram_free_gb,
            "vram_used_percent": hw.vram_used_percent,
            "vram_warning": hw.vram_warning,
            "tokens_per_second": hw.tokens_per_second,
            "ollama_active": hw.ollama_active,
            "llamacpp_active": hw.llamacpp_active,
        },
    }


def gather_schema_versions() -> Dict[str, Any]:
    """Gather OpenAPI specification and database table metadata."""
    from core.storage import get_storage

    storage = get_storage()
    table_names = [
        "audit_logs",
        "scheduled_tasks",
        "staged_patches",
        "sessions",
        "messages",
        "credentials",
    ]

    return {
        "openapi_version": "3.0.3",
        "specification_title": "Agent Engine Desktop Shell & Local Core API",
        "api_version": "0.1.0",
        "storage_engine": storage.name if hasattr(storage, "name") else "SQLite3",
        "schema_migration_version": 1,
        "active_tables": table_names,
        "mcp_protocol_version": "2024-11-05",
        "audit_schema_hash": "sha256-zero-trust-boundary-v1",
    }


def gather_redacted_config() -> Dict[str, Any]:
    """Load settings from encrypted storage and redact all secrets."""
    settings = get_settings_manager().load_settings()
    raw_dict = settings.to_dict()
    return redact_sensitive_data(raw_dict)


def gather_redacted_logs() -> str:
    """Read recent audit logs and format as redacted log stream."""
    from core.storage import get_storage

    storage = get_storage()
    lines: List[str] = [
        f"=== AGENT ENGINE AUDIT & ACTIVITY LOGS (EXPORTED {datetime.datetime.now().isoformat()}) ===",
        "NOTE: All authentication tokens, API keys, and private payloads have been scrubbed.",
        "",
    ]

    try:
        logs = storage.list_audit_logs(limit=100)
        for entry in logs:
            tool_args = (
                entry.tool_args if hasattr(entry, "tool_args") else entry.get("tool_args", {})
            )
            result = entry.result if hasattr(entry, "result") else entry.get("result", {})
            ts = entry.timestamp if hasattr(entry, "timestamp") else entry.get("timestamp")
            eid = entry.id if hasattr(entry, "id") else entry.get("id")
            tool_name = entry.tool_name if hasattr(entry, "tool_name") else entry.get("tool_name")
            decision = entry.decision if hasattr(entry, "decision") else entry.get("decision")
            risk_level = (
                entry.risk_level if hasattr(entry, "risk_level") else entry.get("risk_level")
            )

            sanitized_args = redact_sensitive_data(tool_args)
            sanitized_res = redact_sensitive_data(result)
            line = (
                f"[{ts}] ID={eid} TOOL={tool_name} "
                f"DECISION={decision} RISK={risk_level} "
                f"ARGS={json.dumps(sanitized_args)} RESULT={json.dumps(sanitized_res)}"
            )
            lines.append(redact_sensitive_data(line))
    except Exception as err:
        lines.append(f"[SYSTEM] Log retrieval error: {err}")

    return "\n".join(lines)


def build_diagnostics_bundle(format: str = "zip") -> Tuple[bytes, str, str]:
    """Generate a complete diagnostics bundle.

    Returns:
        (content_bytes, content_type, filename)
    """
    ts_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    system_info = gather_system_info()
    schema_versions = gather_schema_versions()
    config_redacted = gather_redacted_config()
    logs_redacted = gather_redacted_logs()

    if format.lower() == "json":
        bundle_dict = {
            "system_info": system_info,
            "schema_versions": schema_versions,
            "config": config_redacted,
            "logs": logs_redacted.splitlines(),
        }
        content_bytes = json.dumps(bundle_dict, indent=2).encode("utf-8")
        filename = f"agent_engine_diagnostics_{ts_slug}.json"
        return content_bytes, "application/json", filename

    # Default to .zip archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("system_info.json", json.dumps(system_info, indent=2))
        zip_file.writestr("schema_versions.json", json.dumps(schema_versions, indent=2))
        zip_file.writestr("config_redacted.json", json.dumps(config_redacted, indent=2))
        zip_file.writestr("logs_redacted.txt", logs_redacted)

    zip_bytes = buf.getvalue()
    filename = f"agent_engine_diagnostics_{ts_slug}.zip"
    return zip_bytes, "application/zip", filename
