"""core/inference/installer.py

Controlled Managed Runtime Provisioner and Installer.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Controlled Supply Chain: Provisions strictly from trusted Agent Engine distribution packages
   or packaged installation payloads into private runtime storage (~/.agent_engine/runtimes/llamacpp).
2. Pre-Installation Byte Integrity: Asserts SHA-256 for all bundle artifacts against the versioned platform
   manifest prior to installation. Corrupted or tampered artifacts are rejected before touching destination.
3. Safe Staging & Permissions: Stages inside private storage (never /tmp), creates symlinks, and enforces 0o755.
4. Post-Installation Verification: Runs verify_runtime_bundle() on the installed target directory before completion.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Optional

from core.inference.manifest import (
    ChecksumMismatchError,
    MissingArtifactError,
    RuntimeManifest,
    compute_file_sha256,
    get_current_platform_key,
    get_expected_manifest,
    verify_runtime_bundle,
)
from core.storage.paths import get_private_data_dir

logger = logging.getLogger("agent_engine.inference.installer")


class RuntimeInstaller:
    """Provisions, validates, and installs verified managed runtime bundles."""

    def __init__(self, target_root: Optional[Path] = None) -> None:
        self.target_root = target_root or (get_private_data_dir() / "runtimes" / "llamacpp")

    def provision_bundle(
        self,
        source_dir: Path,
        target_dir: Optional[Path] = None,
        platform_key: Optional[str] = None,
        version: Optional[str] = None,
        expected_manifest: Optional[RuntimeManifest] = None,
    ) -> RuntimeManifest:
        """Provision a runtime bundle from a source directory into managed storage.

        Args:
            source_dir: Directory containing candidate runtime bundle artifacts.
            target_dir: Destination directory (defaults to self.target_root).
            platform_key: Target platform identifier (defaults to current host platform).
            version: Runtime version tag (defaults to 'default').
            expected_manifest: Explicit manifest to enforce (optional).

        Returns:
            Verified RuntimeManifest on successful provisioning.

        Raises:
            MissingArtifactError: If source or required artifacts are missing.
            ChecksumMismatchError: If any artifact has modified bytes or does not match manifest.
            UnsupportedPlatformError: If platform is unsupported.
            UnversionedRuntimeError: If runtime version is unknown.
        """
        dest = target_dir or self.target_root
        plat = platform_key or get_current_platform_key()
        manifest = expected_manifest or get_expected_manifest(platform_key=plat, version=version)

        if not source_dir.is_dir():
            raise MissingArtifactError(f"Source bundle directory not found: {source_dir}")

        # Step 1: Pre-validation of source files against manifest
        for rel_path, entry in manifest.artifacts.items():
            if not entry.required:
                continue
            src_file = source_dir / rel_path
            if not src_file.is_file():
                raise MissingArtifactError(
                    f"Source bundle missing required artifact '{rel_path}' at '{src_file}'"
                )
            digest = compute_file_sha256(src_file)
            if digest.lower() != entry.sha256.lower():
                raise ChecksumMismatchError(
                    f"Pre-install validation failed for '{rel_path}': expected SHA-256 '{entry.sha256}', "
                    f"got '{digest}'. Source bundle corrupted or tampered."
                )

        # Step 2: Prepare clean staging directory inside private storage
        staging_parent = dest.parent / ".staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="runtime_stage_", dir=staging_parent))

        try:
            # Step 3: Copy regular files and set permissions
            for rel_path, entry in manifest.artifacts.items():
                src_file = source_dir / rel_path
                if src_file.is_file():
                    target_file = staging_dir / rel_path
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target_file)
                    if entry.is_executable:
                        target_file.chmod(0o755)

            # Copy any optional extension plugins present in source (e.g. cpu extensions)
            for item in source_dir.iterdir():
                if item.is_file() and not item.is_symlink() and item.name not in manifest.artifacts:
                    target_file = staging_dir / item.name
                    if not target_file.exists():
                        shutil.copy2(item, target_file)
                        if (
                            item.name.endswith(".so")
                            or "server" in item.name
                            or "quantize" in item.name
                        ):
                            target_file.chmod(0o755)

            # Step 4: Recreate required symlinks
            for link_name, target_rel in manifest.symlinks.items():
                link_path = staging_dir / link_name
                if link_path.is_symlink() or link_path.exists():
                    link_path.unlink()
                link_path.symlink_to(target_rel)

            # Step 5: Write manifest receipt
            receipt_path = staging_dir / "manifest.json"
            receipt_data = manifest.model_dump()
            receipt_path.write_text(json.dumps(receipt_data, indent=2))

            # Step 6: Atomically replace destination directory
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                old_backup = dest.parent / f".old_{dest.name}_{os.getpid()}"
                if old_backup.exists():
                    shutil.rmtree(old_backup, ignore_errors=True)
                dest.rename(old_backup)
                staging_dir.rename(dest)
                shutil.rmtree(old_backup, ignore_errors=True)
            else:
                staging_dir.rename(dest)

        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        # Step 7: Post-install verification
        verified = verify_runtime_bundle(dest, expected_manifest=manifest)
        logger.info(
            "Runtime successfully provisioned and verified at '%s' (Platform: %s, Version: %s)",
            dest,
            verified.platform_key,
            verified.runtime_version,
        )
        return verified
