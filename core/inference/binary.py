"""core/inference/binary.py

Managed Runtime Binary Resolver and Provenance Auditor.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Rejects arbitrary user PATH, workspace/project root, /tmp, and Downloads folder lookups.
2. Resolves strictly from Agent Engine private runtime installation or packaged desktop resources (zero Ollama dependency).
3. Probes version honestly and calculates SHA-256 executable integrity digest (verifying byte integrity; trust root verification belongs to R2.13).
4. Operator AGENT_ENGINE_LLAMA_BIN override is strictly gated behind AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY or dev mode.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Optional

from core.inference.manifest import (
    RuntimeManifest,
    verify_runtime_bundle,
)
from core.inference.models import RuntimeBinaryInfo
from core.storage.paths import get_private_data_dir

logger = logging.getLogger("agent_engine.inference.binary")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def is_binary_override_allowed() -> bool:
    """Check if AGENT_ENGINE_LLAMA_BIN override is explicitly authorized.

    Allowed only when AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY=true or when running in dev/test mode
    (AGENT_ENGINE_DEV_MODE=true or AGENT_ENGINE_ENV in ('dev', 'development', 'test')).
    In default and production modes, arbitrary binary overrides are strictly rejected.
    """
    allow_flag = os.getenv("AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY", "").lower()
    if allow_flag in ("1", "true", "yes"):
        return True
    dev_flag = os.getenv("AGENT_ENGINE_DEV_MODE", "").lower()
    if dev_flag in ("1", "true", "yes"):
        return True
    env_mode = os.getenv("AGENT_ENGINE_ENV", "").lower()
    if env_mode in ("dev", "development", "test"):
        return True
    return False


class BinaryNotFoundError(FileNotFoundError):
    """Raised when no verified managed runtime binary is available."""


class UntrustedBinaryLocationError(PermissionError):
    """Raised when a candidate binary originates from an untrusted or prohibited path."""


class RuntimeBinaryResolver:
    """Discovers, validates, and records provenance of managed inference binaries."""

    def __init__(
        self,
        managed_root: Optional[Path] = None,
        enforce_integrity: bool = True,
        expected_manifest: Optional[RuntimeManifest] = None,
    ) -> None:
        self.managed_root = managed_root or (get_private_data_dir() / "runtimes" / "llamacpp")
        self.executable_name = (
            "llama-server.exe" if platform.system() == "Windows" else "llama-server"
        )
        self.enforce_integrity = enforce_integrity
        self.expected_manifest = expected_manifest

    @classmethod
    def is_prohibited_location(cls, path: Path) -> bool:
        """Verify whether candidate path falls into prohibited/untrusted directories."""
        try:
            resolved = path.resolve()
        except Exception:
            return True

        res_str = str(resolved).lower()

        # 1. Project workspace tree
        try:
            proj_str = str(PROJECT_ROOT.resolve()).lower()
            if res_str.startswith(proj_str):
                return True
        except Exception:
            pass

        # 2. Current working directory
        try:
            cwd_str = str(Path.cwd().resolve()).lower()
            if res_str.startswith(cwd_str):
                return True
        except Exception:
            pass

        # 3. System temp directories
        try:
            tmp_str = str(Path(tempfile.gettempdir()).resolve()).lower()
            if res_str.startswith(tmp_str) or res_str.startswith("/tmp"):
                return True
        except Exception:
            pass

        # 4. Downloads folder
        home = Path.home().resolve()
        downloads = (home / "Downloads").resolve()
        if res_str.startswith(str(downloads).lower()):
            return True

        return False

    def resolve_binary(self) -> RuntimeBinaryInfo:
        """Resolve and verify the managed runtime binary.

        Search order:
        1. Controlled environment override AGENT_ENGINE_LLAMA_BIN (gated by AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY/dev mode).
        2. Agent Engine private runtime directory (~/.agent_engine/runtimes/llamacpp/llama-server).
        3. System Agent Engine runtime directory (/opt/agent_engine/runtimes/llamacpp/llama-server).
        4. Packaged desktop binary resources (apps/desktop/src-tauri/binaries/).
        """
        # 1. Controlled environment override (development/test operators only)
        env_override = os.environ.get("AGENT_ENGINE_LLAMA_BIN")
        if env_override:
            if not is_binary_override_allowed():
                raise UntrustedBinaryLocationError(
                    f"Rejected AGENT_ENGINE_LLAMA_BIN='{env_override}': binary overrides are strictly disabled in production mode. "
                    "Set AGENT_ENGINE_ALLOW_UNVERIFIED_BINARY=true or enable dev mode to authorize operator binary overrides."
                )
            p = Path(env_override).expanduser()
            if self.is_prohibited_location(p):
                raise UntrustedBinaryLocationError(
                    f"Rejected AGENT_ENGINE_LLAMA_BIN='{env_override}': cannot reside in workspace, /tmp, or Downloads."
                )
            if not p.is_file() or not os.access(p, os.X_OK):
                raise BinaryNotFoundError(
                    f"Configured AGENT_ENGINE_LLAMA_BIN='{env_override}' is not an executable regular file."
                )
            return self._inspect_binary(p, provenance="controlled_override")

        # 2. Agent Engine private runtime storage (~/.agent_engine/runtimes/llamacpp/llama-server)
        managed_bin = self.managed_root / self.executable_name
        if managed_bin.is_file() and os.access(managed_bin, os.X_OK):
            if self.enforce_integrity:
                verify_runtime_bundle(self.managed_root, expected_manifest=self.expected_manifest)
            return self._inspect_binary(
                managed_bin,
                provenance="managed_installation",
                manifest_verified=self.enforce_integrity,
                bundle_integrity_verified=self.enforce_integrity,
            )

        # 3. System-wide Agent Engine runtime directory (/opt/agent_engine/runtimes/llamacpp)
        system_ae_dir = Path("/opt/agent_engine/runtimes/llamacpp")
        system_ae_bin = system_ae_dir / self.executable_name
        if system_ae_bin.is_file() and os.access(system_ae_bin, os.X_OK):
            verify_runtime_bundle(system_ae_dir)
            return self._inspect_binary(
                system_ae_bin,
                provenance="system_managed_installation",
                manifest_verified=True,
                bundle_integrity_verified=True,
            )

        # 4. Packaged desktop resources
        packaged_dir = PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
        packaged_bin = packaged_dir / self.executable_name
        if packaged_bin.is_file() and os.access(packaged_bin, os.X_OK):
            verify_runtime_bundle(packaged_dir)
            return self._inspect_binary(
                packaged_bin,
                provenance="packaged_resource",
                manifest_verified=True,
                bundle_integrity_verified=True,
            )

        raise BinaryNotFoundError(
            f"No managed llama.cpp runtime binary found. Expected at '{managed_bin}'. "
            "Arbitrary PATH lookup and third-party host lookups (e.g. Ollama) are disabled for security."
        )

    def _inspect_binary(
        self,
        binary_path: Path,
        provenance: str,
        manifest_verified: bool = False,
        bundle_integrity_verified: bool = False,
    ) -> RuntimeBinaryInfo:
        """Inspect binary to compute SHA-256 byte integrity digest and query version via bounded execution.

        Note on Security & Provenance:
        The SHA-256 digest calculated here proves byte-level integrity (ensuring the executable
        matches expected installed bytes and has not been modified or corrupted). It does NOT
        assert publisher cryptographic authenticity or CA root trust chains, which are verified
        by the update and installation system (Milestone R2 Task R2.13).
        """
        # Compute SHA-256
        hasher = hashlib.sha256()
        with open(binary_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()

        # Probe version via bounded command execution
        version_str = "unknown"
        try:
            res = subprocess.run(
                [str(binary_path), "--version"],
                capture_output=True,
                text=True,
                timeout=2.0,
                shell=False,
            )
            out = (res.stdout or "") + "\n" + (res.stderr or "")
            lines = out.strip().splitlines()
            for line in lines:
                if "version:" in line.lower() or "build" in line.lower() or "llama" in line.lower():
                    version_str = line.strip()
                    break
            if version_str == "unknown" and lines:
                version_str = lines[0].strip()
        except Exception as ex:
            logger.debug("Probing binary version for '%s' encountered error: %s", binary_path, ex)

        return RuntimeBinaryInfo(
            binary_path=str(binary_path.resolve()),
            version=version_str,
            implementation="llama.cpp",
            sha256=digest,
            provenance=provenance,
            manifest_verified=manifest_verified,
            bundle_integrity_verified=bundle_integrity_verified,
        )
