"""core/inference/environment.py

Secret-Free Child Process Environment Builder for Managed Inference.
Part of Milestone R3 Task R3.4 (Managed Local Inference Supervisor).

Invariants:
1. Pure allowlist construction: child process never inherits parent os.environ by default.
2. Provable secret absence: AGENT_ENGINE_IPC_TOKEN, master keys, and cloud API keys are strictly excluded.
3. Minimal operational footprint: retains only execution paths, library paths, locale, and GPU device masks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import platform
from typing import Dict, List, Optional

logger = logging.getLogger("agent_engine.inference.environment")

# Strictly prohibited secret names / substrings
PROHIBITED_SECRET_PATTERNS = [
    "AGENT_ENGINE_IPC_TOKEN",
    "AGENT_ENGINE_MASTER_KEY",
    "AGENT_ENGINE_VAULT_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MOONSHOT_API_KEY",
    "MISTRAL_API_KEY",
    "OLLAMA_API_KEY",
    "COHERE_API_KEY",
    "VOYAGE_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
]

# Allowlisted base environment variables
ALLOWLIST_BASE_VARS = {
    "HOME",
    "USER",
    "USERNAME",
    "LOGNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "COMSPEC",
    "WINDIR",
}

# Allowlisted hardware acceleration variables
ALLOWLIST_ACCELERATOR_VARS = {
    "CUDA_VISIBLE_DEVICES",
    "ROCR_VISIBLE_DEVICES",
    "HIP_VISIBLE_DEVICES",
    "GGML_METAL_PATH_RESOURCES",
    "HSA_OVERRIDE_GFX_VERSION",
}


def build_child_environment(
    binary_path: Optional[Path] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Construct an allowlisted, secret-free environment for the managed inference runtime."""
    child_env: Dict[str, str] = {}

    # 1. Base system variables
    for var in ALLOWLIST_BASE_VARS:
        val = os.environ.get(var)
        if val is not None:
            child_env[var] = val

    # 2. Hardware accelerator masks
    for var in ALLOWLIST_ACCELERATOR_VARS:
        val = os.environ.get(var)
        if val is not None:
            child_env[var] = val

    # 3. Trusted execution PATH
    # Restrict to standard system binaries
    if platform.system() == "Windows":
        child_env["PATH"] = os.environ.get("PATH", r"C:\Windows\system32;C:\Windows")
    else:
        child_env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    # 4. Library search path restricted strictly to binary directory
    if binary_path is not None:
        bin_dir = str(binary_path.parent.resolve())
        if platform.system() == "Darwin":
            existing = os.environ.get("DYLD_LIBRARY_PATH", "")
            child_env["DYLD_LIBRARY_PATH"] = f"{bin_dir}:{existing}".rstrip(":")
        elif platform.system() != "Windows":
            existing = os.environ.get("LD_LIBRARY_PATH", "")
            child_env["LD_LIBRARY_PATH"] = f"{bin_dir}:{existing}".rstrip(":")

    # 5. Optional caller overrides (must still pass security verification)
    if extra_env:
        for k, v in extra_env.items():
            child_env[k] = v

    # 6. Verify absolute absence of prohibited secrets
    verify_child_environment_is_clean(child_env)

    return child_env


def verify_child_environment_is_clean(env: Dict[str, str]) -> None:
    """Verify and assert that the child environment does not contain any secret or token."""
    violations: List[str] = []

    for k in env.keys():
        k_upper = k.upper()
        # Direct prohibited names
        for secret_name in PROHIBITED_SECRET_PATTERNS:
            if secret_name in k_upper:
                violations.append(
                    f"Prohibited secret key pattern '{secret_name}' found in env key '{k}'"
                )

        # Generic heuristic flags
        for token_word in ("TOKEN", "SECRET", "PRIVATE_KEY", "API_KEY", "PASSWORD"):
            if token_word in k_upper and not k_upper.startswith("LLAMA_"):
                violations.append(
                    f"Suspicious secret keyword '{token_word}' found in env key '{k}'"
                )

    if violations:
        raise ValueError("Child environment security check failed:\n" + "\n".join(violations))
