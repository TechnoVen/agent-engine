"""tests/test_r2_diagnostics_redaction.py

Comprehensive test suite for Milestone R2 Task R2.12 Central Diagnostics Redaction and Export Policy (S1).
Covers CTO Review Items 3-14:
1. Central diagnostics architecture (models, policy, redactor, exporter).
2. Compressed-archive canary verification (reopening with archive parser, enumerating and decompressing every member, secret occurrences = 0).
3. Archive member security (rejecting absolute paths, path traversal, non-regular members, normalizing uid/gid/mtime).
4. Manifest hash scope & acyclic verification (integrity metadata over canonical members, manifest excluded from member hashes).
5. SecretReference diagnostic minimization (default minimized, exact reference opt-in only).
6. Central diagnostic egress inventory (classifying surfaces, routing through central redactor).
7. Fail-safe on redaction & serialization errors (malicious __repr__/__str__, recursion cycles, depth limits, unsupported objects).
8. Bounded diagnostic collection (string truncation, log line/byte limits, private store exclusion).
9. Path minimization order & coverage (known-root mapping before regexes, POSIX & Windows, exceptions, logs, argv, preserving URLs).
10. Canonical seeded-canary production export artifact verification across 17 distinct canary injection points.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
from typing import Any, Dict, List, Optional
import zipfile

import pytest

from core.diagnostics.exporter import (
    DIAGNOSTIC_EGRESS_INVENTORY,
    DiagnosticsExporter,
    is_safe_member_name,
)
from core.diagnostics.models import (
    EgressClassification,
    RedactionReport,
)
from core.diagnostics.policy import RedactionPolicy
from core.diagnostics.redactor import DiagnosticsRedactor
from core.security.secrets import SecretReference, SecretValue


class MaliciousReprObject:
    """Class whose __repr__ attempts to leak secrets or raise an exception."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def __repr__(self) -> str:
        return f"MaliciousReprObject(LEAKED_SECRET={self._secret})"


class MaliciousStrObject:
    """Class whose __str__ raises an error if invoked."""

    def __str__(self) -> str:
        raise RuntimeError("Malicious __str__ trap triggered!")


class RecursiveObject:
    """Self-referencing object to test cycle detection."""

    def __init__(self) -> None:
        self.child: Optional[RecursiveObject] = None


