#!/usr/bin/env python3
"""infra/update-server/serve_feed.py - Local update feed server for development and testing.

Serves Tauri v2 signed update manifests and binary release assets over HTTP.
Satisfies Task 2.4 (Auto-Update Channel) and ADR-008.

Usage:
    python infra/update-server/serve_feed.py --port 8088 --dir dist/updates
"""

import argparse
import http.server
import logging
import os
import socketserver
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("update-server")


class UpdateFeedHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP request handler with CORS headers and JSON content-type support."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        logger.info(f"{self.address_string()} - {fmt % args}")


def run_server(host: str, port: int, directory: Path) -> None:
    """Run the update feed server."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)

    class CustomDirHandler(UpdateFeedHTTPHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(directory), **kwargs)  # type: ignore[call-arg]

    with socketserver.TCPServer((host, port), CustomDirHandler) as httpd:
        logger.info(f"Serving update manifests from {directory} at http://{host}:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Update server stopped by user")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local mock update feed server for Agent Engine Tauri updates"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("UPDATE_SERVER_HOST", "127.0.0.1"),
        help="Host interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("UPDATE_SERVER_PORT", "8088")),
        help="Port to listen on (default: 8088)",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("dist/updates"),
        help="Directory containing manifests and release assets (default: dist/updates)",
    )
    args = parser.parse_args()

    try:
        run_server(args.host, args.port, args.dir)
    except Exception as e:
        logger.error(f"Failed to start update server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
