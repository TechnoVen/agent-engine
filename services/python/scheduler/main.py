"""services/python/scheduler/main.py

CLI and Standalone Runner for Timezone-Aware Recurring Job Scheduler (Task R4.7).
Part of Milestone R4 (Task R4.7 - Timezone-Aware Scheduler).

Runs independently from desktop UI, Tauri processes, and worker executors.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Any, List, Optional

from core.jobs.scheduler import SchedulerService
from core.jobs.sqlite import DEFAULT_JOBS_DB_PATH

logger = logging.getLogger("agent_engine.services.scheduler")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent Engine Timezone-Aware Recurring Job Scheduler",
        prog="python -m services.python.scheduler",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_JOBS_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_JOBS_DB_PATH})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one tick evaluation and exit (useful for testing and cron runners)",
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

    scheduler = SchedulerService(
        db_path=parsed.db_path,
        poll_interval_seconds=parsed.poll_interval,
    )

    if parsed.once:
        logger.info("Executing single tick evaluation...")
        occurrences = scheduler.tick()
        logger.info("Tick complete; materialized %d occurrences.", len(occurrences))
        return 0

    stop_requested = [False]

    def handle_signal(sig: int, frame: Any) -> None:
        signame = signal.Signals(sig).name
        logger.info("Received signal %s; shutting down scheduler gracefully...", signame)
        stop_requested[0] = True
        scheduler.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Starting scheduler loop (poll_interval=%.2fs)...", parsed.poll_interval)
    scheduler.start()

    try:
        while not stop_requested[0]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; stopping scheduler...")
    finally:
        scheduler.stop()

    logger.info("Scheduler service stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
