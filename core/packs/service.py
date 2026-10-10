"""core/packs/service.py

Capability Pack Discovery, Validation, and Canonical Binding Service for Agent Engine 0.5.
Part of Milestone R5 (Founder Dogfood & Capability Packs) - Task R5.1 (Core Pack MVP).

Governing Invariant (ADR-016):
Every consequential capability declared in a capability pack MUST bind directly
to an existing canonical product service (ExecutionCoordinator, ProjectService,
JobService, ApprovalService). Zero shadow runtimes are permitted.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import yaml

from core.packs.models import PackCapability, PackManifest
from core.storage.paths import get_private_data_dir

logger = logging.getLogger("agent_engine.packs.service")

# Permitted canonical product service bindings for Agent Engine 0.5
CANONICAL_BINDING_ALLOWLIST: Set[str] = {
    "core.execution.coordinator.ExecutionCoordinator",
    "core.projects.service.ProjectService",
    "core.projects.models.Project",
    "core.jobs.service.JobService",
    "core.safety.service.ApprovalService",
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
    """Manages discovery, validation, lifecycle, and one-unit enablement of Capability Packs."""

    def __init__(
        self,
        packs_dir: Optional[Union[str, Path]] = None,
        state_file: Optional[Union[str, Path]] = None,
    ):
        if packs_dir is not None:
            self.packs_dir = Path(packs_dir)
        else:
            # Default to repo packs/ directory
            repo_root = Path(__file__).resolve().parents[2]
            self.packs_dir = repo_root / "packs"

        if state_file is not None:
            self.state_file = Path(state_file)
        else:
            self.state_file = get_private_data_dir() / "packs_state.json"

        self._packs: Dict[str, PackManifest] = {}
        self._enabled_states: Dict[str, bool] = {}
        self.load_states()

    def load_states(self) -> None:
        """Load persisted pack enablement states from disk."""
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._enabled_states = json.load(f)
            except Exception as e:
                logger.warning("Failed to load pack states from %s: %s", self.state_file, e)
                self._enabled_states = {}
        else:
            self._enabled_states = {}

    def save_states(self) -> None:
        """Persist pack enablement states atomically to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._enabled_states, f, indent=2)
            tmp_path.replace(self.state_file)
        except Exception as e:
            logger.error("Failed to save pack states to %s: %s", self.state_file, e)

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

        # Default system packs to enabled
        if manifest.category == "system" and manifest.id not in self._enabled_states:
            self._enabled_states[manifest.id] = True
            self.save_states()

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

    def is_pack_enabled(self, pack_id: str) -> bool:
        """Check whether a pack is currently enabled."""
        pack = self.get_pack(pack_id)
        if not pack:
            return False
        # System packs are permanently enabled
        if pack.category == "system":
            return True
        return self._enabled_states.get(pack_id, False)

    def enable_pack(self, pack_id: str) -> bool:
        """Enable capability pack as one unit after verifying all capabilities and bindings."""
        pack = self.get_pack(pack_id)
        if not pack:
            raise PackValidationError(f"Cannot enable unknown pack '{pack_id}'")

        # Validate all capabilities prior to enabling
        for cap in pack.capabilities:
            self._verify_canonical_binding(cap)

        self._enabled_states[pack_id] = True
        self.save_states()
        logger.info("Capability pack '%s' enabled as one unit", pack_id)
        return True

    def disable_pack(self, pack_id: str) -> bool:
        """Disable capability pack (system packs cannot be disabled)."""
        pack = self.get_pack(pack_id)
        if not pack:
            raise PackValidationError(f"Cannot disable unknown pack '{pack_id}'")

        if pack.category == "system":
            raise PackValidationError(
                f"Capability pack '{pack_id}' is a system-installed pack and cannot be disabled."
            )

        self._enabled_states[pack_id] = False
        self.save_states()
        logger.info("Capability pack '%s' disabled", pack_id)
        return True

    def get_pack_summary(self, pack_id: str) -> Optional[Dict[str, Any]]:
        """Return truthful status summary for a capability pack."""
        pack = self.get_pack(pack_id)
        if not pack:
            return None

        is_system = pack.category == "system"
        enabled = self.is_pack_enabled(pack_id)

        return {
            "id": pack.id,
            "name": pack.name,
            "version": pack.version,
            "category": pack.category,
            "description": pack.description,
            "author": pack.author,
            "enabled": enabled,
            "is_system": is_system,
            "capabilities": [c.model_dump() for c in pack.capabilities],
            "permissions": [p.model_dump() for p in pack.permissions],
        }

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
    state_file: Optional[Union[str, Path]] = None,
) -> CapabilityPackService:
    """Get or initialize the process-level singleton CapabilityPackService."""
    global _global_pack_service
    if _global_pack_service is None or packs_dir is not None:
        _global_pack_service = CapabilityPackService(packs_dir=packs_dir, state_file=state_file)
        _global_pack_service.discover_packs()
    return _global_pack_service


def reset_capability_pack_service() -> None:
    """Reset global singleton for test isolation."""
    global _global_pack_service
    _global_pack_service = None
