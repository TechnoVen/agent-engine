"""tests/test_r2_diagnostics_redaction.py

Comprehensive test suite for R2.12 Diagnostics Redaction (S1).
Covers CTO Review Sections 13-24 requirements:
1. Central diagnostics architecture (core/diagnostics/ with models, policy, redactor, exporter).
2. Redact at egress boundary: internal operational evidence remains unmutated.
3. Multi-layer redaction pipeline:
   - Layer 1: Structural value objects (SecretValue omitted, SecretReference preserved).
   - Layer 2: Key-based & header scrubbing (passwords, tokens, cookies, auth headers).
   - Layer 3: Environment variable scrubbing (strict allowlist, blocking API keys and secrets).
   - Layer 4: Pattern/Regex token heuristics (OpenAI, Anthropic, Gemini, JWT, PEM, Bearer).
4. Safe object serialization without repr() for unknown objects.
5. Path minimization (<HOME>, <PROJECT>, <DATA_DIR>, <TEMP>).
6. Default exclusion of private storage payloads (vault.key, ipc.token, .env, DBs, checkpoints).
7. Seeded-canary export verification (0 occurrences of canary in exported payload bytes).
8. Packaging and export manifest verification (zip, tar.gz, SHA-256).
"""

from __future__ import annotations

import io
from pathlib import Path
import tarfile
import zipfile
import pytest

from core.diagnostics.exporter import DiagnosticsExporter
from core.diagnostics.models import DiagnosticBundle
from core.diagnostics.redactor import DiagnosticsRedactor
from core.security.secrets import SecretReference, SecretValue


class MockUnserializableObject:
    """Class containing sensitive data whose repr() would leak secrets if called."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def __repr__(self) -> str:
        return f"MockUnserializableObject(LEAKED_SECRET={self._secret})"


class MockStorageWithLogs:
    """Mock storage providing audit logs for diagnostics export."""

    def __init__(self, logs: list | None = None) -> None:
        self.name = "MockAuditStorage"
        self._logs = logs or []

    def list_audit_logs(self, limit: int = 100) -> list:
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
# 1. Structural Value Object Isolation (Layer 1)
# ============================================================================


def test_secret_value_omitted_without_revealing(redactor: DiagnosticsRedactor) -> None:
    """SecretValue container is scrubbed at egress boundary without revealing its plaintext."""
    secret = SecretValue("super-secret-password-12345")
    redacted, report = redactor.redact(secret)

    assert redacted == "***REDACTED***" or redacted == "[REDACTED_SECRET_VALUE]"
    assert "super-secret-password-12345" not in str(redacted)
    assert report.redactions_count >= 1
    assert "secret_value_omitted" in report.redacted_patterns


def test_secret_reference_preserved_as_safe_identifier(redactor: DiagnosticsRedactor) -> None:
    """SecretReference is preserved as structured public identifier."""
    ref = SecretReference(
        provider="openai",
        name="api_key",
        scope="project",
        project_id="proj_100",
    )
    redacted, report = redactor.redact(ref)

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
    assert "secret_reference" in redacted["auth"]["ref"]
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
        "normal_setting": "verbose",
    }
    redacted, report = redactor.redact(payload)

    assert redacted["username"] == "alice"
    assert redacted["normal_setting"] == "verbose"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["access_token"] == "***REDACTED***"
    assert redacted["client_secret"] == "***REDACTED***"
    assert redacted["api_key"] == "***REDACTED***"
    assert "alice_plain_password" not in str(redacted)
    assert report.redactions_count >= 4


def test_sensitive_http_headers_scrubbed(redactor: DiagnosticsRedactor) -> None:
    """Standard HTTP authentication and session headers are scrubbed."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
        "Cookie": "session_id=abcdef1234567890",
        "X-Api-Key": "my-custom-api-key",
        "X-IPC-Token": "ipc-token-secret-999",
        "Accept": "text/html",
    }
    redacted, report = redactor.redact(headers)

    assert redacted["Content-Type"] == "application/json"
    assert redacted["Accept"] == "text/html"
    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["Cookie"] == "***REDACTED***"
    assert redacted["X-Api-Key"] == "***REDACTED***"
    assert redacted["X-IPC-Token"] == "***REDACTED***"
    assert report.redactions_count >= 4


# ============================================================================
# 3. Environment Variable Allowlist (Layer 3)
# ============================================================================


