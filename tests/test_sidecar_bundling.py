"""
Unit & Integration Tests for Sidecar Bundling & Signing (Task 2.2).

Validates:
- Sidecar CLI argument parsing (--version, --verify, --port, --host, --token).
- Cross-platform target triple detection and bundling into Tauri externalBin.
- SHA-256 checksum generation and manifest metadata.
- Ed25519 cryptographic keypair generation, manifest signing, and verification (ADR-008).
- Tampering detection (bit flips, content modification, invalid signatures).
- Tauri v2 externalBin configuration in tauri.conf.json.
- Tauri v2 capability permissions for sidecar execution.
- Rust supervisor lifecycle methods and IPC command handlers in src/sidecar.rs & src/lib.rs.
- Monorepo Makefile automation targets.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ROOT = REPO_ROOT / "apps" / "desktop"
SRC_TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(REPO_ROOT))

from scripts.bundle_sidecar import (
    bundle_sidecar,
    compute_sha256 as bundle_compute_sha256,
    detect_target_triple,
)
from scripts.sign_artifacts import (
    generate_keypair,
    sign_manifest,
    verify_manifest,
)


def test_sidecar_cli_arguments():
    """Test sidecar CLI --version and --verify flags."""
    # Test --version
    res_ver = subprocess.run(
        [sys.executable, "-m", "services.python.server.api", "--version"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_ver.returncode == 0
    assert "0.1.0" in res_ver.stdout

    # Test --verify
    res_check = subprocess.run(
        [sys.executable, "-m", "services.python.server.api", "--verify"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_check.returncode == 0
    assert "Self-check passed" in res_check.stdout


def test_bundle_sidecar_script():
    """Test bundling sidecar into a directory produces valid launcher and metadata."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        built_path, manifest = bundle_sidecar(
            output_dir=tmp_path,
            target_triple="x86_64-unknown-linux-gnu",
            freeze=False,
        )

        assert built_path.exists(), "Bundled binary must exist"
        assert built_path.stat().st_size > 0

        # Check executable permissions on POSIX
        if os.name != "nt":
            mode = built_path.stat().st_mode
            assert mode & 0o111, "Binary must have executable permissions"

        # Check manifest.json
        manifest_file = tmp_path / "manifest.json"
        assert manifest_file.exists()
        loaded = json.loads(manifest_file.read_text())
        assert loaded["name"] == "agent-engine-sidecar"
        assert loaded["version"] == "0.1.0"
        assert loaded["target_triple"] == "x86_64-unknown-linux-gnu"
        assert loaded["binary"] == "agent-engine-sidecar-x86_64-unknown-linux-gnu"
        assert loaded["sha256"] == bundle_compute_sha256(built_path)

        # Check SHA256SUMS
        sums_file = tmp_path / "SHA256SUMS"
        assert sums_file.exists()
        sums_content = sums_file.read_text()
        assert loaded["sha256"] in sums_content
        assert loaded["binary"] in sums_content


def test_target_triple_detection():
    """Test target triple detection returns recognized format."""
    triple = detect_target_triple()
    assert isinstance(triple, str)
    assert len(triple) > 0
    assert any(sub in triple for sub in ["linux", "darwin", "windows"])


def test_cryptographic_keypair_generation():
    """Test Ed25519 keypair generation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        priv_file, pub_file = generate_keypair(tmp_path)

        assert priv_file.exists()
        assert pub_file.exists()
        assert "BEGIN PRIVATE KEY" in priv_file.read_text()
        assert "BEGIN PUBLIC KEY" in pub_file.read_text()


def test_cryptographic_signing_and_verification():
    """Test full sign and verify workflow using Ed25519."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # 1. Bundle mock binary
        built_path, manifest = bundle_sidecar(
            output_dir=tmp_path,
            target_triple="x86_64-unknown-linux-gnu",
        )
        manifest_file = tmp_path / "manifest.json"

        # 2. Generate keys
        priv_key, pub_key = generate_keypair(tmp_path / "keys")

        # 3. Sign manifest
        signed_file = sign_manifest(
            manifest_path=manifest_file,
            private_key_path=str(priv_key),
        )
        assert signed_file.exists()

        data = json.loads(signed_file.read_text())
        assert data["algorithm"] == "ed25519"
        assert "signature" in data
        assert "public_key" in data

        # 4. Verify manifest
        valid, msg = verify_manifest(signed_file, public_key_path=str(pub_key))
        assert valid is True
        assert "verified" in msg.lower()


