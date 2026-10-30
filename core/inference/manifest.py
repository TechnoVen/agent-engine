"""core/inference/manifest.py

Managed Runtime Version, Platform, and Bundle Integrity Manifest.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Exact SHA-256 Comparison: Enforces byte integrity against known platform/version manifests.
   One-byte modified executables or sibling libraries are strictly rejected with ChecksumMismatchError.
2. Sibling Bundle Integrity: Hashing covers the main executable (llama-server) AND all required
   sibling executable code (.so, .dylib, .dll) loaded by the runtime from its managed directory.
3. Unsupported Platform / Architecture Rejection: Wrong platform artifacts raise UnsupportedPlatformError.
4. Unversioned / Unknown Binary Rejection: Binaries without a known manifest entry raise UnversionedRuntimeError.
5. Terminology Discipline: SHA-256 + trusted expected digest guarantees BYTE INTEGRITY,
   NOT publisher cryptographic authenticity. Publisher authenticity and trust roots belong to Milestone R2.13.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import platform
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("agent_engine.inference.manifest")


class RuntimeIntegrityError(PermissionError):
    """Base exception for runtime artifact and bundle integrity failures."""


class ChecksumMismatchError(RuntimeIntegrityError):
    """Raised when an executable or sibling library SHA-256 digest does not match expected manifest."""


class MissingArtifactError(RuntimeIntegrityError):
    """Raised when an expected executable or sibling runtime artifact is missing from the bundle."""


class UnsupportedPlatformError(RuntimeIntegrityError):
    """Raised when an artifact or request specifies an unsupported platform or architecture."""


class UnversionedRuntimeError(RuntimeIntegrityError):
    """Raised when a managed binary does not correspond to any known/supported version manifest."""


class RuntimeArtifactEntry(BaseModel):
    """Single file artifact entry in the runtime bundle manifest."""

    path: str
    sha256: str
    size_bytes: int
    required: bool = True
    is_executable: bool = True


class RuntimeManifest(BaseModel):
    """Versioned integrity manifest for a specific runtime implementation and platform."""

    runtime_name: str = "llamacpp"
    runtime_version: str
    platform_key: str  # e.g., "linux-x86_64", "darwin-arm64", "darwin-x86_64", "windows-x86_64"
    main_executable: str  # e.g., "llama-server" or "llama-server.exe"
    artifacts: Dict[str, RuntimeArtifactEntry] = Field(default_factory=dict)
    symlinks: Dict[str, str] = Field(default_factory=dict)  # symlink_name -> target_relpath
    metadata: Dict[str, Any] = Field(default_factory=dict)


def get_current_platform_key() -> str:
    """Derive canonical platform_key for the current host operating system and CPU architecture."""
    sys_name = platform.system().lower()
    mach = platform.machine().lower()

    if sys_name == "linux":
        os_part = "linux"
    elif sys_name == "darwin":
        os_part = "darwin"
    elif sys_name == "windows":
        os_part = "windows"
    else:
        os_part = sys_name

    if mach in ("x86_64", "amd64"):
        arch_part = "x86_64"
    elif mach in ("arm64", "aarch64"):
        arch_part = "arm64"
    else:
        arch_part = mach

    return f"{os_part}-{arch_part}"


# ==============================================================================
# Built-in Trusted Runtime Manifests
# ==============================================================================

LINUX_X86_64_0_3_0_ARTIFACTS: Dict[str, RuntimeArtifactEntry] = {
    "llama-server": RuntimeArtifactEntry(
        path="llama-server",
        sha256="234b05b2138264f8fb263c3205e85f4c290e8afe5067e280a4f6f90cdac5696b",
        size_bytes=15096,
        required=True,
        is_executable=True,
    ),
    "llama-quantize": RuntimeArtifactEntry(
        path="llama-quantize",
        sha256="208fcacd9b4264cacdc9783efc5b3361ac775372469edc12b48747e6b9c4dbff",
        size_bytes=15096,
        required=False,
        is_executable=True,
    ),
    "libllama-server-impl.so": RuntimeArtifactEntry(
        path="libllama-server-impl.so",
        sha256="b8275be3b108c2704bdf96672f49a9fe7ca00338becaf2d6bc80bc2979357d78",
        size_bytes=2745616,
        required=True,
        is_executable=True,
    ),
    "libllama-common.so.0.3.0": RuntimeArtifactEntry(
        path="libllama-common.so.0.3.0",
        sha256="bfca1591e19207918e9f92dbcd2c3ed14a25e872aff274b87bac9259b050f984",
        size_bytes=4187024,
        required=True,
        is_executable=True,
    ),
    "libllama-quantize-impl.so": RuntimeArtifactEntry(
        path="libllama-quantize-impl.so",
        sha256="a4d0efb151ad11bf35745deaf18c4d598c233051271384001b144b560f8cb544",
        size_bytes=72560,
        required=False,
        is_executable=True,
    ),
    "libllama.so.0.3.0": RuntimeArtifactEntry(
        path="libllama.so.0.3.0",
        sha256="d3f3c9a44f49faff58269cc52496e70685a8115cf7a95e85c78ce4ce399c50ab",
        size_bytes=3901784,
        required=True,
        is_executable=True,
    ),
    "libmtmd.so.0.3.0": RuntimeArtifactEntry(
        path="libmtmd.so.0.3.0",
        sha256="db2352d8c5a47a83806bb329d842353d314c163dfea46c64c94e539ed21cceea",
        size_bytes=1847920,
        required=True,
        is_executable=True,
    ),
    "libggml.so.0.22.0": RuntimeArtifactEntry(
        path="libggml.so.0.22.0",
        sha256="959e2fe38c212fec3596c56947ce2ab09c9ed8ed14e9fa667f25b5a409b86804",
        size_bytes=220832,
        required=True,
        is_executable=True,
    ),
    "libggml-base.so.0.22.0": RuntimeArtifactEntry(
        path="libggml-base.so.0.22.0",
        sha256="a75ddf249fc215d86306a401c7a6ccd2e7242b5a572426c3e7c949586c42eaee",
        size_bytes=821856,
        required=True,
        is_executable=True,
    ),
    "libgomp.so.1.0.0": RuntimeArtifactEntry(
        path="libgomp.so.1.0.0",
        sha256="e985bcbb6b444c2c472de70c331ab101e6de860affa3a20d1d1aecd06d9242e8",
        size_bytes=235072,
        required=True,
        is_executable=True,
    ),
}

LINUX_X86_64_0_3_0_SYMLINKS: Dict[str, str] = {
    "libggml-base.so": "libggml-base.so.0",
    "libggml-base.so.0": "libggml-base.so.0.22.0",
    "libggml.so": "libggml.so.0",
    "libggml.so.0": "libggml.so.0.22.0",
    "libgomp.so.1": "libgomp.so.1.0.0",
    "libllama-common.so": "libllama-common.so.0",
    "libllama-common.so.0": "libllama-common.so.0.3.0",
    "libllama.so": "libllama.so.0",
    "libllama.so.0": "libllama.so.0.3.0",
    "libmtmd.so": "libmtmd.so.0",
    "libmtmd.so.0": "libmtmd.so.0.3.0",
}

MANIFEST_LINUX_X86_64_0_3_0 = RuntimeManifest(
    runtime_name="llamacpp",
    runtime_version="0.3.0",
    platform_key="linux-x86_64",
    main_executable="llama-server",
    artifacts=LINUX_X86_64_0_3_0_ARTIFACTS,
    symlinks=LINUX_X86_64_0_3_0_SYMLINKS,
    metadata={"build_commit": "d222767c7", "upstream_tag": "0.3.0-dev"},
)

# Registry of known runtime manifests keyed by (platform_key, version)
KNOWN_RUNTIME_MANIFESTS: Dict[Tuple[str, str], RuntimeManifest] = {
    ("linux-x86_64", "0.3.0"): MANIFEST_LINUX_X86_64_0_3_0,
    ("linux-x86_64", "0.3.0-dev"): MANIFEST_LINUX_X86_64_0_3_0,
    ("linux-x86_64", "default"): MANIFEST_LINUX_X86_64_0_3_0,
}


def register_runtime_manifest(manifest: RuntimeManifest) -> None:
    """Register or override a runtime manifest (used for test fixtures or dynamic extensions)."""
    KNOWN_RUNTIME_MANIFESTS[(manifest.platform_key, manifest.runtime_version)] = manifest


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file in 64KB chunks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_expected_manifest(
    platform_key: Optional[str] = None,
    version: Optional[str] = None,
) -> RuntimeManifest:
    """Retrieve expected runtime manifest for platform and version."""
    plat = platform_key or get_current_platform_key()
    ver = version or "default"

    manifest = KNOWN_RUNTIME_MANIFESTS.get((plat, ver))
    if manifest:
        return manifest

    # Fallback to default for this platform if specific version not found
    if ver != "default":
        manifest = KNOWN_RUNTIME_MANIFESTS.get((plat, "default"))
        if manifest:
            return manifest

    # If platform is not even in known platforms
    known_platforms = {p for (p, _) in KNOWN_RUNTIME_MANIFESTS.keys()}
    if plat not in known_platforms:
        raise UnsupportedPlatformError(
            f"Unsupported platform/architecture '{plat}'. Supported platforms: {sorted(known_platforms)}"
        )

    raise UnversionedRuntimeError(
        f"No verified runtime manifest for platform '{plat}' version '{ver}'."
    )


def verify_runtime_bundle(
    bundle_dir: Path,
    expected_manifest: Optional[RuntimeManifest] = None,
    platform_key: Optional[str] = None,
    version: Optional[str] = None,
    enforce_bundle: bool = True,
) -> RuntimeManifest:
    """Verify byte-level integrity of the runtime bundle against an expected platform manifest.

    Verification guarantees:
    1. Checks platform compatibility; rejects wrong platform with UnsupportedPlatformError.
    2. Enforces presence of main executable and all required sibling libraries.
    3. Computes SHA-256 for each artifact and asserts exact match against manifest digest.
       Any 1-byte alteration raises ChecksumMismatchError.
    4. Confirms executable permissions on required binaries and libraries.

    Note on Security Model:
    This function guarantees BYTE INTEGRITY against corruption or tampering.
    Publisher cryptographic authenticity, signature verification, and trust roots are
    the responsibility of Milestone R2 Task R2.13.
    """
    if not bundle_dir.is_dir():
        raise MissingArtifactError(f"Runtime bundle directory does not exist: {bundle_dir}")

    manifest = expected_manifest or get_expected_manifest(platform_key, version)

    # 1. Verify main executable
    main_exe_path = bundle_dir / manifest.main_executable
    if not main_exe_path.is_file():
        raise MissingArtifactError(
            f"Main runtime executable '{manifest.main_executable}' missing from bundle '{bundle_dir}'."
        )

    main_entry = manifest.artifacts.get(manifest.main_executable)
    if not main_entry:
        raise UnversionedRuntimeError(
            f"Main executable '{manifest.main_executable}' is unlisted in manifest artifacts."
        )

    actual_main_hash = compute_file_sha256(main_exe_path)
    if actual_main_hash.lower() != main_entry.sha256.lower():
        raise ChecksumMismatchError(
            f"Executable '{manifest.main_executable}' byte integrity verification failed! "
            f"Expected SHA-256 '{main_entry.sha256}', but computed '{actual_main_hash}'. "
            "Artifact rejected due to modification or corruption."
        )

    if main_entry.is_executable and not os.access(main_exe_path, os.X_OK):
        raise RuntimeIntegrityError(
            f"Main executable '{manifest.main_executable}' lacks execute permission."
        )

    # 2. Verify bundle sibling executable code and libraries
    if enforce_bundle:
        for rel_path, entry in manifest.artifacts.items():
            if not entry.required:
                continue
            artifact_path = bundle_dir / rel_path
            if not artifact_path.is_file():
                raise MissingArtifactError(
                    f"Required sibling runtime artifact '{rel_path}' missing from bundle."
                )

            actual_hash = compute_file_sha256(artifact_path)
            if actual_hash.lower() != entry.sha256.lower():
                raise ChecksumMismatchError(
                    f"Sibling runtime artifact '{rel_path}' byte integrity verification failed! "
                    f"Expected SHA-256 '{entry.sha256}', but computed '{actual_hash}'. "
                    "Runtime bundle rejected due to modification or corruption."
                )

            if entry.is_executable and not os.access(artifact_path, os.X_OK):
                raise RuntimeIntegrityError(
                    f"Sibling library/binary '{rel_path}' lacks execute permission."
                )

    logger.debug(
        "Runtime bundle '%s' successfully verified against manifest [%s/%s]",
        bundle_dir,
        manifest.platform_key,
        manifest.runtime_version,
    )
    return manifest
