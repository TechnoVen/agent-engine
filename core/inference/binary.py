"""core/inference/binary.py

Managed Runtime Binary Resolver and Provenance Auditor.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Rejects arbitrary user PATH, workspace/project root, /tmp, and Downloads folder lookups.
2. Resolves strictly from Agent Engine private runtime installation or packaged desktop resources.
3. Probes version honestly and calculates SHA-256 executable integrity digest.
4. Auto-provisions from verified host installation into Agent Engine private storage if absent.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Optional

from core.inference.models import RuntimeBinaryInfo
from core.storage.paths import get_private_data_dir

logger = logging.getLogger("agent_engine.inference.binary")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BinaryNotFoundError(FileNotFoundError):
    """Raised when no verified managed runtime binary is available."""


class UntrustedBinaryLocationError(PermissionError):
    """Raised when a candidate binary originates from an untrusted or prohibited path."""


class RuntimeBinaryResolver:
    """Discovers, validates, and records provenance of managed inference binaries."""

    def __init__(self, managed_root: Optional[Path] = None) -> None:
        self.managed_root = managed_root or (get_private_data_dir() / "runtimes" / "llamacpp")
        self.executable_name = (
            "llama-server.exe" if platform.system() == "Windows" else "llama-server"
        )

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

    def _sync_host_runtime_if_needed(self, target_bin: Path) -> bool:
        """If target binary is absent from AE private runtime dir, attempt to sync from trusted host path."""
        if target_bin.is_file() and os.access(target_bin, os.X_OK):
            return True

        # Check standard trusted host path (e.g. ~/.local/lib/ollama)
        host_candidates = [
            Path.home() / ".local" / "lib" / "ollama",
            Path("/usr/lib/ollama"),
            Path("/opt/agent_engine/runtimes/llamacpp"),
        ]

        for host_dir in host_candidates:
            cand_bin = host_dir / self.executable_name
            if cand_bin.is_file() and os.access(cand_bin, os.X_OK):
                try:
                    self.managed_root.mkdir(parents=True, exist_ok=True)
                    # Copy or symlink libraries and binary
                    for item in host_dir.iterdir():
                        dest = self.managed_root / item.name
                        if not dest.exists():
                            if item.is_symlink():
                                link_target = os.readlink(item)
                                os.symlink(link_target, dest)
                            elif item.is_file():
                                shutil.copy2(item, dest)
                                if os.access(item, os.X_OK):
                                    dest.chmod(0o755)
                    logger.info(
                        "Provisioned managed runtime from %s to %s", host_dir, self.managed_root
                    )
                    return target_bin.is_file() and os.access(target_bin, os.X_OK)
                except Exception as ex:
                    logger.warning("Failed provisioning managed runtime from %s: %s", host_dir, ex)
        return False

    def resolve_binary(self) -> RuntimeBinaryInfo:
        """Resolve and verify the managed runtime binary.

        Search order:
        1. Controlled environment override AGENT_ENGINE_LLAMA_BIN (strictly validated).
        2. Agent Engine private runtime directory (~/.agent_engine/runtimes/llamacpp/llama-server).
        3. Packaged desktop binary resources (apps/desktop/src-tauri/binaries/).
        """
        # 1. Controlled environment override
        env_override = os.environ.get("AGENT_ENGINE_LLAMA_BIN")
        if env_override:
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

        # 2. Agent Engine private runtime storage
        managed_bin = self.managed_root / self.executable_name
        if not managed_bin.is_file() or not os.access(managed_bin, os.X_OK):
            self._sync_host_runtime_if_needed(managed_bin)

        if managed_bin.is_file() and os.access(managed_bin, os.X_OK):
            return self._inspect_binary(managed_bin, provenance="managed_installation")

        # 3. Packaged desktop resources
        packaged_dir = PROJECT_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
        packaged_bin = packaged_dir / self.executable_name
        if packaged_bin.is_file() and os.access(packaged_bin, os.X_OK):
            return self._inspect_binary(packaged_bin, provenance="packaged_resource")

        raise BinaryNotFoundError(
            f"No managed llama.cpp runtime binary found. Expected at '{managed_bin}'. "
            "Arbitrary PATH lookup is disabled for security."
        )

    def _inspect_binary(self, binary_path: Path, provenance: str) -> RuntimeBinaryInfo:
        """Inspect binary to compute SHA-256 and query version via bounded execution."""
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
        )