def test_environment_variable_allowlist_filtering(redactor: DiagnosticsRedactor) -> None:
    """Environment variables are filtered against strict allowlist, omitting all secret variables."""
    raw_env = {
        "OS": "Linux",
        "ARCH": "x86_64",
        "PYTHON_VERSION": "3.14.7",
        "AGENT_ENGINE_PORT": "8000",
        "OPENAI_API_KEY": "sk-proj-supersecretkey12345",
        "ANTHROPIC_API_KEY": "sk-ant-supersecretkey12345",
        "DATABASE_URL": "postgres://user:pass@localhost:5432/db",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    }
    redacted_env = redactor.redact_env(raw_env)

    assert "OS" in redacted_env
    assert "ARCH" in redacted_env
    assert "PYTHON_VERSION" in redacted_env
    assert "AGENT_ENGINE_PORT" in redacted_env
    assert "OPENAI_API_KEY" not in redacted_env
    assert "ANTHROPIC_API_KEY" not in redacted_env
    assert "DATABASE_URL" not in redacted_env
    assert "AWS_SECRET_ACCESS_KEY" not in redacted_env
    assert "sk-proj" not in str(redacted_env)


# ============================================================================
# 4. Pattern and Regex Heuristics (Layer 4)
# ============================================================================


def test_regex_token_heuristics_in_text(redactor: DiagnosticsRedactor) -> None:
    """Regex patterns detect and scrub API keys and JWT tokens appearing inside strings and logs."""
    log_text = (
        "Calling OpenAI with key sk-proj-1234567890abcdef1234567890abcdef\n"
        "Anthropic client init sk-ant-api03-abcdef1234567890abcdef1234567890\n"
        "Gemini auth header AIzaSyB1234567890abcdef1234567890abcdef\n"
        "User bearer header Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef1234567890"
    )
    redacted_text = redactor.redact_text(log_text)

    assert "sk-proj-1234567890abcdef" not in redacted_text
    assert "sk-ant-api03-abcdef" not in redacted_text
    assert "AIzaSyB1234567890abcdef" not in redacted_text
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted_text
    assert "***REDACTED***" in redacted_text


def test_pem_private_key_block_redacted(redactor: DiagnosticsRedactor) -> None:
    """Full PEM private key blocks embedded in strings are redacted."""
    pem_key = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y8v...fake...key...material...xyz\n"
        "-----END RSA PRIVATE KEY-----"
    )
    text = f"Certificate loaded:\n{pem_key}\nReady."
    redacted = redactor.redact_text(text)

    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "fake...key...material" not in redacted
    assert "***REDACTED***" in redacted


# ============================================================================
# 5. Safe Object Serialization (Without repr())
# ============================================================================


def test_unknown_object_serialized_without_repr(redactor: DiagnosticsRedactor) -> None:
    """Unknown complex objects are safely serialized without calling repr() to avoid leaking secrets."""
    sensitive_obj = MockUnserializableObject("SECRET_CANARY_VALUE_999")
    payload = {"custom_service": sensitive_obj}

    redacted, report = redactor.redact(payload)

    # Invariant: repr() was NOT called, so LEAKED_SECRET and SECRET_CANARY_VALUE_999 are absent!
    assert "LEAKED_SECRET" not in str(redacted)
    assert "SECRET_CANARY_VALUE_999" not in str(redacted)
    assert redacted["custom_service"] == {"<unserializable_type>": "MockUnserializableObject"}
    assert report.redactions_count >= 1


# ============================================================================
# 6. Path Minimization (<HOME>, <PROJECT>, <DATA_DIR>, <TEMP>)
# ============================================================================


def test_path_minimization_to_standard_placeholders(
    redactor: DiagnosticsRedactor, project_root: Path, private_data_dir: Path
) -> None:
    """Absolute filesystem paths are minimized to standardized anonymized placeholders."""
    home_path = redactor.home_dir / "projects" / "secrets.txt"
    proj_path = project_root / "src" / "main.py"
    data_path = private_data_dir / "checkpoints" / "chk-123"

    sample_log = (
        f"File loaded from {proj_path}\n"
        f"Private checkpoint stored at {data_path}\n"
        f"User document located at {home_path}\n"
    )

    minimized = redactor.redact_text(sample_log)

    assert str(project_root) not in minimized
    assert str(private_data_dir) not in minimized
    assert str(redactor.home_dir) not in minimized

    assert "<PROJECT>/src/main.py" in minimized
    assert "<DATA_DIR>/checkpoints/chk-123" in minimized
    assert "<HOME>/projects/secrets.txt" in minimized


# ============================================================================
# 7. Exclusion of Private Storage Payloads
# ============================================================================


def test_exporter_blocks_private_storage_payloads(
    project_root: Path, private_data_dir: Path
) -> None:
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


