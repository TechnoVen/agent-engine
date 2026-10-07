"""core/inference/validation.py

Model Artifact Pre-Flight Validation for Managed Inference.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Canonical path validation and safe symlink resolution (no broken or circular links).
2. Regular file check with read access verification.
3. Deterministic model format verification: GGUF magic header (b"GGUF") check.
4. Non-empty file constraint (st_size > 0).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("agent_engine.inference.validation")

GGUF_MAGIC_BYTES = b"GGUF"


class ModelValidationError(Exception):
    """Base exception for model artifact validation errors."""


class ModelNotFoundError(ModelValidationError, FileNotFoundError):
    """Raised when the specified model path does not exist."""


class InvalidModelFormatError(ModelValidationError, ValueError):
    """Raised when the model artifact does not match expected format (e.g. GGUF)."""


class ValidatedModelArtifact(BaseModel):
    """Validated model file metadata."""

    canonical_path: str
    size_bytes: int
    format: str = "gguf"
    is_symlink: bool = False


class ModelArtifactValidator:
    """Validates local model artifacts before runtime execution."""

    @classmethod
    def validate(
        cls,
        model_path: str | Path,
        enforce_gguf_format: bool = True,
        allowed_parent_dir: Optional[Path] = None,
    ) -> ValidatedModelArtifact:
        p = Path(model_path).expanduser()

        # 1. Existence check
        if not p.exists():
            raise ModelNotFoundError(f"Model file does not exist: '{p}'")

        is_symlink = p.is_symlink()

        # 2. Resolve canonical target
        try:
            resolved = p.resolve(strict=True)
        except Exception as e:
            raise ModelValidationError(f"Cannot resolve model path '{p}': {e}") from e

        # 3. Regular file check
        if not resolved.is_file():
            raise ModelValidationError(f"Model path '{resolved}' is not a regular file.")

        # 4. Read permission check
        if not os.access(resolved, os.R_OK):
            raise ModelValidationError(
                f"Model file '{resolved}' is not readable by current process."
            )

        # 5. File size non-zero
        size = resolved.stat().st_size
        if size == 0:
            raise ModelValidationError(f"Model file '{resolved}' is empty (0 bytes).")

        # 6. Optional directory jail / boundary check
        if allowed_parent_dir is not None:
            try:
                allowed_res = allowed_parent_dir.resolve(strict=True)
                resolved.relative_to(allowed_res)
            except ValueError:
                raise ModelValidationError(
                    f"Model path '{resolved}' escapes allowed directory '{allowed_parent_dir}'."
                )

        # 7. GGUF magic bytes check
        if enforce_gguf_format:
            try:
                with open(resolved, "rb") as f:
                    magic = f.read(4)
                if magic != GGUF_MAGIC_BYTES:
                    raise InvalidModelFormatError(
                        f"File '{resolved}' has invalid magic bytes {magic!r}; expected GGUF header {GGUF_MAGIC_BYTES!r}."
                    )
            except OSError as ex:
                raise ModelValidationError(
                    f"Failed to read model header from '{resolved}': {ex}"
                ) from ex

        return ValidatedModelArtifact(
            canonical_path=str(resolved),
            size_bytes=size,
            format="gguf",
            is_symlink=is_symlink,
        )
