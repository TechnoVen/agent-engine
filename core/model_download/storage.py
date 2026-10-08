"""core/model_download/storage.py

Agent-Engine-controlled storage, path sanitization, and disk management for models.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).

Invariants:
1. Private Storage Root: Default ~/.agent_engine/models/ (project-independent).
2. Anti-Traversal & Sanitization: Artifact IDs strictly constrained to [a-zA-Z0-9_.-]+.
   Rejects directory traversal (../), slashes, and symlink escapes.
3. Disk Safety: Pre-flight and mid-flight disk space enforcement with safety reserve.
4. Atomic Promotion: os.replace atomic transition from .partial to verified final destination.
5. Quarantine on Mismatch: Corrupted or mismatched files are isolated, never finalized.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
from typing import Optional

from core.model_download.models import DownloadStatus

logger = logging.getLogger("agent_engine.models.download.storage")

DEFAULT_MODELS_DIR = Path.home() / ".agent_engine" / "models"
DEFAULT_DISK_SAFETY_RESERVE_BYTES = 512 * 1024 * 1024  # 512 MiB safety reserve
ARTIFACT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


class StorageSecurityError(Exception):
    """Raised when an artifact ID attempts directory traversal or storage escape."""


class ArtifactConflictError(StorageSecurityError):
    """Raised when destination path already contains a conflicting model artifact."""


class InsufficientDiskSpaceError(Exception):
    """Raised when available storage capacity is insufficient to host requested model."""


def is_override_authorized() -> bool:
    """Check if AGENT_ENGINE_MODELS_DIR override is explicitly authorized."""
    env_mode = os.getenv("AGENT_ENGINE_ENV", "").lower()
    dev_flag = os.getenv("AGENT_ENGINE_DEV_MODE", "").lower()
    allow_flag = os.getenv("AGENT_ENGINE_ALLOW_UNVERIFIED_MODELS_DIR", "").lower()
    return (
        env_mode in ("dev", "development", "test")
        or dev_flag in ("1", "true", "yes")
        or allow_flag in ("1", "true", "yes")
    )


def validate_model_root(candidate: Path, is_env_override: bool = False) -> Path:
    """Canonicalize and strictly validate that model root cannot escape or target sensitive paths."""
    resolved = candidate.expanduser().resolve()
    cand_str = str(resolved)

    # 1. Reject root or top-level system paths
    for sys_root in (
        "/",
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/System",
        "/Library",
        "/proc",
        "/sys",
        "/dev",
    ):
        if cand_str == sys_root or (
            cand_str.startswith(sys_root + "/") and not cand_str.startswith(("/home/", "/Users/"))
        ):
            raise StorageSecurityError(
                f"Model root '{candidate}' targets forbidden system path '{sys_root}'."
            )

    # 2. Reject home directory root directly
    home_res = Path.home().resolve()
    if resolved == home_res:
        raise StorageSecurityError(
            f"Model root '{candidate}' cannot be the user home directory root."
        )

    # 3. Environment override specific restrictions
    if is_env_override:
        # Check operator authority
        if not is_override_authorized():
            raise StorageSecurityError(
                f"Rejected AGENT_ENGINE_MODELS_DIR='{candidate}': model root overrides are strictly "
                "disabled in production mode. Set AGENT_ENGINE_ALLOW_UNVERIFIED_MODELS_DIR=true or "
                "enable dev mode to authorize operator storage overrides."
            )

        # Disallow Downloads or Desktop
        for forbidden_sub in ("Downloads", "Desktop"):
            forbidden_p = (home_res / forbidden_sub).resolve()
            if resolved == forbidden_p or resolved.is_relative_to(forbidden_p):
                raise StorageSecurityError(
                    f"Model root '{candidate}' cannot reside in '{forbidden_sub}'."
                )

        # Disallow /tmp or temporary directories in env override
        if cand_str.startswith(("/tmp", "/var/tmp", "/dev/shm")):
            raise StorageSecurityError(
                f"Model root '{candidate}' cannot reside in temporary directories (/tmp)."
            )

        # Disallow project repository / workspace tree
        try:
            cwd = Path.cwd().resolve()
        except Exception:
            cwd = None

        if cwd and (resolved == cwd or resolved.is_relative_to(cwd)):
            raise StorageSecurityError(
                f"Model root '{candidate}' cannot reside within the project source tree."
            )

    return resolved


class ModelStorageManager:
    """Manages files, paths, and capacity within the Agent Engine managed model directory."""

    def __init__(
        self,
        models_dir: Optional[Path | str] = None,
        safety_reserve_bytes: int = DEFAULT_DISK_SAFETY_RESERVE_BYTES,
    ) -> None:
        if models_dir is not None:
            self._models_dir = validate_model_root(Path(models_dir), is_env_override=False)
        else:
            env_override = os.environ.get("AGENT_ENGINE_MODELS_DIR")
            if env_override:
                self._models_dir = validate_model_root(Path(env_override), is_env_override=True)
            else:
                self._models_dir = DEFAULT_MODELS_DIR.resolve()

        self._safety_reserve_bytes = safety_reserve_bytes
        self.ensure_directory()

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def ensure_directory(self) -> None:
        """Create the managed model root directory securely with restricted 0700 permissions."""
        self._models_dir.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "posix":
                self._models_dir.chmod(0o700)
        except OSError:
            pass

    def sanitize_artifact_id(self, artifact_id: str) -> str:
        """Enforce strict naming rules and reject path traversal attempts."""
        if not artifact_id or not isinstance(artifact_id, str):
            raise StorageSecurityError("Artifact ID cannot be empty.")

        # Reject path separators and null bytes explicitly
        if "/" in artifact_id or "\\" in artifact_id or "\0" in artifact_id:
            raise StorageSecurityError(
                f"Artifact ID '{artifact_id}' contains forbidden path separator or null byte."
            )

        if artifact_id.startswith(".") or ".." in artifact_id:
            raise StorageSecurityError(
                f"Artifact ID '{artifact_id}' contains relative directory traversal elements."
            )

        if not ARTIFACT_ID_PATTERN.match(artifact_id):
            raise StorageSecurityError(
                f"Artifact ID '{artifact_id}' contains invalid characters. Must match [a-zA-Z0-9_.-]+."
            )

        return artifact_id

    def get_final_path(self, artifact_id: str) -> Path:
        """Get canonical destination path for a verified model artifact."""
        clean_id = self.sanitize_artifact_id(artifact_id)
        final_p = (self._models_dir / clean_id).resolve()
        self._verify_within_root(final_p)
        return final_p

    def get_partial_path(self, artifact_id: str) -> Path:
        """Get canonical staging path for an in-flight or paused model download."""
        clean_id = self.sanitize_artifact_id(artifact_id)
        partial_p = (self._models_dir / f"{clean_id}.partial").resolve()
        self._verify_within_root(partial_p)
        return partial_p

    def get_meta_path(self, artifact_id: str) -> Path:
        """Get canonical path for persistence of artifact download metadata."""
        clean_id = self.sanitize_artifact_id(artifact_id)
        meta_p = (self._models_dir / f"{clean_id}.meta.json").resolve()
        self._verify_within_root(meta_p)
        return meta_p

    def _verify_within_root(self, path: Path) -> None:
        """Verify resolved path stays strictly within the managed model root."""
        try:
            path.relative_to(self._models_dir)
        except ValueError:
            raise StorageSecurityError(
                f"Path '{path}' escapes the managed model root '{self._models_dir}'."
            )

    def check_disk_capacity(
        self,
        required_bytes: int,
        existing_partial_bytes: int = 0,
    ) -> None:
        """Check available disk space, accounting for required bytes and safety reserve."""
        net_needed = max(0, required_bytes - existing_partial_bytes)
        try:
            usage = shutil.disk_usage(self._models_dir)
            available = usage.free
        except Exception as e:
            logger.warning("Failed to inspect disk usage: %s", e)
            return

        needed_total = net_needed + self._safety_reserve_bytes
        if available < needed_total:
            avail_gib = round(available / (1024**3), 2)
            need_gib = round(net_needed / (1024**3), 2)
            res_gib = round(self._safety_reserve_bytes / (1024**3), 2)
            raise InsufficientDiskSpaceError(
                f"Insufficient disk space in '{self._models_dir}': "
                f"available {avail_gib} GiB, but requires {need_gib} GiB + {res_gib} GiB safety reserve."
            )

    def atomic_promote(
        self,
        partial_path: Path,
        final_path: Path,
        expected_sha256: Optional[str] = None,
    ) -> None:
        """Atomically promote verified partial file to final destination without silently clobbering existing files."""
        if not partial_path.exists():
            raise FileNotFoundError(f"Partial file does not exist: {partial_path}")

        # 1. Immediate destination-state check
        if final_path.exists():
            if expected_sha256:
                import hashlib

                hasher = hashlib.sha256()
                with open(final_path, "rb") as ff:
                    while chunk := ff.read(64 * 1024):
                        hasher.update(chunk)
                if hasher.hexdigest().lower() == expected_sha256.lower().strip():
                    logger.info(
                        "Final artifact %s already exists with matching SHA-256; safely reusing.",
                        final_path.name,
                    )
                    try:
                        os.unlink(partial_path)
                    except OSError:
                        pass
                    return
            raise ArtifactConflictError(
                f"Cannot promote model artifact: destination '{final_path}' already exists and differs."
            )

        # 2. Atomic no-clobber final placement using os.link on POSIX
        linked = False
        if hasattr(os, "link"):
            try:
                os.link(partial_path, final_path)
                try:
                    os.unlink(partial_path)
                except OSError:
                    pass
                linked = True
            except FileExistsError:
                # Race condition: destination created concurrently
                if expected_sha256:
                    import hashlib

                    hasher = hashlib.sha256()
                    with open(final_path, "rb") as ff:
                        while chunk := ff.read(64 * 1024):
                            hasher.update(chunk)
                    if hasher.hexdigest().lower() == expected_sha256.lower().strip():
                        try:
                            os.unlink(partial_path)
                        except OSError:
                            pass
                        return
                raise ArtifactConflictError(
                    f"Concurrent conflict: destination '{final_path}' was created during promotion."
                )
            except OSError:
                pass

        if not linked:
            if final_path.exists():
                raise ArtifactConflictError(
                    f"Destination '{final_path}' already exists; refusing to clobber."
                )
            os.replace(partial_path, final_path)

        # 3. Ensure restricted file mode 0o600 on final artifact
        try:
            if os.name == "posix":
                final_path.chmod(0o600)
        except OSError:
            pass

        # 4. Flush parent directory metadata on POSIX
        if hasattr(os, "sync") and os.name == "posix":
            try:
                parent_fd = os.open(str(self._models_dir), os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except Exception as e:
                logger.debug("Parent dir fsync skipped: %s", e)

    def quarantine_corrupted_partial(self, partial_path: Path) -> Optional[Path]:
        """Isolate a corrupted or checksum-mismatched partial file."""
        if not partial_path.exists():
            return None
        timestamp = int(time.time())
        quarantine_path = partial_path.with_name(f"{partial_path.name}.corrupt_{timestamp}")
        try:
            os.replace(partial_path, quarantine_path)
            try:
                if os.name == "posix":
                    quarantine_path.chmod(0o600)
            except OSError:
                pass
            logger.warning("Quarantined corrupt partial to %s", quarantine_path)
            return quarantine_path
        except Exception as e:
            logger.error("Failed to quarantine partial file %s: %s", partial_path, e)
            return None

    def save_metadata(self, status: DownloadStatus) -> None:
        """Persist download status metadata to .meta.json file with 0600 permissions and fsync."""
        meta_p = self.get_meta_path(status.artifact_id)
        temp_p = meta_p.with_suffix(".tmp")
        try:
            with open(temp_p, "w", encoding="utf-8") as f:
                json.dump(status.model_dump(), f, indent=2)
                f.flush()
                if hasattr(os, "fsync"):
                    os.fsync(f.fileno())
            try:
                if os.name == "posix":
                    temp_p.chmod(0o600)
            except OSError:
                pass
            os.replace(temp_p, meta_p)
            if hasattr(os, "sync") and os.name == "posix":
                try:
                    parent_fd = os.open(str(self._models_dir), os.O_RDONLY)
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                except Exception:
                    pass
        except Exception as e:
            logger.error("Failed to save metadata for %s: %s", status.artifact_id, e)

    def load_metadata(self, artifact_id: str) -> Optional[DownloadStatus]:
        """Load persisted download status from .meta.json file."""
        meta_p = self.get_meta_path(artifact_id)
        if not meta_p.exists():
            return None
        try:
            with open(meta_p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DownloadStatus.model_validate(data)
        except Exception as e:
            logger.warning("Failed to read metadata file %s: %s", meta_p, e)
            return None
