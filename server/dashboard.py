"""Deprecated: server/dashboard.py has been moved to tools/dev_dashboard.py.

The sole official user-facing UI is the Tauri Desktop application (apps/desktop).
Streamlit is demoted to an internal developer tool.
"""

import os
import sys
import warnings

warnings.warn(
    "server/dashboard.py is deprecated and has been moved to tools/dev_dashboard.py. "
    "The sole official user-facing UI is the Tauri Desktop application.",
    DeprecationWarning,
    stacklevel=2,
)

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools.dev_dashboard import (  # noqa: E402
    auto_repair_naked_return,
    extract_code_block,
)

__all__ = ["auto_repair_naked_return", "extract_code_block"]

if __name__ == "__main__" or "streamlit" in sys.modules:
    import subprocess

    sys.exit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                os.path.join(PROJECT_ROOT, "tools", "dev_dashboard.py"),
                *sys.argv[1:],
            ]
        )
    )