class MockStorageWithLogs:
    """Mock storage providing audit logs for diagnostics export."""

    def __init__(self, logs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.name = "MockAuditStorage"
        self._logs = logs or []

    def list_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._logs[:limit]


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    p = tmp_path / "project_alpha"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def private_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agent_engine_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def redactor(project_root: Path, private_data_dir: Path) -> DiagnosticsRedactor:
    return DiagnosticsRedactor(
        project_root=project_root,
        data_dir=private_data_dir,
    )


# ============================================================================
# 1. Structural Value Object Isolation & SecretReference Minimization (Layer 1 & Item 7)
# ============================================================================


def test_secret_value_omitted_without_revealing(redactor: DiagnosticsRedactor) -> None:
    """SecretValue container is scrubbed at egress boundary without revealing its plaintext."""
    secret = SecretValue("super-secret-password-12345")
    redacted, report = redactor.redact(secret)

    assert redacted == "***REDACTED***" or redacted == "[REDACTED_SECRET_VALUE]"
    assert "super-secret-password-12345" not in str(redacted)
    assert report.redactions_count >= 1
    assert "secret_value_omitted" in report.redacted_patterns


def test_secret_reference_minimized_by_default(redactor: DiagnosticsRedactor) -> None:
    """SecretReference is minimized by default in shareable diagnostics (CTO Review Item 7)."""
    ref = SecretReference(
        provider="openai",
        name="api_key",
        scope="project",
        project_id="proj_100",
    )
    redacted, report = redactor.redact(ref)

    assert isinstance(redacted, dict)
    assert redacted == {"credential_configured": True, "provider": "openai"}
    assert report.references_minimized_count >= 1
    # Ensure sensitive internal name and project_id are NOT leaked
    assert "api_key" not in str(redacted)
    assert "proj_100" not in str(redacted)


def test_secret_reference_preserved_when_explicitly_configured(
    project_root: Path, private_data_dir: Path
) -> None:
    """SecretReference is preserved as structured public identifier when policy allows (CTO Review Item 7)."""
    policy = RedactionPolicy(include_exact_secret_references=True)
    opt_in_redactor = DiagnosticsRedactor(
        policy=policy, project_root=project_root, data_dir=private_data_dir
    )
    ref = SecretReference(
        provider="openai",
        name="api_key",
        scope="project",
        project_id="proj_100",
    )
    redacted, report = opt_in_redactor.redact(ref)

    assert isinstance(redacted, dict)
    assert "secret_reference" in redacted
    ref_info = redacted["secret_reference"]
    assert ref_info["provider"] == "openai"
    assert ref_info["name"] == "api_key"
    assert ref_info["project_id"] == "proj_100"
    assert len(report.preserved_references) >= 1


def test_nested_secret_structures_handled_correctly(redactor: DiagnosticsRedactor) -> None:
    """Nested dictionaries containing SecretValue and SecretReference are properly isolated."""
    data = {
        "app": "AgentEngine",
        "auth": {
            "credentials": SecretValue("confidential_token_xyz"),
            "ref": SecretReference(provider="anthropic", name="main_key"),
        },
    }
    redacted, report = redactor.redact(data)

    assert redacted["app"] == "AgentEngine"
    assert "confidential_token_xyz" not in str(redacted)
    assert redacted["auth"]["ref"] == {"credential_configured": True, "provider": "anthropic"}
    assert report.redactions_count >= 1


# ============================================================================
# 2. Key-Based and HTTP Header Scrubbing (Layer 2)
# ============================================================================


def test_sensitive_dictionary_keys_scrubbed(redactor: DiagnosticsRedactor) -> None:
    """Dictionary keys matching sensitive keywords have their values redacted."""
    payload = {
        "username": "alice",
        "password": "alice_plain_password",
        "access_token": "token_12345678",
        "client_secret": "secret_abc_987",
        "api_key": "raw_api_key_here",
        "nested": {"db_password": "database_pass_word"},
    }
    redacted, report = redactor.redact(payload)

    assert redacted["username"] == "alice"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["access_token"] == "***REDACTED***"
    assert redacted["client_secret"] == "***REDACTED***"
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["nested"]["db_password"] == "***REDACTED***"
    assert report.redactions_count >= 5


def test_sensitive_http_headers_scrubbed(redactor: DiagnosticsRedactor) -> None:
    """HTTP headers matching sensitive header names are scrubbed."""
    headers = {
        "User-Agent": "AgentEngine/0.1.0",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token.sig",
        "Cookie": "session=secret_session_id_456; other=123",
        "X-API-Key": "my_api_key_header",
        "X-IPC-Token": "ipc_token_xyz",
    }
    redacted, report = redactor.redact(headers)

    assert redacted["User-Agent"] == "AgentEngine/0.1.0"
    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["Cookie"] == "***REDACTED***"
    assert redacted["X-API-Key"] == "***REDACTED***"
    assert redacted["X-IPC-Token"] == "***REDACTED***"
    assert report.redactions_count >= 4


# ============================================================================
# 3. Environment Variable Scrubbing (Layer 3)
# ============================================================================


def test_environment_variables_scrubbed_strict_allowlist(redactor: DiagnosticsRedactor) -> None:
    """Only allowlisted environment variables are preserved; secret env vars are excluded."""
    env = {
        "OS": "Linux",
        "ARCH": "x86_64",
        "PATH": "/usr/local/bin:/usr/bin",
        "OPENAI_API_KEY": "sk-secret-openai-api-key-1234567890",
        "ANTHROPIC_API_KEY": "sk-ant-secret-anthropic-key-1234567890",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    }
    scrubbed = redactor.redact_env(env)

    assert "OS" in scrubbed
    assert "ARCH" in scrubbed
    assert "PATH" in scrubbed
    assert "OPENAI_API_KEY" not in scrubbed
    assert "ANTHROPIC_API_KEY" not in scrubbed
    assert "DATABASE_URL" not in scrubbed
    assert "AWS_SECRET_ACCESS_KEY" not in scrubbed


# ============================================================================
# 4. Pattern / Regex Token Heuristics (Layer 4)
# ============================================================================


def test_token_regex_heuristics_scrub_string_leaks(redactor: DiagnosticsRedactor) -> None:
    """Regex patterns catch OpenAI, Anthropic, Gemini, JWT, Bearer, PEM, query param, and URI passwords."""
    raw_text = (
        "Logs from worker: "
        "OpenAI: sk-abcdefghijklmnopqrstuvwxyz1234567890 "
        "Anthropic: sk-ant-abcdefghijklmnopqrstuvwxyz1234567890 "
        "Google: AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q "
        "JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0 "
        "Bearer: Bearer mySecretBearerToken123456 "
        "URI: postgresql://admin:super_secret_pw@db.local:5432/main "
        "Query: https://api.service.com/v1?api_key=secret_param_token_999&user=bob "
        "Assignment: token='token_assigned_value_12345' "
        "PEM: -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAz6Q...-----END RSA PRIVATE KEY-----"
    )
    redacted = redactor.redact_text(raw_text)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "AIzaSyA1B2C3D4E5F6G7H8I9" not in redacted
    assert "dozjgNryP4J3jVmNHl0" not in redacted
    assert "mySecretBearerToken123456" not in redacted
    assert "super_secret_pw" not in redacted
    assert "secret_param_token_999" not in redacted
    assert "token_assigned_value_12345" not in redacted
    assert "MIIEowIBAAKCAQEA" not in redacted
    assert "***REDACTED***" in redacted


# ============================================================================
# 5. Fail-Safe on Redaction/Serialization Errors (Item 9)
# ============================================================================


def test_fail_safe_on_malicious_repr_and_str(redactor: DiagnosticsRedactor) -> None:
    """Malicious __repr__ and __str__ methods are never invoked; unknown objects return safe type markers."""
    secret = "SECRET_CANARY_IN_REPR_999"
    obj_repr = MaliciousReprObject(secret)
    obj_str = MaliciousStrObject()

    # Neither should crash, and secret in repr must NEVER appear
    redacted_repr, report1 = redactor.redact(obj_repr)
    assert redacted_repr == {"<unserializable_type>": "MaliciousReprObject"}
    assert secret not in str(redacted_repr)
    assert report1.unserializable_objects_omitted >= 1

    redacted_str, report2 = redactor.redact(obj_str)
    assert redacted_str == {"<unserializable_type>": "MaliciousStrObject"}
    assert report2.unserializable_objects_omitted >= 1


def test_fail_safe_on_recursive_and_cyclic_structures(redactor: DiagnosticsRedactor) -> None:
    """Cyclic and self-referencing dictionary/object structures do not cause infinite recursion."""
    cyclic_dict: Dict[str, Any] = {"name": "root"}
    cyclic_dict["self"] = cyclic_dict

    redacted, report = redactor.redact(cyclic_dict)
    assert redacted["name"] == "root"
    assert "<recursion_cycle>" in str(redacted["self"])


def test_fail_safe_on_deeply_nested_structures_depth_limit(redactor: DiagnosticsRedactor) -> None:
    """Deeply nested structures exceeding max_recursion_depth are safely bounded."""
    curr: Dict[str, Any] = {"depth": 0}
    root = curr
    for d in range(1, 50):
        next_dict: Dict[str, Any] = {"depth": d}
        curr["child"] = next_dict
        curr = next_dict

    redacted, report = redactor.redact(root)
    assert report.recursion_depth_exceeded_count >= 1
    # Check that depth limit marker is reached
    assert "<depth_limit_exceeded>" in str(redacted)


def test_fail_safe_on_unsupported_custom_objects(redactor: DiagnosticsRedactor) -> None:
    """Custom objects without dictionary serialization produce safe type markers without leaking."""

    class CustomOpaque:
        pass

    redacted, report = redactor.redact(CustomOpaque())
    assert redacted == {"<unserializable_type>": "CustomOpaque"}
    assert report.unserializable_objects_omitted == 1


# ============================================================================
# 6. Path Minimization Order & Coverage (Item 11)
# ============================================================================


def test_path_minimization_order_and_placeholders(
    redactor: DiagnosticsRedactor, project_root: Path, private_data_dir: Path
) -> None:
    """Host paths are minimized to standardized placeholders, evaluating known roots before generic regexes."""
    f_proj = project_root / "src" / "worker.py"
    f_data = private_data_dir / "sessions" / "s1.db"
    f_home = Path.home() / ".config" / "app" / "config.toml"

    assert redactor._minimize_path(str(f_proj), RedactionReport()) == "<PROJECT>/src/worker.py"
    assert redactor._minimize_path(str(f_data), RedactionReport()) == "<DATA_DIR>/sessions/s1.db"
    assert (
        redactor._minimize_path(str(f_home), RedactionReport()) == "<HOME>/.config/app/config.toml"
    )


def test_windows_path_minimization(tmp_path: Path) -> None:
    """Path minimization handles Windows backslash paths correctly."""
    win_project = Path("C:/Users/TestUser/agent_engine")
    redactor_win = DiagnosticsRedactor(project_root=win_project)

    win_backslash_path = "C:\\Users\\TestUser\\agent_engine\\src\\main.py"
    minimized = redactor_win._minimize_path(win_backslash_path, RedactionReport())
    assert "<PROJECT>" in minimized
    assert "C:\\Users\\TestUser" not in minimized


def test_path_minimization_inside_exceptions_logs_and_argv(
    redactor: DiagnosticsRedactor, project_root: Path
) -> None:
    """Path minimization applies inside exception strings, logs, and argv structures."""
    script_path = str(project_root / "scripts" / "run.py")

    # Inside exception string
    exc_text = f"FileNotFoundError: [Errno 2] No such file or directory: '{script_path}'"
    redacted_exc = redactor.redact_text(exc_text)
    assert "<PROJECT>/scripts/run.py" in redacted_exc
    assert str(project_root) not in redacted_exc

    # Inside structured argv
    argv = ["python3", script_path, "--verbose"]
    redacted_argv, _ = redactor.redact(argv)
    assert redacted_argv[1] == "<PROJECT>/scripts/run.py"


def test_url_paths_not_rewritten_as_filesystem_paths(redactor: DiagnosticsRedactor) -> None:
    """Benign URL paths are not rewritten or corrupted as filesystem paths (CTO Review Item 11)."""
    url = "https://api.openai.com/v1/chat/completions"
    redacted = redactor.redact_text(url)
    assert redacted == url


# ============================================================================
# 7. Collection Bounds & Private Store Exclusion (Item 10)
# ============================================================================


def test_private_stores_unconditionally_blocked(project_root: Path) -> None:
    """Exporter unconditionally refuses to include private keys, tokens, .env, DBs, or checkpoints."""
    exporter = DiagnosticsExporter(project_root=project_root)

    assert exporter.is_path_blocked("vault.key") is True
    assert exporter.is_path_blocked("ipc.token") is True
    assert exporter.is_path_blocked(".env") is True
    assert exporter.is_path_blocked(".env.production") is True
    assert exporter.is_path_blocked("database.sqlite") is True
    assert exporter.is_path_blocked("app.db") is True
    assert exporter.is_path_blocked("app.sqlite-wal") is True
    assert exporter.is_path_blocked("checkpoints/chk-1/backup.bin") is True
    assert exporter.is_path_blocked("patch_recovery/patch.bin") is True
    assert exporter.is_path_blocked("server.key") is True

    # Safe files must be allowed
    assert exporter.is_path_blocked("system_info.json") is False
    assert exporter.is_path_blocked("README.md") is False


def test_collection_bounds_string_and_log_truncation(project_root: Path) -> None:
    """Collection bounds truncate excessive strings and log sizes (CTO Review Item 10)."""
    policy = RedactionPolicy(max_string_length=100, max_log_lines=5)
    redactor_bounded = DiagnosticsRedactor(policy=policy, project_root=project_root)

    # String truncation
    huge_str = "A" * 500
    redacted_str, rep = redactor_bounded.redact(huge_str)
    assert len(redacted_str) < 200
    assert "...[TRUNCATED]" in redacted_str
    assert rep.bytes_truncated_count >= 1

    # Log truncation
    many_logs = [
        {"id": f"log-{i}", "timestamp": "2026-10-01", "tool_name": "bash", "decision": "allow"}
        for i in range(50)
    ]
    storage = MockStorageWithLogs(logs=many_logs)
    exporter = DiagnosticsExporter(
        redactor=redactor_bounded, storage=storage, project_root=project_root
    )
    logs_text = exporter.gather_redacted_logs(RedactionReport())
    # Header lines + max 5 log entries
    assert logs_text.count("ID=log-") <= 5


# ============================================================================
# 8. Archive Member Security & Normalized Metadata (Item 5)
# ============================================================================


def test_archive_member_security_rejects_unsafe_names(project_root: Path) -> None:
    """Archive member validation rejects absolute paths, path traversal, and special characters."""
    assert is_safe_member_name("system_info.json") is True
    assert is_safe_member_name("logs/debug.txt") is True

    # Traversal and absolute rejected
    assert is_safe_member_name("/etc/passwd") is False
    assert is_safe_member_name("../escape.txt") is False
    assert is_safe_member_name("subdir/../../escape.txt") is False
    assert is_safe_member_name("C:\\Windows\\System32") is False
    assert is_safe_member_name("") is False


def test_archive_member_metadata_normalized(project_root: Path) -> None:
    """Archive members have normalized uid/gid/mtime and strict regular file types (CTO Review Item 5)."""
    exporter = DiagnosticsExporter(project_root=project_root)
    bundle = exporter.export_bundle(format="tar.gz")

    with tarfile.open(fileobj=io.BytesIO(bundle.payload_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Normalized metadata
            assert member.uid == 0
            assert member.gid == 0
            assert member.uname == ""
            assert member.gname == ""
            assert member.mtime == 1700000000
            assert member.type == tarfile.REGTYPE
            assert member.mode == 0o600
            # Member name is safe
            assert is_safe_member_name(member.name) is True


# ============================================================================
# 9. Acyclic Manifest Hash Scope & Integrity Verification (Item 6)
# ============================================================================


def test_manifest_acyclic_hash_scope_and_integrity_verification(project_root: Path) -> None:
    """Manifest provides acyclic integrity verification over canonical exported members."""
    exporter = DiagnosticsExporter(project_root=project_root)
    bundle = exporter.export_bundle(format="zip")

    manifest = bundle.manifest
    assert manifest.hash_scope == "canonical_exported_members"
    assert manifest.hash_algorithm == "sha256"
    assert manifest.export_format_version == 1

    # Invariant: manifest.json MUST NOT be in member_hashes (acyclic integrity!)
    assert "manifest.json" not in manifest.member_hashes
    assert "system_info.json" in manifest.member_hashes
    assert "config_redacted.json" in manifest.member_hashes

    # Unpack members and verify integrity
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        members_dict = {name: zf.read(name) for name in zf.namelist()}

    assert manifest.verify_member_integrity(members_dict) is True


def test_manifest_detects_tampered_member(project_root: Path) -> None:
    """Tampering with an archive member fails manifest integrity verification."""
    exporter = DiagnosticsExporter(project_root=project_root)
    bundle = exporter.export_bundle(format="zip")

    manifest = bundle.manifest
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        members_dict = {name: zf.read(name) for name in zf.namelist()}

    # Tamper with one member's bytes
    members_dict["system_info.json"] = b'{"tampered": true}'
    assert manifest.verify_member_integrity(members_dict) is False


# ============================================================================
# 10. Central Diagnostic Egress Inventory Enforcement (Item 8)
# ============================================================================


def test_diagnostic_egress_inventory_enforcement(project_root: Path) -> None:
    """Every outward diagnostic surface is registered and routes through central policy."""
    exporter = DiagnosticsExporter(project_root=project_root)

    # 1. Verify classifications
    assert (
        DIAGNOSTIC_EGRESS_INVENTORY["diagnostic_export"] == EgressClassification.SHAREABLE_REDACTED
    )
    assert (
        DIAGNOSTIC_EGRESS_INVENTORY["health_support_report"]
        == EgressClassification.SHAREABLE_REDACTED
    )
    assert DIAGNOSTIC_EGRESS_INVENTORY["vault_storage"] == EgressClassification.NOT_EXPORTABLE
    assert DIAGNOSTIC_EGRESS_INVENTORY["internal_sqlite_raw"] == EgressClassification.INTERNAL_ONLY

    # 2. Shareable surfaces route through central redactor
    payload = {"status": "ok", "api_key": "sk-secret-token-1234567890"}
    sanitized = exporter.sanitize_for_egress("diagnostic_export", payload)
    assert sanitized["status"] == "ok"
    assert sanitized["api_key"] == "***REDACTED***"

    # 3. NOT_EXPORTABLE and INTERNAL_ONLY surfaces raise PermissionError
    with pytest.raises(PermissionError, match="NOT_EXPORTABLE"):
        exporter.sanitize_for_egress("vault_storage", payload)

    with pytest.raises(PermissionError, match="INTERNAL_ONLY"):
        exporter.sanitize_for_egress("internal_sqlite_raw", payload)


# ============================================================================
# 11. Canonical Decompressed Member Canary Verification (Items 4 & 12)
# ============================================================================


def test_canonical_decompressed_member_canary_scan_zip(
    project_root: Path, private_data_dir: Path
) -> None:
    """Reopen zip with archive parser, decompress every member, and scan decompressed bytes for 0 canary leaks."""
    canary = "canary-zip-secret-token-998877"
    custom_files = {
        "custom_notes.txt": f"Important note with secret {canary}",
        "custom_data.json": {"auth": canary, "safe": "regular_value"},
    }

    redactor = DiagnosticsRedactor(project_root=project_root, data_dir=private_data_dir)
    exporter = DiagnosticsExporter(redactor=redactor, project_root=project_root)
    bundle = exporter.export_bundle(format="zip", custom_files=custom_files)

    # Canonical Verification Flow (CTO Review Item 4):
    # 1. Reopen using zipfile archive parser
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        # 2. Enumerate every member
        infolist = zf.infolist()
        assert len(infolist) >= 5

        for zinfo in infolist:
            # 3. Validate safe member metadata
            assert is_safe_member_name(zinfo.filename) is True
            assert not zinfo.filename.startswith("/")
            assert ".." not in zinfo.filename
            assert canary not in zinfo.filename

            # 4. Decompress / read regular member bytes
            decompressed_bytes = zf.read(zinfo.filename)

            # 5. Scan decompressed bytes: secret occurrences = 0!
            assert canary.encode("utf-8") not in decompressed_bytes
            decompressed_str = decompressed_bytes.decode("utf-8", errors="replace")
            assert canary not in decompressed_str


def test_canonical_decompressed_member_canary_scan_tar_gz(
    project_root: Path, private_data_dir: Path
) -> None:
    """Reopen tar.gz with archive parser, decompress every member, and scan decompressed bytes for 0 canary leaks."""
    canary = "canary-tar-secret-token-554433"
    custom_files = {
        "tar_notes.txt": f"Important tar note with secret {canary}",
        "tar_data.json": {"token": canary},
    }

    redactor = DiagnosticsRedactor(project_root=project_root, data_dir=private_data_dir)
    exporter = DiagnosticsExporter(redactor=redactor, project_root=project_root)
    bundle = exporter.export_bundle(format="tar.gz", custom_files=custom_files)

    with tarfile.open(fileobj=io.BytesIO(bundle.payload_bytes), mode="r:gz") as tar:
        members = tar.getmembers()
        assert len(members) >= 5

        for member in members:
            assert is_safe_member_name(member.name) is True
            assert member.type == tarfile.REGTYPE
            assert canary not in member.name

            f = tar.extractfile(member)
            assert f is not None
            decompressed_bytes = f.read()

            assert canary.encode("utf-8") not in decompressed_bytes
            decompressed_str = decompressed_bytes.decode("utf-8", errors="replace")
            assert canary not in decompressed_str


# ============================================================================
# 12. Egress Boundary Invariant (Internal Storage Unmutated)
# ============================================================================


def test_egress_boundary_leaves_internal_storage_unmutated(project_root: Path) -> None:
    """Exporting diagnostics does NOT mutate the raw internal storage records."""
    original_tool_args = {"auth_token": "secret_internal_token_12345"}
    mock_storage = MockStorageWithLogs(
        logs=[
            {
                "id": "audit-egress",
                "timestamp": "2026-10-03T00:00:00Z",
                "tool_name": "query",
                "decision": "allow",
                "risk_level": "high",
                "tool_args": original_tool_args,
                "result": {"status": "ok"},
            }
        ]
    )

    exporter = DiagnosticsExporter(storage=mock_storage, project_root=project_root)
    bundle = exporter.export_bundle(format="zip")

    # Internal storage log tool_args must still have original_token unmutated!
    internal_log = mock_storage.list_audit_logs()[0]
    assert internal_log["tool_args"]["auth_token"] == "secret_internal_token_12345"

    # But exported bundle must have it redacted!
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        logs_text = zf.read("logs_redacted.txt").decode("utf-8")
        assert "secret_internal_token_12345" not in logs_text
        assert "***REDACTED***" in logs_text


# ============================================================================
# 13. Comprehensive Seeded-Canary Production Export Artifact (Item 12)
# ============================================================================


def test_production_seeded_canary_export_artifact_comprehensive(
    project_root: Path, private_data_dir: Path
) -> None:
    """Canonical Roadmap Evidence Artifact: Seed canaries across all 17 sensitive vectors and verify 0 leaks.

    Vectors tested:
    1. API key
    2. Bearer token
    3. Password
    4. IPC token
    5. Vault key
    6. HTTP Authorization
    7. Cookie / Set-Cookie
    8. URL query credential
    9. Connection URI
    10. Environment variable
    11. Nested dict/list
    12. Provider exception
    13. Tool stderr
    14. Sandbox stderr
    15. Checkpoint attempted metadata
    16. Patch attempted metadata
    17. Malicious repr/str object
    """
    canaries = {
        "api_key": "sk-canary-key-11223344556677889900",
        "bearer_token": "canary-bearer-22334455667788990011",
        "password": "canary-pwd-33445566778899001122",
        "ipc_token": "canary-ipc-44556677889900112233",
        "vault_key": "canary-vault-55667788990011223344",
        "auth_header": "canary-auth-66778899001122334455",
        "cookie": "canary-cookie-77889900112233445566",
        "url_query": "canary-query-88990011223344556677",
        "conn_uri": "canary-conn-99001122334455667788",
        "env_var": "canary-env-00112233445566778899",
        "nested": "canary-nested-12121212121212121212",
        "prov_exc": "canary-exc-23232323232323232323",
        "tool_stderr": "canary-tool-34343434343434343434",
        "sbx_stderr": "canary-sbx-45454545454545454545",
        "chk_meta": "canary-chk-56565656565656565656",
        "patch_meta": "canary-patch-67676767676767676767",
        "malicious_repr": "canary-repr-78787878787878787878",
    }

    mock_storage = MockStorageWithLogs(
        logs=[
            {
                "id": "audit-artifact-1",
                "timestamp": "2026-10-07T12:00:00Z",
                "tool_name": "sandbox.execute",
                "decision": "allow",
                "risk_level": "high",
                "tool_args": {
                    "env": {"DISALLOWED_CANARY": canaries["env_var"]},
                    "query_url": f"https://api.openai.com/v1/models?token={canaries['url_query']}",
                    "headers": {
                        "Authorization": f"Bearer {canaries['auth_header']}",
                        "Cookie": f"session={canaries['cookie']}",
                    },
                },
                "result": {
                    "stderr": f"sandbox failure: {canaries['sbx_stderr']}",
                    "exception": f"ProviderConnectionError: failed at {canaries['prov_exc']}",
                    "tool_stderr": f"git execution error: {canaries['tool_stderr']}",
                },
            }
        ]
    )

    redactor = DiagnosticsRedactor(project_root=project_root, data_dir=private_data_dir)
    exporter = DiagnosticsExporter(
        redactor=redactor, storage=mock_storage, project_root=project_root
    )

    custom_files = {
        "security_diagnostic.json": {
            "api_key": canaries["api_key"],
            "bearer": f"Bearer {canaries['bearer_token']}",
            "password": canaries["password"],
            "ipc_token": canaries["ipc_token"],
            "vault_key": canaries["vault_key"],
            "conn_uri": f"postgresql://usr:{canaries['conn_uri']}@db:5432/test",
            "nested": {"level1": [{"level2": canaries["nested"]}]},
            "checkpoint_metadata": {"attempted_id": canaries["chk_meta"]},
            "patch_metadata": {"attempted_hash": canaries["patch_meta"]},
            "malicious_obj": MaliciousReprObject(canaries["malicious_repr"]),
        },
        # Attempt to export blocked files
        "vault.key": "BLOCKED_VAULT_BYTES",
        "ipc.token": "BLOCKED_IPC_BYTES",
        ".env": "BLOCKED_ENV_BYTES",
    }

    bundle = exporter.export_bundle(format="zip", custom_files=custom_files)

    # 1. Archive Parser Inspection & Decompression Scan
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        namelist = zf.namelist()

        # Invariant: Private storage files MUST NOT be present
        assert "vault.key" not in namelist
        assert "ipc.token" not in namelist
        assert ".env" not in namelist

        # Invariant: Manifest must be present and acyclically valid
        assert "manifest.json" in namelist
        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "vault.key" in manifest_data["sections_omitted"]

        # Decompress and scan every single member
        for member_name in namelist:
            # Check member filename itself does not leak any canary
            for name, val in canaries.items():
                assert val not in member_name

            raw_bytes = zf.read(member_name)
            raw_text = raw_bytes.decode("utf-8", errors="replace")

            # Check decompressed contents: EXACTLY 0 occurrences of all 17 seeded canaries!
            for name, val in canaries.items():
                assert val.encode("utf-8") not in raw_bytes, (
                    f"Canary '{name}' leaked in decompressed bytes of {member_name}!"
                )
                assert val not in raw_text, (
                    f"Canary '{name}' leaked in decoded text of {member_name}!"
                )

    # 2. Raw Archive Bytes Scan (defense-in-depth check)
    raw_archive_str = bundle.payload_bytes.decode("latin-1")
    for name, val in canaries.items():
        assert val not in raw_archive_str, f"Canary '{name}' found in raw archive payload!"

    # 3. Useful non-sensitive diagnostic fields remain intact
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        sys_info = json.loads(zf.read("system_info.json").decode("utf-8"))
        assert "agent_engine_version" in sys_info
        assert "python" in sys_info
        assert "hardware" in sys_info

        sec_diag = json.loads(zf.read("security_diagnostic.json").decode("utf-8"))
        assert sec_diag["api_key"] == "***REDACTED***"
        assert sec_diag["password"] == "***REDACTED***"
        assert sec_diag["malicious_obj"] == {"<unserializable_type>": "MaliciousReprObject"}