# ============================================================================
# 8. Seeded-Canary Export Verification (0 Occurrences)
# ============================================================================


def test_seeded_canary_export_verification_zip(project_root: Path, private_data_dir: Path) -> None:
    """Seeded canary secrets produce 0 occurrences in final exported zip archive payload bytes."""
    canary_token = "canary-token-998877665544332211"
    canary_api_key = "sk-proj-canary-secret-uuid-9988"

    mock_storage = MockStorageWithLogs(
        logs=[
            {
                "id": "audit-1",
                "timestamp": "2026-10-03T00:00:00Z",
                "tool_name": "bash",
                "decision": "allow",
                "risk_level": "medium",
                "tool_args": {"command": f"echo {canary_token}"},
                "result": {"stdout": f"executed with {canary_api_key}"},
            }
        ]
    )

    redactor = DiagnosticsRedactor(project_root=project_root, data_dir=private_data_dir)
    exporter = DiagnosticsExporter(
        redactor=redactor,
        storage=mock_storage,
        project_root=project_root,
    )

    custom_files = {
        "custom_log.txt": f"Diagnostic custom text with {canary_token}\n",
        "custom_config.json": {"api_key": canary_api_key, "canary": canary_token},
        # Attempt to export blocked file
        "vault.key": "THIS_SHOULD_BE_BLOCKED_ENTIRELY",
    }

    bundle: DiagnosticBundle = exporter.export_bundle(format="zip", custom_files=custom_files)

    # 1. Byte-level canary verification: exactly 0 occurrences in raw bundle payload bytes!
    raw_payload_str = bundle.payload_bytes.decode("latin-1")
    assert canary_token not in raw_payload_str
    assert canary_api_key not in raw_payload_str
    assert "THIS_SHOULD_BE_BLOCKED_ENTIRELY" not in raw_payload_str

    # 2. Inspect archive contents
    with zipfile.ZipFile(io.BytesIO(bundle.payload_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "vault.key" not in namelist

        # Inspect custom_log.txt inside archive
        log_bytes = zf.read("custom_log.txt")
        assert canary_token.encode("utf-8") not in log_bytes
        assert b"***REDACTED***" in log_bytes


def test_seeded_canary_export_verification_tar_gz(
    project_root: Path, private_data_dir: Path
) -> None:
    """Seeded canary secrets produce 0 occurrences in final exported tar.gz archive payload bytes."""
    canary_token = "canary-token-tar-778899aabbcc"
    mock_storage = MockStorageWithLogs(
        logs=[
            {
                "id": "audit-2",
                "timestamp": "2026-10-03T00:00:00Z",
                "tool_name": "curl",
                "decision": "allow",
                "risk_level": "low",
                "tool_args": {"header": f"Bearer {canary_token}"},
                "result": {"status": 200},
            }
        ]
    )

    exporter = DiagnosticsExporter(
        redactor=DiagnosticsRedactor(project_root=project_root, data_dir=private_data_dir),
        storage=mock_storage,
        project_root=project_root,
    )

    bundle: DiagnosticBundle = exporter.export_bundle(
        format="tar.gz",
        custom_files={"note.txt": f"Sensitive canary {canary_token}"},
    )

    # Unpack tar.gz in memory and check all files
    with tarfile.open(fileobj=io.BytesIO(bundle.payload_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            f = tar.extractfile(member)
            if f:
                content = f.read()
                assert canary_token.encode("utf-8") not in content

    assert bundle.content_type == "application/gzip"
    assert bundle.filename.endswith(".tar.gz")


# ============================================================================
# 9. Egress Boundary Invariant (Internal Storage Unmutated)
# ============================================================================


def test_egress_boundary_leaves_internal_storage_unmutated(
    project_root: Path, private_data_dir: Path
) -> None:
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
# 10. Manifest and Cryptographic Verifiability
# ============================================================================


def test_export_manifest_cryptographic_verification(project_root: Path) -> None:
    """Export manifest includes valid SHA-256 hash matching payload bytes."""
    import hashlib

    exporter = DiagnosticsExporter(project_root=project_root)
    bundle = exporter.export_bundle(format="zip", bundle_id="diag-test-999")

    assert bundle.manifest.bundle_id == "diag-test-999"
    assert bundle.manifest.sha256_hash == hashlib.sha256(bundle.payload_bytes).hexdigest()
    assert (
        bundle.manifest.total_bytes == len(bundle.payload_bytes) or bundle.manifest.total_bytes > 0
    )
    assert "manifest.json" in bundle.manifest.files
    assert "system_info.json" in bundle.manifest.files
