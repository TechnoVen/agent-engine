"""core/diagnostics/exporter.py

Packaging and export pipeline for Agent Engine diagnostics bundles.
Part of Milestone R2 Task R2.12.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import platform
import sys
import tarfile
import time
from typing import Any, Dict, List, Optional
import uuid
import zipfile

import psutil

from core.config.settings import get_settings_manager
from core.diagnostics.models import DiagnosticBundle, ExportManifest, RedactionReport
from core.diagnostics.redactor import DiagnosticsRedactor
from core.telemetry.hardware import get_hardware_telemetry_tracker

logger = logging.getLogger("agent_engine.diagnostics.exporter")


class DiagnosticsExporter:
    """Assembles, redacts at egress boundary, and packages diagnostics bundles."""

    def __init__(
        self,
        redactor: Optional[DiagnosticsRedactor] = None,
        storage: Optional[Any] = None,
        project_root: Optional[Path | str] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.redactor = redactor or DiagnosticsRedactor(project_root=self.project_root)
        self.storage = storage

    def is_path_blocked(self, rel_path: str) -> bool:
        """Check if file matches blocked sensitive patterns (Closure Item 18)."""
        norm = rel_path.replace("\\", "/")
        name = Path(norm).name
        for pat in self.redactor.policy.blocked_file_patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(norm, pat):
                return True
        return False

    def gather_system_info(self, report: RedactionReport) -> Dict[str, Any]:
        """Gather host specifications and process telemetry with paths minimized."""
        hw = get_hardware_telemetry_tracker().get_telemetry()
        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()

        raw_info = {
            "agent_engine_version": "0.1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
                "executable": self.redactor.redact_text(sys.executable, report),
                "prefix": self.redactor.redact_text(sys.prefix, report),
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
        redacted, _ = self.redactor.redact(raw_info)
        return redacted

    def gather_schema_versions(self) -> Dict[str, Any]:
        """Gather API and storage schema metadata."""
        engine_name = "SQLite3"
        if self.storage and hasattr(self.storage, "name"):
            engine_name = self.storage.name

        return {
            "openapi_version": "3.0.3",
            "specification_title": "Agent Engine Desktop Shell & Local Core API",
            "api_version": "0.1.0",
            "storage_engine": engine_name,
            "schema_migration_version": 1,
            "active_tables": [
                "audit_logs",
                "scheduled_tasks",
                "staged_patches",
                "sessions",
                "messages",
                "credentials",
            ],
            "mcp_protocol_version": "2024-11-05",
            "audit_schema_hash": "sha256-zero-trust-boundary-v1",
        }

    def gather_redacted_config(self, report: RedactionReport) -> Dict[str, Any]:
        """Load settings from storage and redact at egress boundary."""
        try:
            settings = get_settings_manager().load_settings()
            raw_dict = settings.to_dict()
        except Exception:
            raw_dict = {}
        redacted, _ = self.redactor.redact(raw_dict)
        return redacted

    def gather_redacted_logs(self, report: RedactionReport) -> str:
        """Read recent audit logs and apply egress boundary redaction."""
        lines: List[str] = [
            f"=== AGENT ENGINE AUDIT & ACTIVITY LOGS (EXPORTED {datetime.datetime.now(datetime.timezone.utc).isoformat()}) ===",
            "NOTE: All authentication tokens, API keys, credentials, and private payloads have been scrubbed at egress boundary.",
            "",
        ]

        if not self.storage:
            try:
                from core.storage import get_storage

                storage = get_storage()
            except Exception:
                storage = None
        else:
            storage = self.storage

        if storage and hasattr(storage, "list_audit_logs"):
            try:
                logs = storage.list_audit_logs(limit=self.redactor.policy.max_log_lines)
                for entry in logs:
                    tool_args = (
                        entry.tool_args
                        if hasattr(entry, "tool_args")
                        else entry.get("tool_args", {})
                    )
                    result = entry.result if hasattr(entry, "result") else entry.get("result", {})
                    ts = entry.timestamp if hasattr(entry, "timestamp") else entry.get("timestamp")
                    eid = entry.id if hasattr(entry, "id") else entry.get("id")
                    tool_name = (
                        entry.tool_name if hasattr(entry, "tool_name") else entry.get("tool_name")
                    )
                    decision = (
                        entry.decision if hasattr(entry, "decision") else entry.get("decision")
                    )
                    risk_level = (
                        entry.risk_level
                        if hasattr(entry, "risk_level")
                        else entry.get("risk_level")
                    )

                    redacted_args, _ = self.redactor.redact(tool_args)
                    redacted_res, _ = self.redactor.redact(result)
                    line = (
                        f"[{ts}] ID={eid} TOOL={tool_name} "
                        f"DECISION={decision} RISK={risk_level} "
                        f"ARGS={json.dumps(redacted_args)} RESULT={json.dumps(redacted_res)}"
                    )
                    lines.append(self.redactor.redact_text(line, report))
            except Exception as err:
                lines.append(f"[SYSTEM] Log retrieval error: {err}")
        else:
            lines.append("[SYSTEM] No audit storage connected.")

        return "\n".join(lines)

    def export_bundle(
        self,
        format: str = "zip",
        custom_files: Optional[Dict[str, Any]] = None,
        bundle_id: Optional[str] = None,
    ) -> DiagnosticBundle:
        """Create and package an egress-redacted diagnostics bundle (Closure Item 14)."""
        bid = bundle_id or f"diag-{uuid.uuid4().hex[:12]}"
        ts_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        overall_report = RedactionReport()

        # Gather standard components
        system_info = self.gather_system_info(overall_report)
        schema_versions = self.gather_schema_versions()
        config_redacted = self.gather_redacted_config(overall_report)
        logs_redacted = self.gather_redacted_logs(overall_report)

        # File registry: filename -> content bytes
        bundle_files: Dict[str, bytes] = {
            "system_info.json": json.dumps(system_info, indent=2).encode("utf-8"),
            "schema_versions.json": json.dumps(schema_versions, indent=2).encode("utf-8"),
            "config_redacted.json": json.dumps(config_redacted, indent=2).encode("utf-8"),
            "logs_redacted.txt": logs_redacted.encode("utf-8"),
        }

        # Add custom files if provided, enforcing blocked patterns & redaction
        if custom_files:
            for fname, content in custom_files.items():
                if self.is_path_blocked(fname):
                    logger.warning(f"Blocked sensitive file from diagnostics bundle: {fname}")
                    overall_report.record_redaction("blocked_private_payload")
                    continue

                if isinstance(content, (dict, list)):
                    redacted, _ = self.redactor.redact(content)
                    raw_bytes = json.dumps(redacted, indent=2).encode("utf-8")
                elif isinstance(content, str):
                    redacted_str = self.redactor.redact_text(content, overall_report)
                    raw_bytes = redacted_str.encode("utf-8")
                elif isinstance(content, bytes):
                    # For binary/bytes, check if text decode is possible
                    try:
                        decoded = content.decode("utf-8")
                        redacted_str = self.redactor.redact_text(decoded, overall_report)
                        raw_bytes = redacted_str.encode("utf-8")
                    except UnicodeDecodeError:
                        raw_bytes = content
                else:
                    redacted, _ = self.redactor.redact(content)
                    raw_bytes = json.dumps(redacted, indent=2).encode("utf-8")

                bundle_files[fname] = raw_bytes

        # Build manifest
        all_files = sorted(list(bundle_files.keys()) + ["manifest.json"])
        manifest = ExportManifest(
            bundle_id=bid,
            created_at=time.time(),
            format=format.lower(),
            files=all_files,
            total_bytes=sum(len(b) for b in bundle_files.values()),
            redaction_summary=overall_report.to_dict(),
        )
        manifest_bytes = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
        manifest.total_bytes += len(manifest_bytes)
        bundle_files["manifest.json"] = manifest_bytes

        # Package format
        fmt = format.lower()
        if fmt == "json":
            json_bundle = {
                "manifest": manifest.to_dict(),
                "system_info": system_info,
                "schema_versions": schema_versions,
                "config": config_redacted,
                "logs": logs_redacted.splitlines(),
            }
            payload_bytes = json.dumps(json_bundle, indent=2).encode("utf-8")
            content_type = "application/json"
            filename = f"agent_engine_diagnostics_{ts_slug}.json"
        elif fmt in ("tar.gz", "tar"):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for fname, bdata in sorted(bundle_files.items()):
                    ti = tarfile.TarInfo(name=fname)
                    ti.size = len(bdata)
                    ti.mtime = int(time.time())
                    ti.mode = 0o600
                    tar.addfile(ti, io.BytesIO(bdata))
            payload_bytes = buf.getvalue()
            content_type = "application/gzip"
            filename = f"agent_engine_diagnostics_{ts_slug}.tar.gz"
        else:  # default zip
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, bdata in sorted(bundle_files.items()):
                    zf.writestr(fname, bdata)
            payload_bytes = buf.getvalue()
            content_type = "application/zip"
            filename = f"agent_engine_diagnostics_{ts_slug}.zip"

        manifest.sha256_hash = hashlib.sha256(payload_bytes).hexdigest()

        return DiagnosticBundle(
            manifest=manifest,
            payload_bytes=payload_bytes,
            content_type=content_type,
            filename=filename,
            redaction_report=overall_report,
        )
