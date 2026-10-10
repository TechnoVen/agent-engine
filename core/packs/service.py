"""core/packs/service.py

Capability Pack Discovery, Validation, and Canonical Binding Service for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).

Governing Invariant (ADR-016):
Every consequential capability declared in a capability pack MUST bind directly
to an existing canonical subsystem (ExecutionCoordinator, ModelRouter, PendingOperationRegistry,
JobWorker, ProjectStorage). Zero shadow runtimes are permitted.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Union
import yaml

from core.packs.models import PackCapability, PackManifest

logger = logging.getLogger("agent_engine.packs.service")

# Permitted canonical subsystem bindings for Agent Engine 0.5
CANONICAL_BINDING_ALLOWLIST: Set[str] = {
    "core.execution.coordinator.ExecutionCoordinator",
    "core.projects.models.Project",
    "core.router.model_router.ModelRouter",
    "core.jobs.worker.JobWorker",
    "core.safety.pending.PendingOperationRegistry",
    "core.storage.sqlite.SQLiteStorageRepository",
    "core.storage.sqlite.SQLiteJobRepository",
    "core.storage.sqlite.SQLiteJobQueue",
    "core.safety.policy.PolicyEngine",
    "core.session.store.SessionStore",
}


class PackValidationError(ValueError):
    """Raised when a pack manifest violates schema, permissions, or architectural invariants."""

    pass


class CapabilityPackService:
    """Manages discovery, validation, and lifecycle of modular Capability Packs."""

    def __init__(self, packs_dir: Optional[Union[str, Path]] = None):
        if packs_dir is not None:
            self.packs_dir = Path(packs_dir)
        else:
            # Default to repo packs/ directory
            repo_root = Path(__file__).resolve().parents[2]
            self.packs_dir = repo_root / "packs"
        self._packs: Dict[str, PackManifest] = {}

    def load_manifest(self, manifest_path: Union[str, Path]) -> PackManifest:
        """Load, validate, and verify a single manifest.yaml file."""
        path = Path(manifest_path)
        if not path.is_file():
            raise FileNotFoundError(f"Pack manifest not found at: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise PackValidationError(f"Failed to parse YAML manifest: {e}") from e

        if not isinstance(data, dict):
            raise PackValidationError("Pack manifest must be a mapping dictionary")

        try:
            manifest = PackManifest.model_validate(data)
        except Exception as e:
            raise PackValidationError(f"Pack manifest schema validation failed: {e}") from e

        # Validate canonical bindings and invariant against shadow runtimes
        for cap in manifest.capabilities:
            self._verify_canonical_binding(cap)

        self._packs[manifest.id] = manifest
        return manifest

    def _verify_canonical_binding(self, cap: PackCapability) -> None:
        """Ensure capability binds to a verified canonical subsystem with zero shadow runtimes."""
        binding = cap.canonical_binding.strip()
        if not binding:
            raise PackValidationError(
                f"Capability '{cap.id}' in pack must declare a valid canonical_binding."
            )

        if not binding.startswith("core."):
            raise PackValidationError(
                f"Capability '{cap.id}' declares non-canonical binding '{binding}'. "
                "All capabilities must bind directly to verified core.* subsystems."
            )

        if binding not in CANONICAL_BINDING_ALLOWLIST:
            # Attempt to verify the module and symbol dynamically if within core
            parts = binding.rsplit(".", 1)
            if len(parts) == 2:
                mod_name, attr_name = parts
                try:
                    mod = importlib.import_module(mod_name)
                    if not hasattr(mod, attr_name):
                        raise PackValidationError(
                            f"Canonical binding '{binding}' symbol '{attr_name}' not found in '{mod_name}'."
                        )
                except ImportError as e:
                    raise PackValidationError(
                        f"Canonical binding '{binding}' cannot be imported: {e}"
                    ) from e
            else:
                raise PackValidationError(f"Malformed canonical binding: '{binding}'")

    def discover_packs(self, packs_dir: Optional[Union[str, Path]] = None) -> List[PackManifest]:
        """Scan directory and register all discovered valid capability packs."""
        target_dir = Path(packs_dir) if packs_dir else self.packs_dir
        if not target_dir.exists():
            return []

        discovered: List[PackManifest] = []
        for child in sorted(target_dir.iterdir()):
            if child.is_dir():
                manifest_file = child / "manifest.yaml"
                if manifest_file.is_file():
                    try:
                        manifest = self.load_manifest(manifest_file)
                        discovered.append(manifest)
                    except Exception as e:
                        logger.error("Failed to load pack at %s: %s", child, e)
                        raise

        return discovered

    def get_pack(self, pack_id: str) -> Optional[PackManifest]:
        """Retrieve registered pack by its canonical ID."""
        return self._packs.get(pack_id)

    def list_packs(self) -> List[PackManifest]:
        """List all registered capability packs."""
        return list(self._packs.values())

    def validate_permission(
        self,
        pack: PackManifest,
        requested_scope: str,
        path: Optional[str] = None,
    ) -> bool:
        """Verify whether a requested action is authorized under the pack's declared permissions."""
        matching_grants = [p for p in pack.permissions if p.scope == requested_scope]
        if not matching_grants:
            return False

        if path is not None:
            # Verify path containment against granted glob patterns
            import fnmatch

            for grant in matching_grants:
                if not grant.paths:
                    return True
                for pattern in grant.paths:
                    expanded = pattern.replace("${PROJECT_ROOT}", "")
                    if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"*{expanded}"):
                        return True
            return False

        return True


_global_pack_service: Optional[CapabilityPackService] = None


def get_capability_pack_service(
    packs_dir: Optional[Union[str, Path]] = None,
) -> CapabilityPackService:
    """Get or initialize the process-level singleton CapabilityPackService."""
    global _global_pack_service
    if _global_pack_service is None or packs_dir is not None:
        _global_pack_service = CapabilityPackService(packs_dir=packs_dir)
        _global_pack_service.discover_packs()
    return _global_pack_service
