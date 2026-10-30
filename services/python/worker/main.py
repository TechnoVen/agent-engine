"""services/python/worker/main.py

CLI and Standalone Execution Runner for Durable Job Worker Service (Task R4.3).
Part of Milestone R4 (Task R4.3 - Worker Service).

Runs independently from desktop UI and Tauri processes.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from typing import Any, List, Optional

from core.jobs.worker import DEFAULT_JOBS_DB_PATH, JobWorker

logger = logging.getLogger("agent_engine.services.worker")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent Engine Durable Job Worker Service",
        prog="python -m services.python.worker",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_JOBS_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_JOBS_DB_PATH})",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Custom worker identifier (default: auto-generated wrk_<uuid12>)",
    )
    parser.add_argument(
        "--lease-ttl",
        type=float,
        default=60.0,
        help="Lease duration in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=None,
        help="Heartbeat extension interval in seconds (default: lease_ttl / 3)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval when queue is empty in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--drain-timeout",
        type=float,
        default=5.0,
        help="Maximum seconds to drain active work on SIGINT/SIGTERM (default: 5.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one job if available and then exit (useful for testing)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(args)


def main(args: Optional[List[str]] = None) -> int:
    parsed = parse_args(args)

    level = logging.DEBUG if parsed.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s (pid=%(process)d): %(message)s",
    )

    worker = JobWorker(
        db_path=parsed.db_path,
        worker_id=parsed.worker_id,
        lease_ttl_seconds=parsed.lease_ttl,
        heartbeat_interval_seconds=parsed.heartbeat_interval,
        poll_interval_seconds=parsed.poll_interval,
        drain_timeout_seconds=parsed.drain_timeout,
    )

    def handle_signal(sig: int, frame: Any) -> None:
        signame = signal.Signals(sig).name
        logger.info("Received signal %s; requesting worker graceful stop", signame)
        worker.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(
        "Starting standalone JobWorker id=%s pid=%d db=%s lease_ttl=%.1fs",
        worker.worker_id,
        os.getpid(),
        parsed.db_path,
        parsed.lease_ttl,
    )

    try:
        if parsed.once:
            processed = worker.step()
            logger.info("Single step completed (processed=%s)", processed)
        else:
            worker.run()
    except Exception as e:
        logger.error("Worker fatal failure: %s", e, exc_info=True)
        return 1
    finally:
        worker.close()

    logger.info("Worker %s shut down cleanly", worker.worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
