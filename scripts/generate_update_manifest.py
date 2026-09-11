#!/usr/bin/env python3
"""scripts/generate_update_manifest.py

Generates and cryptographically signs Tauri v2 update manifests for Agent Engine
across multiple distribution channels (stable, beta, nightly) - ADR-008.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UPDATES_DIR = REPO_ROOT / "dist" / "updates"
DEFAULT_KEYS_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "keys"

CHANNELS = ("stable", "beta", "nightly")

# Platform target identifiers mapping to standard target-triples
PLATFORM_TRIPLES = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "darwin-aarch64": "aarch64-apple-darwin",
    "darwin-x86_64": "x86_64-apple-darwin",
    "windows-x86_64": "x86_64-pc-windows-msvc",
}


def load_private_key(
    key_input: Optional[Any] = None,
) -> ed25519.Ed25519PrivateKey:
    """Load or generate Ed25519 private key for signing update manifests."""
    if isinstance(key_input, ed25519.Ed25519PrivateKey):
        return key_input

    if key_input and Path(key_input).is_file():
        data = Path(key_input).read_bytes()
        try:
            return serialization.load_pem_private_key(data, password=None)  # type: ignore[return-value]
        except Exception:
            if len(data) == 32:
                return ed25519.Ed25519PrivateKey.from_private_bytes(data)
            raise

    env_key = os.environ.get("AGENT_ENGINE_SIGNING_KEY")
    if env_key:
        if Path(env_key).is_file():
            data = Path(env_key).read_bytes()
        else:
            data = env_key.encode("utf-8")
        try:
            return serialization.load_pem_private_key(data, password=None)  # type: ignore[return-value]
        except Exception:
            if len(data) == 32:
                return ed25519.Ed25519PrivateKey.from_private_bytes(data)
            raise

    default_key = DEFAULT_KEYS_DIR / "ed25519.pem"
    if default_key.is_file():
        return serialization.load_pem_private_key(default_key.read_bytes(), password=None)  # type: ignore[return-value]

    # Generate a keypair if none exists
    DEFAULT_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    default_key.write_bytes(priv_bytes)
    (DEFAULT_KEYS_DIR / "ed25519.pub").write_bytes(pub_bytes)
    os.chmod(default_key, 0o600)
    return priv


def load_public_key(
    pub_key_input: Optional[Any] = None,
) -> ed25519.Ed25519PublicKey:
    """Load Ed25519 public key."""
    if isinstance(pub_key_input, ed25519.Ed25519PublicKey):
        return pub_key_input

    if pub_key_input and Path(pub_key_input).is_file():
        data = Path(pub_key_input).read_bytes()
        try:
            return serialization.load_pem_public_key(data)  # type: ignore[return-value]
        except Exception:
            if len(data) == 32:
                return ed25519.Ed25519PublicKey.from_public_bytes(data)
            raise

    env_pub = os.environ.get("AGENT_ENGINE_PUBLIC_KEY")
    if env_pub:
        if Path(env_pub).is_file():
            data = Path(env_pub).read_bytes()
        else:
            data = env_pub.encode("utf-8")
        try:
            return serialization.load_pem_public_key(data)  # type: ignore[return-value]
        except Exception:
            if len(data) == 32:
                return ed25519.Ed25519PublicKey.from_public_bytes(data)
            raise

    default_pub = DEFAULT_KEYS_DIR / "ed25519.pub"
    if default_pub.is_file():
        return serialization.load_pem_public_key(default_pub.read_bytes())  # type: ignore[return-value]

    raise FileNotFoundError(f"Public key not found at {default_pub}")


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sign_data(data: bytes, private_key: ed25519.Ed25519PrivateKey) -> str:
    """Sign bytes with Ed25519 and return base64 encoded signature."""
    sig = private_key.sign(data)
    return base64.b64encode(sig).decode("utf-8")


def verify_signature(data: bytes, signature_b64: str, public_key: ed25519.Ed25519PublicKey) -> bool:
    """Verify base64 encoded Ed25519 signature."""
    try:
        sig = base64.b64decode(signature_b64)
        public_key.verify(sig, data)
        return True
    except Exception:
        return False


def canonical_manifest_bytes(manifest: Dict[str, Any]) -> bytes:
    """Return sorted, deterministic UTF-8 bytes for manifest fields excluding underscore prefixes."""
    return json.dumps(
        {k: v for k, v in manifest.items() if not k.startswith("_")},
        sort_keys=True,
    ).encode("utf-8")


def sign_manifest_dict(
    manifest: Dict[str, Any],
    private_key: Optional[Any] = None,
) -> Dict[str, Any]:
    """Cryptographically sign a manifest dictionary with Ed25519."""
    priv = (
        load_private_key(private_key)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey)
        else private_key
    )
    out = dict(manifest)
    out["_signature_algorithm"] = "ed25519"
    out["_manifest_signature"] = sign_data(canonical_manifest_bytes(out), priv)
    return out


def verify_manifest_dict(
    manifest: Dict[str, Any],
    public_key: Optional[Any] = None,
) -> bool:
    """Verify cryptographic Ed25519 signature of a manifest dictionary."""
    pub = (
        load_public_key(public_key)
        if not isinstance(public_key, ed25519.Ed25519PublicKey)
        else public_key
    )
    sig_b64 = manifest.get("_manifest_signature")
    if not sig_b64:
        return False
    return verify_signature(canonical_manifest_bytes(manifest), sig_b64, pub)


def build_update_manifest(
    version: str,
    channel: str = "stable",
    notes: str = "",
    base_url: str = "https://github.com/TechnoVen/agent-engine/releases/download",
    binaries_dir: Optional[Path] = None,
    private_key: Optional[ed25519.Ed25519PrivateKey] = None,
) -> Dict[str, Any]:
    """Construct and sign a Tauri v2 update manifest."""
    if channel not in CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'. Must be one of {CHANNELS}")

    priv_key = private_key or load_private_key()
    pub_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_version = version.lstrip("v")

    platforms: Dict[str, Any] = {}

    for platform_id, target_triple in PLATFORM_TRIPLES.items():
        if "windows" in platform_id:
            ext = ".exe.zip"
        elif "darwin" in platform_id:
            ext = ".app.tar.gz"
        else:
            ext = ".AppImage.tar.gz"

        asset_name = f"agent-engine_{clean_version}_{platform_id}{ext}"
        asset_url = f"{base_url}/v{clean_version}/{asset_name}"

        # If a real local binary exists, hash its actual bytes; else hash canonical url string
        sha256_hash = None
        if binaries_dir and (binaries_dir / f"agent-engine-sidecar-{target_triple}").is_file():
            bin_file = binaries_dir / f"agent-engine-sidecar-{target_triple}"
            sha256_hash = compute_sha256(bin_file)
            payload_to_sign = bin_file.read_bytes()
        else:
            sim_bytes = f"{asset_url}:{clean_version}:{platform_id}".encode("utf-8")
            sha256_hash = hashlib.sha256(sim_bytes).hexdigest()
            payload_to_sign = sim_bytes

        sig_b64 = sign_data(payload_to_sign, priv_key)

        platforms[platform_id] = {
            "url": asset_url,
            "signature": sig_b64,
            "sha256": sha256_hash,
            "target_triple": target_triple,
        }

    manifest: Dict[str, Any] = {
        "version": clean_version,
        "channel": channel,
        "notes": notes or f"Agent Engine {clean_version} ({channel} channel)",
        "pub_date": pub_date,
        "platforms": platforms,
        "_signature_algorithm": "ed25519",
    }

    manifest["_manifest_signature"] = sign_data(canonical_manifest_bytes(manifest), priv_key)

    return manifest


def verify_manifest(
    manifest: Dict[str, Any],
    public_key: Optional[ed25519.Ed25519PublicKey] = None,
) -> bool:
    """Verify the cryptographic signature of an update manifest."""
    return verify_manifest_dict(manifest, public_key)


def generate_all_channel_manifests(
    version: str,
    base_url: str = "https://github.com/TechnoVen/agent-engine/releases/download",
    out_dir: Optional[Path] = None,
    private_key_path: Optional[Path] = None,
    notes_prefix: str = "Agent Engine",
) -> Dict[str, Dict[str, Any]]:
    """Generate and return signed manifests for all release channels."""
    priv_key = load_private_key(private_key_path) if private_key_path else load_private_key()
    manifests = {}
    clean_version = version.lstrip("v")
    for ch in CHANNELS:
        manifest = build_update_manifest(
            version=clean_version,
            channel=ch,
            notes=f"{notes_prefix} {clean_version} ({ch} channel)",
            base_url=base_url,
            private_key=priv_key,
        )
        manifests[ch] = manifest
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / f"{ch}.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

    # Stable is also aliased to latest.json
    manifests["latest"] = manifests["stable"]
    if out_dir:
        with open(out_dir / "latest.json", "w", encoding="utf-8") as f:
            json.dump(manifests["stable"], f, indent=2)

    return manifests


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and sign Tauri v2 update manifests for Agent Engine release channels."
    )
    parser.add_argument(
        "--version",
        "-v",
        type=str,
        default="0.1.0",
        help="Release version string (e.g. 0.2.0, 0.2.0-beta.1)",
    )
    parser.add_argument(
        "--channel",
        "-c",
        type=str,
        choices=CHANNELS,
        default="stable",
        help="Release channel (stable, beta, nightly)",
    )
    parser.add_argument(
        "--notes",
        "-n",
        type=str,
        default="",
        help="Release notes or changelog summary",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_UPDATES_DIR,
        help="Output directory for generated manifests (default: dist/updates)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://github.com/TechnoVen/agent-engine/releases/download",
        help="Base download URL for release assets",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=None,
        help="Path to Ed25519 private key",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing manifest in output directory",
    )

    args = parser.parse_args(argv)

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    channel_file = out_dir / f"{args.channel}.json"

    if args.verify:
        if not channel_file.is_file():
            print(f"[ERROR] Manifest file not found: {channel_file}")
            return 1
        with open(channel_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        if verify_manifest(manifest_data):
            print(f"[OK] Manifest signature valid for channel '{args.channel}': {channel_file}")
            return 0
        else:
            print(f"[ERROR] Manifest signature verification failed for: {channel_file}")
            return 1

    priv_key = load_private_key(args.key)
    manifest = build_update_manifest(
        version=args.version,
        channel=args.channel,
        notes=args.notes,
        base_url=args.base_url,
        private_key=priv_key,
    )

    with open(channel_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # For stable channel, also write latest.json
    if args.channel == "stable":
        latest_file = out_dir / "latest.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    print(f"[OK] Generated signed update manifest: {channel_file}")
    if args.channel == "stable":
        print(f"[OK] Generated stable alias: {out_dir / 'latest.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
