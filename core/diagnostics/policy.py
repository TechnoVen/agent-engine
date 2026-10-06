"""core/diagnostics/policy.py

Redaction and export policies for Agent Engine diagnostics.
Part of Milestone R2 Task R2.12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Set, Tuple


@dataclass
class RedactionPolicy:
    """Configurable redaction and export bounds policy."""

    sensitive_keys: Set[str] = field(
        default_factory=lambda: {
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "auth_token",
            "credential",
            "cookie",
            "set-cookie",
            "private_key",
            "privatekey",
            "jwt",
            "access_token",
            "refresh_token",
            "vault_key",
            "ipc_token",
            "webhook",
            "bearer",
            "session_token",
            "client_secret",
            "master_key",
            "secret_key",
        }
    )

    sensitive_headers: Set[str] = field(
        default_factory=lambda: {
            "authorization",
            "proxy-authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-ipc-token",
            "x-auth-token",
            "x-session-token",
        }
    )

    allowed_env_vars: Set[str] = field(
        default_factory=lambda: {
            "OS",
            "ARCH",
            "PLATFORM",
            "PYTHON_VERSION",
            "PYTHON_PREFIX",
            "LANG",
            "LC_ALL",
            "TZ",
            "SHELL",
            "TERM",
            "PATH",
            "AGENT_ENGINE_ENV",
            "AGENT_ENGINE_VERSION",
            "AGENT_ENGINE_DATA_DIR",
            "AGENT_ENGINE_PORT",
            "AGENT_ENGINE_HOST",
        }
    )

    blocked_file_patterns: List[str] = field(
        default_factory=lambda: [
            "vault.key",
            "ipc.token",
            ".env",
            ".env.*",
            "*.sqlite",
            "*.db",
            "*.sqlite-wal",
            "*.sqlite-shm",
            "checkpoints/*",
            "patch_recovery/*",
            "*.key",
            "*.pem",
            "*.pfx",
            "*.p12",
        ]
    )

    default_placeholder: str = "***REDACTED***"

    # Heuristic regex patterns for token leakage in strings:
    # (pattern_name, regex, replacement)
    regex_rules: List[Tuple[str, re.Pattern[str], str]] = field(
        default_factory=lambda: [
            ("openai_key", re.compile(r"\bsk-[a-zA-Z0-9_\-]{20,}\b"), "***REDACTED***"),
            ("anthropic_key", re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b"), "***REDACTED***"),
            ("google_key", re.compile(r"\bAIzaSy[a-zA-Z0-9_\-]{33}\b"), "***REDACTED***"),
            (
                "jwt_token",
                re.compile(
                    r"\beyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\b"
                ),
                "***REDACTED***",
            ),
            (
                "bearer_auth",
                re.compile(r"\bBearer\s+[a-zA-Z0-9_\-\.\+]{12,}\b", re.IGNORECASE),
                "Bearer ***REDACTED***",
            ),
            (
                "pem_private_key",
                re.compile(
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
                ),
                "***REDACTED***",
            ),
            ("seeded_canary", re.compile(r"\bcanary-[a-zA-Z0-9_\-]{10,}\b"), "***REDACTED***"),
            (
                "key_assignment",
                re.compile(
                    r"(?i)\b(api_key|apikey|secret|token|password)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?"
                ),
                r"\1=***REDACTED***",
            ),
        ]
    )

    max_file_size_bytes: int = 10 * 1024 * 1024
    max_bundle_size_bytes: int = 50 * 1024 * 1024
    max_log_lines: int = 500
