#!/usr/bin/env python3
"""
Agent Engine — Sidecar Bundling Utility (Task 2.2).

Detects host platform target triple, bundles the Python sidecar service
(via PyInstaller or self-contained executable launcher), generates
SHA-256 checksums, and produces manifest metadata for Tauri v2 externalBin packaging.
"""

import argparse
import datetime
import hashlib
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"


def detect_target_triple() -> str:
    """Detect Rust/Tauri target triple for the current host platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        elif machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
        return f"{machine}-unknown-linux-gnu"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        return "x86_64-apple-darwin"
    elif system == "windows":
        return "x86_64-pc-windows-msvc"
    return f"{machine}-unknown-{system}"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hexadecimal hash of a binary file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_executable_launcher(
    output_path: Path,
    target_triple: str,
) -> Path:
    """Create a self-contained executable wrapper script for the sidecar."""
    is_windows = "windows" in target_triple

    if is_windows:
        # On Windows, generate batch wrapper
        bat_path = output_path.with_suffix(".cmd")
        content = (
            "@echo off\r\n"
            "setlocal\r\n"
            "set SCRIPT_DIR=%~dp0\r\n"
            "set REPO_ROOT=%SCRIPT_DIR%..\\..\\..\\..\r\n"
            'if exist "%REPO_ROOT%\\.venv\\Scripts\\python.exe" (\r\n'
            '    "%REPO_ROOT%\\.venv\\Scripts\\python.exe" -m services.python.server.api %*\r\n'
            ") else (\r\n"
            "    python -m services.python.server.api %*\r\n"
            ")\r\n"
        )
        bat_path.write_text(content)
        # Also touch the expected binary path
        output_path.write_bytes(content.encode())
    else:
        # On POSIX (Linux/macOS), generate self-contained shell launcher
        content = (
            "#!/usr/bin/env bash\n"
            "# Agent Engine Standalone Sidecar Launcher\n"
            "set -e\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            "# Locate repository root (4 levels up from apps/desktop/src-tauri/binaries/)\n"
            'REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." 2>/dev/null && pwd || true)"\n'
            'if [ ! -d "${REPO_ROOT}/services" ]; then\n'
            "    # Fallback search if installed in bundle\n"
            '    REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"\n'
            "fi\n"
            'export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH}"\n'
            'if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then\n'
            '    exec "${REPO_ROOT}/.venv/bin/python" -m services.python.server.api "$@"\n'
            'elif command -v uv >/dev/null 2>&1 && [ -f "${REPO_ROOT}/pyproject.toml" ]; then\n'
            '    exec uv run --directory "${REPO_ROOT}" python -m services.python.server.api "$@"\n'
            "else\n"
            '    exec python3 -m services.python.server.api "$@"\n'
            "fi\n"
        )
        output_path.write_text(content)
        # Ensure executable permissions 0o755
        st = os.stat(output_path)
        os.chmod(output_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return output_path


def bundle_with_pyinstaller(
    output_path: Path,
    target_triple: str,
) -> Optional[Path]:
    """Attempt to compile sidecar into a single frozen binary with PyInstaller."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return None

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        output_path.name,
        "--distpath",
        str(output_path.parent),
        "--clean",
        "--noconfirm",
        str(REPO_ROOT / "services" / "python" / "server" / "api.py"),
    ]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if res.returncode == 0 and output_path.exists():
        return output_path
    return None


def bundle_sidecar(
    output_dir: Optional[Path] = None,
    target_triple: Optional[str] = None,
    freeze: bool = False,
) -> Tuple[Path, Dict]:
    """Bundle the Python sidecar into the Tauri externalBin directory."""
    triple = target_triple or detect_target_triple()
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    binary_name = f"agent-engine-sidecar-{triple}"
    if "windows" in triple and not binary_name.endswith(".exe"):
        binary_name += ".exe"

    binary_path = out_dir / binary_name

    built_path = None
    build_mode = "launcher"

    if freeze:
        built_path = bundle_with_pyinstaller(binary_path, triple)
        if built_path:
            build_mode = "pyinstaller"

    if not built_path:
        built_path = create_executable_launcher(binary_path, triple)

    sha256 = compute_sha256(built_path)
    size_bytes = built_path.stat().st_size

    # Write SHA256SUMS
    sha_file = out_dir / "SHA256SUMS"
    sha_line = f"{sha256}  {binary_name}\n"
    sha_file.write_text(sha_line)

    # Write manifest.json
    manifest = {
        "name": "agent-engine-sidecar",
        "version": "0.1.0",
        "target_triple": triple,
        "binary": binary_name,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "build_mode": build_mode,
        "bundled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    import json

    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")

    return built_path, manifest


def main(argv: Optional[list] = None):
    parser = argparse.ArgumentParser(
        description="Bundle Python sidecar for Agent Engine desktop shell (Tauri v2)",
        prog="bundle_sidecar.py",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Target directory for binaries (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--triple",
        "-t",
        type=str,
        default=None,
        help="Target architecture triple (default: auto-detected host triple)",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Attempt PyInstaller single-file binary freeze if available",
    )

    args = parser.parse_args(argv)
    path, manifest = bundle_sidecar(
        output_dir=Path(args.output_dir),
        target_triple=args.triple,
        freeze=args.freeze,
    )

    print(f"[OK] Bundled sidecar successfully: {path}")
    print(f"     Target Triple: {manifest['target_triple']}")
    print(f"     SHA-256:       {manifest['sha256']}")
    print(f"     Size:          {manifest['size_bytes']} bytes ({manifest['build_mode']})")


if __name__ == "__main__":
    main()