def test_tampering_detection():
    """Test tampering with binary or signature causes verification failure (ADR-008)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        built_path, manifest = bundle_sidecar(output_dir=tmp_path)
        manifest_file = tmp_path / "manifest.json"
        priv_key, pub_key = generate_keypair(tmp_path / "keys")
        signed_file = sign_manifest(manifest_file, private_key_path=str(priv_key))

        # Baseline: valid
        valid, _ = verify_manifest(signed_file, public_key_path=str(pub_key))
        assert valid is True

        # Case 1: Tamper with binary content (append byte)
        with open(built_path, "ab") as f:
            f.write(b"\x00")

        valid, msg = verify_manifest(signed_file, public_key_path=str(pub_key))
        assert valid is False
        assert "mismatch" in msg.lower() or "violation" in msg.lower()

        # Revert binary content and re-sign
        built_path, manifest = bundle_sidecar(output_dir=tmp_path)
        signed_file = sign_manifest(manifest_file, private_key_path=str(priv_key))

        # Case 2: Tamper with signature
        tampered_data = json.loads(signed_file.read_text())
        # Alter signature base64
        tampered_data["signature"] = "AA" + tampered_data["signature"][2:]
        signed_file.write_text(json.dumps(tampered_data))

        valid, msg = verify_manifest(signed_file, public_key_path=str(pub_key))
        assert valid is False
        assert "signature verification failed" in msg.lower() or "invalid" in msg.lower()


def test_tauri_conf_external_bin_configuration():
    """Verify tauri.conf.json specifies externalBin for sidecar bundling."""
    conf_file = SRC_TAURI_ROOT / "tauri.conf.json"
    assert conf_file.exists(), "src-tauri/tauri.conf.json must exist"

    with open(conf_file, "r") as f:
        conf = json.load(f)

    bundle_cfg = conf.get("bundle", {})
    external_bin = bundle_cfg.get("externalBin", [])
    assert isinstance(external_bin, list)
    assert any(
        "agent-engine-sidecar" in bin_entry for bin_entry in external_bin
    ), f"externalBin must include agent-engine-sidecar, found: {external_bin}"


def test_tauri_capability_permissions():
    """Verify default.json capability file authorizes shell execution and spawn."""
    cap_file = SRC_TAURI_ROOT / "capabilities" / "default.json"
    assert cap_file.exists(), "capabilities/default.json must exist"

    with open(cap_file, "r") as f:
        cap = json.load(f)

    perms = cap.get("permissions", [])
    assert "shell:allow-execute" in perms
    assert "shell:allow-spawn" in perms

    # Check scoped sidecar entry
    has_sidecar_scope = False
    for p in perms:
        if isinstance(p, dict) and p.get("identifier") in (
            "shell:allow-execute",
            "shell:allow-spawn",
        ):
            for entry in p.get("allow", []):
                if entry.get("sidecar") is True and "agent-engine-sidecar" in entry.get("name", ""):
                    has_sidecar_scope = True
    assert has_sidecar_scope, "Capability must authorize agent-engine-sidecar execution"


def test_sidecar_supervisor_rust_implementation():
    """Verify src/sidecar.rs and src/lib.rs contain lifecycle management and IPC handlers."""
    sidecar_rs = (SRC_TAURI_ROOT / "src" / "sidecar.rs").read_text()
    assert "pub struct SidecarSupervisor" in sidecar_rs
    assert "pub fn compute_sha256" in sidecar_rs
    assert "pub fn locate_sidecar_binary" in sidecar_rs
    assert "pub fn verify_binary_integrity" in sidecar_rs
    assert "pub async fn start" in sidecar_rs
    assert "pub async fn stop" in sidecar_rs
    assert "pub async fn check_health" in sidecar_rs
    assert "checksum_verified" in sidecar_rs

    lib_rs = (SRC_TAURI_ROOT / "src" / "lib.rs").read_text()
    assert "get_sidecar_status" in lib_rs
    assert "start_sidecar" in lib_rs
    assert "stop_sidecar" in lib_rs
    assert "verify_sidecar_binary" in lib_rs
    assert "ExitRequested" in lib_rs


def test_makefile_sidecar_targets():
    """Verify Makefile contains desktop sidecar bundling and signing targets."""
    makefile_content = (REPO_ROOT / "Makefile").read_text()
    assert "desktop-bundle-sidecar" in makefile_content
    assert "desktop-sign-sidecar" in makefile_content
    assert "desktop-verify-sidecar" in makefile_content
