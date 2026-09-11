#!/usr/bin/env python3
"""
Agent Engine — Artifact Signing & Integrity Verification (Task 2.2).

Provides Ed25519 cryptographic signing and SHA-256 integrity verification
for the desktop sidecar binary and distribution artifacts (ADR-008: Zero-Trust Local Integrity).
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BINARIES_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
DEFAULT_KEYS_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "keys"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hexadecimal hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_keypair(output_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """Generate Ed25519 keypair and save private/public keys."""
    out_dir = Path(output_dir) if output_dir else DEFAULT_KEYS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    priv_bytes = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_file = out_dir / "ed25519.pem"
    pub_file = out_dir / "ed25519.pub"

    priv_file.write_bytes(priv_bytes)
    pub_file.write_bytes(pub_bytes)

    # Restrict permissions on private key
    os.chmod(priv_file, 0o600)

    return priv_file, pub_file


def load_private_key(key_path_or_env: Optional[str] = None) -> ed25519.Ed25519PrivateKey:
    """Load private key from path, environment variable, or default location."""
    if key_path_or_env and Path(key_path_or_env).is_file():
        data = Path(key_path_or_env).read_bytes()
        return serialization.load_pem_private_key(data, password=None)

    env_key = os.environ.get("AGENT_ENGINE_SIGNING_KEY")
    if env_key:
        if Path(env_key).is_file():
            data = Path(env_key).read_bytes()
        else:
            data = env_key.encode()
        return serialization.load_pem_private_key(data, password=None)

    default_key = DEFAULT_KEYS_DIR / "ed25519.pem"
    if default_key.is_file():
        return serialization.load_pem_private_key(default_key.read_bytes(), password=None)

    # If no key exists, generate one automatically in default location
    priv_file, _ = generate_keypair(DEFAULT_KEYS_DIR)
    return serialization.load_pem_private_key(priv_file.read_bytes(), password=None)


def load_public_key(pub_key_path_or_data: Optional[str] = None) -> ed25519.Ed25519PublicKey:
    """Load public key from file, raw string, or default location."""
    if pub_key_path_or_data and Path(pub_key_path_or_data).is_file():
        data = Path(pub_key_path_or_data).read_bytes()
        return serialization.load_pem_public_key(data)

    if pub_key_path_or_data and "PUBLIC KEY" in pub_key_path_or_data:
        return serialization.load_pem_public_key(pub_key_path_or_data.encode())

    env_pub = os.environ.get("AGENT_ENGINE_PUBLIC_KEY")
    if env_pub:
        if Path(env_pub).is_file():
            data = Path(env_pub).read_bytes()
        else:
            data = env_pub.encode()
        return serialization.load_pem_public_key(data)

    default_pub = DEFAULT_KEYS_DIR / "ed25519.pub"
    if default_pub.is_file():
        return serialization.load_pem_public_key(default_pub.read_bytes())

    raise FileNotFoundError("Public key not found. Run --generate-keys first.")


def sign_manifest(
    manifest_path: Path,
    private_key_path: Optional[str] = None,
    output_signed_path: Optional[Path] = None,
) -> Path:
    """Sign a manifest.json and write manifest.signed.json."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text())
    binary_name = manifest_data.get("binary")
    binary_path = manifest_path.parent / binary_name

    if not binary_path.is_file():
        raise FileNotFoundError(f"Referenced binary not found: {binary_path}")

    # Verify actual hash matches manifest declared hash
    actual_hash = compute_sha256(binary_path)
    if actual_hash != manifest_data.get("sha256"):
        raise ValueError(
            f"Binary hash mismatch before signing! "
            f"Declared: {manifest_data.get('sha256')}, Actual: {actual_hash}"
        )

    priv_key = load_private_key(private_key_path)
    pub_key = priv_key.public_key()

    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    # Canonical bytes to sign
    canonical_json = json.dumps(manifest_data, sort_keys=True).encode("utf-8")
    signature = priv_key.sign(canonical_json)
    signature_b64 = base64.b64encode(signature).decode("ascii")

    signed_payload = {
        "manifest": manifest_data,
        "algorithm": "ed25519",
        "public_key": pub_pem.strip(),
        "signature": signature_b64,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    out_file = output_signed_path or (manifest_path.parent / "manifest.signed.json")
    out_file.write_text(json.dumps(signed_payload, indent=2) + "\n")
    return out_file


def verify_manifest(
    signed_manifest_path: Path,
    public_key_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verify digital signature and binary checksum in signed manifest.
    Returns (True, message) if valid, (False, reason) if verification fails.
    """
    if not signed_manifest_path.is_file():
        return False, f"Signed manifest not found: {signed_manifest_path}"

    try:
        data = json.loads(signed_manifest_path.read_text())
    except Exception as e:
        return False, f"Invalid JSON in signed manifest: {e}"

    manifest = data.get("manifest")
    if not manifest:
        return False, "Missing 'manifest' block in signed document"

    sig_b64 = data.get("signature")
    if not sig_b64:
        return False, "Missing 'signature' in signed document"

    # Resolve public key
    try:
        if public_key_path:
            pub_key = load_public_key(public_key_path)
        elif data.get("public_key"):
            pub_key = load_public_key(data.get("public_key"))
        else:
            pub_key = load_public_key()
    except Exception as e:
        return False, f"Failed to load public key: {e}"

    # 1. Verify cryptographic digital signature
    canonical_json = json.dumps(manifest, sort_keys=True).encode("utf-8")
    try:
        sig_bytes = base64.b64decode(sig_b64)
        pub_key.verify(sig_bytes, canonical_json)
    except Exception as e:
        return False, f"Cryptographic signature verification failed: {e}"

    # 2. Verify binary file existence and SHA-256 checksum
    binary_name = manifest.get("binary")
    if not binary_name:
        return False, "Manifest missing 'binary' filename"

    binary_path = signed_manifest_path.parent / binary_name
    if not binary_path.is_file():
        return False, f"Binary file not found: {binary_path}"

    actual_hash = compute_sha256(binary_path)
    expected_hash = manifest.get("sha256")
    if actual_hash != expected_hash:
        return False, (
            f"Integrity violation! Binary SHA-256 hash mismatch. "
            f"Expected: {expected_hash}, Computed: {actual_hash}"
        )

    return True, f"Signature and SHA-256 integrity verified for {binary_name}"


def main(argv: Optional[list] = None):
    parser = argparse.ArgumentParser(
        description="Sign and verify Agent Engine sidecar binaries (Ed25519)",
        prog="sign_artifacts.py",
    )
    parser.add_argument(
        "--generate-keys",
        action="store_true",
        help="Generate a new Ed25519 keypair in apps/desktop/src-tauri/keys/",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Sign the manifest.json in binaries directory",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the signed manifest and binary integrity",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=str(DEFAULT_BINARIES_DIR / "manifest.json"),
        help="Path to manifest.json (for --sign)",
    )
    parser.add_argument(
        "--signed-manifest",
        type=str,
        default=str(DEFAULT_BINARIES_DIR / "manifest.signed.json"),
        help="Path to manifest.signed.json (for --verify)",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Path to private key (for --sign) or public key (for --verify)",
    )

    args = parser.parse_args(argv)

    if args.generate_keys:
        priv, pub = generate_keypair()
        print("[OK] Generated Ed25519 keypair:")
        print(f"     Private: {priv}")
        print(f"     Public:  {pub}")
        return

    if args.sign:
        out = sign_manifest(Path(args.manifest), private_key_path=args.key)
        print(f"[OK] Signed manifest generated: {out}")
        return

    if args.verify:
        valid, msg = verify_manifest(Path(args.signed_manifest), public_key_path=args.key)
        if valid:
            print(f"[PASS] {msg}")
            sys.exit(0)
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
            sys.exit(1)

    # Default action if no flags provided: generate keys if missing, sign, and verify
    manifest_file = Path(args.manifest)
    if manifest_file.exists():
        out = sign_manifest(manifest_file)
        valid, msg = verify_manifest(out)
        if valid:
            print(f"[OK] Manifest signed and verified: {out}")
        else:
            print(f"[ERROR] Verification failed: {msg}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
