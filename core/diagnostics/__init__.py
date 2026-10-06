"""core/diagnostics

Central Diagnostics Redaction and Export subsystem.
Part of Milestone R2 Task R2.12.
"""

from typing import Any, Optional, Tuple

from core.diagnostics.exporter import DiagnosticsExporter
from core.diagnostics.models import DiagnosticBundle, ExportManifest, RedactionReport
from core.diagnostics.policy import RedactionPolicy
from core.diagnostics.redactor import DiagnosticsRedactor


def redact_sensitive_data(obj: Any) -> Any:
    """Backward-compatible helper recursively sanitizing dictionaries, lists, and strings."""
    redactor = DiagnosticsRedactor()
    redacted, _ = redactor.redact(obj)
    return redacted


def build_diagnostics_bundle(
    format: str = "zip",
    storage: Optional[Any] = None,
    project_root: Optional[Any] = None,
) -> Tuple[bytes, str, str]:
    """Backward-compatible entrypoint generating diagnostics bundle.

    Returns:
        (content_bytes, content_type, filename)
    """
    exporter = DiagnosticsExporter(storage=storage, project_root=project_root)
    bundle = exporter.export_bundle(format=format)
    return bundle.payload_bytes, bundle.content_type, bundle.filename


__all__ = [
    "DiagnosticsRedactor",
    "RedactionPolicy",
    "DiagnosticsExporter",
    "DiagnosticBundle",
    "ExportManifest",
    "RedactionReport",
    "build_diagnostics_bundle",
    "redact_sensitive_data",
]
