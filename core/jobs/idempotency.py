"""core/jobs/idempotency.py

Durable Idempotency Store and Retry Classifier (Task R4.4).
Part of Milestone R4 (Task R4.4 - Idempotency and Retry Model).

Governing Principles:
- Single-Winner Concurrency: SQLite IMMEDIATE transactions serialize reservations;
  identical keys in contention produce exactly one reservation and reject concurrent attempts
  with OperationAlreadyInProgressError.
- Exact Key Derivation: Key is derived deterministically from (job_id, operation_kind, scope, argument_digest)
  and is completely independent of attempt_id.
- Result Reuse: Operations in SUCCEEDED status return cached results without re-executing
  consequential external side effects and emit IDEMPOTENCY_REUSED.
- Outcome Uncertainty Safety: Operations with OUTCOME_UNKNOWN and NON_IDEMPOTENT capability
  are strictly prohibited from automatic retry (raises NonRetryableOperationError and emits IDEMPOTENCY_OUTCOME_UNKNOWN).
- Redaction & Sanitization: Zero secrets, auth tokens, or private credentials stored in
  arguments digest or event metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

from core.jobs.exceptions import (
    IdempotencyConflictError,
    NonRetryableOperationError,
    OperationAlreadyInProgressError,
)
from core.jobs.migrations import apply_job_migrations
from core.jobs.models import (
    IdempotencyRecord,
    IdempotencyRecordStatus,
    JobEventType,
    OperationIdempotencyCapability,
    RetryClassification,
    compute_idempotency_key,
    format_utc_iso,
    parse_utc_iso,
    sanitize_bounded_dict,
)

logger = logging.getLogger("agent_engine.jobs.idempotency")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS_DB_PATH = str(PROJECT_ROOT / "data" / "agent_engine.db")


DISALLOWED_PAYLOAD_KEYS = {
    "body",
    "content",
    "document_text",
    "raw_response",
    "model_output",
    "html",
    "data",
    "text",
    "output",
    "prompt",
    "response_text",
    "file_content",
    "user_data",
}


def minimize_result_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Minimize inline result payload by stripping oversized or private content.

    Data-Minimization Principles:
    - Canonical result_reference is the authoritative location for large outputs.
    - Inline cached payloads must only contain explicitly bounded, non-sensitive
      structured metadata necessary to reconstruct the replay result.
    - Strings exceeding 256 characters or keys matching bulky/user content are excluded.
    - Bounded to at most 10 key-value pairs and 1024 bytes serialized.
    """
    if payload is None:
        return None
    sanitized = sanitize_bounded_dict(payload)
    minimized: Dict[str, Any] = {}
    for k, v in sanitized.items():
        if k.lower() in DISALLOWED_PAYLOAD_KEYS:
            continue
        if isinstance(v, str):
            if len(v) > 256:
                continue
            minimized[k] = v
        elif isinstance(v, (int, float, bool)) or v is None:
            minimized[k] = v
        elif isinstance(v, dict):
            sub = {
                sk: sv
                for sk, sv in v.items()
                if sk.lower() not in DISALLOWED_PAYLOAD_KEYS
                and (not isinstance(sv, str) or len(sv) <= 256)
            }
            if len(sub) <= 5:
                minimized[k] = sub
        if len(minimized) >= 10:
            break

    try:
        dumped = json.dumps(minimized)
        if len(dumped) > 1024:
            return None
    except Exception:
        return None
    return minimized if minimized else None


class IdempotencyStore(ABC):
    """Abstract interface for durable idempotency tracking and result caching."""

    @abstractmethod
    def reconcile_abandoned_records(
        self,
        job_id: str,
        prior_attempt_id: str,
        reconciling_attempt_id: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> int:
        """Transactionally reconcile any abandoned reservations left by a prior crashed attempt."""
        ...

    @abstractmethod
    def reserve_operation(
        self,
        job_id: str,
        operation_kind: str,
        args: Dict[str, Any],
        capability: OperationIdempotencyCapability = OperationIdempotencyCapability.UNKNOWN,
        attempt_id: Optional[str] = None,
        scope: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> Tuple[bool, IdempotencyRecord]:
        """Atomically reserve execution for an operation or return existing record.

        Returns:
            (should_execute, record):
                - (True, record): Operation reserved for execution by this attempt.
                - (False, record): Operation was already SUCCEEDED; result can be reused.

        Raises:
            OperationAlreadyInProgressError: If operation is actively held by another attempt.
            IdempotencyConflictError: If key matches but argument digest differs.
            NonRetryableOperationError: If operation had OUTCOME_UNKNOWN and is NON_IDEMPOTENT.
        """
        ...

    @abstractmethod
    def record_in_progress(
        self,
        idempotency_key: str,
        attempt_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        """Mark a reserved operation as actively in-progress."""
        ...

    @abstractmethod
    def record_success(
        self,
        idempotency_key: str,
        attempt_id: str,
        result_payload: Optional[Dict[str, Any]] = None,
        result_reference: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        """Mark an operation as completed successfully and store cached result."""
        ...

    @abstractmethod
    def record_failure(
        self,
        idempotency_key: str,
        attempt_id: str,
        safe_to_retry: bool = False,
        outcome_unknown: bool = False,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        """Record operation failure and transition to FAILED_SAFE_TO_RETRY or OUTCOME_UNKNOWN."""
        ...

    @abstractmethod
    def get_record(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        """Retrieve idempotency record by key."""
        ...

    @abstractmethod
    def list_records_for_job(self, job_id: str) -> List[IdempotencyRecord]:
        """List all idempotency records associated with a job."""
        ...


class SQLiteIdempotencyStore(IdempotencyStore):
    """SQLite-backed thread-safe implementation of IdempotencyStore."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.db_path = db_path or os.getenv("SQLITE_DB_PATH") or DEFAULT_JOBS_DB_PATH
        self._is_memory = self.db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._clock = clock

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON;")
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_connection()
            apply_job_migrations(conn)
            if not self._is_memory:
                conn.close()

    def _now_dt(self, override: Optional[Union[datetime, str]] = None) -> datetime:
        if override is not None:
            if isinstance(override, str):
                return parse_utc_iso(override)
            if override.tzinfo is None:
                return override.replace(tzinfo=timezone.utc)
            return override.astimezone(timezone.utc)
        if self._clock is not None:
            c = self._clock()
            if c.tzinfo is None:
                return c.replace(tzinfo=timezone.utc)
            return c.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def close(self) -> None:
        with self._lock:
            if self._memory_conn is not None:
                self._memory_conn.close()
                self._memory_conn = None

    def _row_to_record(self, row: sqlite3.Row) -> IdempotencyRecord:
        payload = None
        if row["result_payload_json"]:
            try:
                payload = json.loads(row["result_payload_json"])
            except Exception:
                payload = None

        return IdempotencyRecord(
            idempotency_key=row["idempotency_key"],
            job_id=row["job_id"],
            operation_kind=row["operation_kind"],
            argument_digest=row["argument_digest"],
            capability=OperationIdempotencyCapability(row["capability"]),
            status=IdempotencyRecordStatus(row["status"]),
            claimed_by_attempt=row["claimed_by_attempt"],
            result_reference=row["result_reference"],
            result_payload=payload,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    def _insert_event(
        self,
        cursor: sqlite3.Cursor,
        job_id: str,
        attempt_id: Optional[str],
        event_type: JobEventType,
        metadata: Dict[str, Any],
        timestamp_iso: str,
    ) -> None:
        cursor.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM job_events WHERE job_id = ?",
            (job_id,),
        )
        seq_num = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO job_events (
                event_id, job_id, attempt_id, event_type, sequence_number, timestamp, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"jev_{uuid.uuid4().hex[:12]}",
                job_id,
                attempt_id,
                event_type.value,
                seq_num,
                timestamp_iso,
                json.dumps(sanitize_bounded_dict(metadata)),
            ),
        )

    # --------------------------------------------------------------------------
    # Reservation & Lifecycle Methods
    # --------------------------------------------------------------------------

    def reconcile_abandoned_records(
        self,
        job_id: str,
        prior_attempt_id: str,
        reconciling_attempt_id: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> int:
        """Transactionally reconcile any abandoned reservations left by a prior crashed attempt."""
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT idempotency_key, operation_kind, capability, status
                    FROM job_idempotency_records
                    WHERE job_id = ? AND claimed_by_attempt = ? AND status IN ('reserved', 'in_progress')
                    """,
                    (job_id, prior_attempt_id),
                )
                abandoned_rows = cursor.fetchall()
                count = 0
                for row in abandoned_rows:
                    idem_key = row["idempotency_key"]
                    op_kind = row["operation_kind"]
                    cap = row["capability"]
                    prior_status = row["status"]

                    cursor.execute(
                        """
                        UPDATE job_idempotency_records
                        SET status = ?, updated_at = ?
                        WHERE idempotency_key = ?
                        """,
                        (IdempotencyRecordStatus.OUTCOME_UNKNOWN.value, now_iso, idem_key),
                    )

                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=reconciling_attempt_id or prior_attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_ABANDONED_RECONCILED,
                        metadata={
                            "idempotency_key": idem_key,
                            "operation_kind": op_kind,
                            "prior_attempt_id": prior_attempt_id,
                            "prior_status": prior_status,
                            "reconciling_attempt_id": reconciling_attempt_id,
                            "capability": cap,
                            "resolved_status": IdempotencyRecordStatus.OUTCOME_UNKNOWN.value,
                        },
                        timestamp_iso=now_iso,
                    )
                    count += 1

                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def reserve_operation(
        self,
        job_id: str,
        operation_kind: str,
        args: Dict[str, Any],
        capability: OperationIdempotencyCapability = OperationIdempotencyCapability.UNKNOWN,
        attempt_id: Optional[str] = None,
        scope: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> Tuple[bool, IdempotencyRecord]:
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        idem_key = compute_idempotency_key(job_id, operation_kind, args, scope=scope)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records
                    WHERE idempotency_key = ?
                    """,
                    (idem_key.key,),
                )
                row = cursor.fetchone()

                if not row:
                    # New reservation: insert row with RESERVED status
                    cursor.execute(
                        """
                        INSERT INTO job_idempotency_records (
                            idempotency_key, job_id, operation_kind, argument_digest, capability,
                            status, claimed_by_attempt, result_reference, result_payload_json,
                            created_at, updated_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
                        """,
                        (
                            idem_key.key,
                            job_id,
                            operation_kind,
                            idem_key.argument_digest,
                            capability.value,
                            IdempotencyRecordStatus.RESERVED.value,
                            attempt_id,
                            now_iso,
                            now_iso,
                        ),
                    )

                    # Emit IDEMPOTENCY_RESERVED event
                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_RESERVED,
                        metadata={
                            "idempotency_key": idem_key.key,
                            "operation_kind": operation_kind,
                            "capability": capability.value,
                            "attempt_id": attempt_id,
                        },
                        timestamp_iso=now_iso,
                    )

                    conn.commit()

                    record = IdempotencyRecord(
                        idempotency_key=idem_key.key,
                        job_id=job_id,
                        operation_kind=operation_kind,
                        argument_digest=idem_key.argument_digest,
                        capability=capability,
                        status=IdempotencyRecordStatus.RESERVED,
                        claimed_by_attempt=attempt_id,
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                    return True, record

                # Existing record found
                existing_record = self._row_to_record(row)

                if existing_record.argument_digest != idem_key.argument_digest:
                    conn.rollback()
                    raise IdempotencyConflictError(
                        f"Idempotency key collision or argument conflict for key {idem_key.key}: "
                        f"existing digest {existing_record.argument_digest} != computed {idem_key.argument_digest}"
                    )

                status = existing_record.status

                if status == IdempotencyRecordStatus.SUCCEEDED:
                    # Operation completed previously: emit IDEMPOTENCY_REUSED and return result for reuse
                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_REUSED,
                        metadata={
                            "idempotency_key": idem_key.key,
                            "operation_kind": operation_kind,
                            "reused_from_attempt": existing_record.claimed_by_attempt,
                            "reused_by_attempt": attempt_id,
                        },
                        timestamp_iso=now_iso,
                    )
                    conn.commit()
                    return False, existing_record

                if status in (
                    IdempotencyRecordStatus.RESERVED,
                    IdempotencyRecordStatus.IN_PROGRESS,
                ):
                    if attempt_id and existing_record.claimed_by_attempt == attempt_id:
                        conn.commit()
                        return True, existing_record

                    # Check if claimed_by_attempt is an abandoned attempt
                    prior_attempt_id = existing_record.claimed_by_attempt
                    is_abandoned = False
                    if prior_attempt_id:
                        cursor.execute(
                            "SELECT attempt_id, attempt_number, status, worker_id, lease_generation "
                            "FROM job_attempts WHERE attempt_id = ?",
                            (prior_attempt_id,),
                        )
                        att_row = cursor.fetchone()
                        if att_row:
                            if att_row["status"] in ("failed", "completed"):
                                is_abandoned = True
                            elif attempt_id:
                                cursor.execute(
                                    "SELECT attempt_id, attempt_number, status, worker_id, lease_generation "
                                    "FROM job_attempts WHERE attempt_id = ?",
                                    (attempt_id,),
                                )
                                curr_att_row = cursor.fetchone()
                                if (
                                    curr_att_row
                                    and curr_att_row["attempt_number"] > att_row["attempt_number"]
                                ):
                                    is_abandoned = True

                    if not is_abandoned:
                        conn.rollback()
                        raise OperationAlreadyInProgressError(
                            f"Operation '{operation_kind}' with idempotency key '{idem_key.key}' is already "
                            f"in progress (status={status.value}) by attempt '{existing_record.claimed_by_attempt}'."
                        )

                    # --- Reconcile Abandoned Reservation ---
                    logger.info(
                        "Reconciling abandoned %s idempotency record %s held by dead attempt %s",
                        status.value,
                        idem_key.key,
                        prior_attempt_id,
                    )

                    effective_cap = (
                        capability
                        if capability != OperationIdempotencyCapability.UNKNOWN
                        else existing_record.capability
                    )

                    # 1. Update record status to OUTCOME_UNKNOWN (preserving uncertainty)
                    cursor.execute(
                        """
                        UPDATE job_idempotency_records
                        SET status = ?, updated_at = ?
                        WHERE idempotency_key = ?
                        """,
                        (
                            IdempotencyRecordStatus.OUTCOME_UNKNOWN.value,
                            now_iso,
                            idem_key.key,
                        ),
                    )

                    # 2. Append IDEMPOTENCY_ABANDONED_RECONCILED audit event
                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_ABANDONED_RECONCILED,
                        metadata={
                            "idempotency_key": idem_key.key,
                            "operation_kind": operation_kind,
                            "prior_attempt_id": prior_attempt_id,
                            "prior_status": status.value,
                            "reconciling_attempt_id": attempt_id,
                            "capability": effective_cap.value,
                            "resolved_status": IdempotencyRecordStatus.OUTCOME_UNKNOWN.value,
                        },
                        timestamp_iso=now_iso,
                    )

                    # 3. Classify retry decision according to capability
                    if effective_cap in (
                        OperationIdempotencyCapability.NATIVE_KEY,
                        OperationIdempotencyCapability.NATURALLY_IDEMPOTENT,
                    ):
                        cursor.execute(
                            """
                            UPDATE job_idempotency_records
                            SET status = ?, claimed_by_attempt = ?, updated_at = ?
                            WHERE idempotency_key = ?
                            """,
                            (
                                IdempotencyRecordStatus.RESERVED.value,
                                attempt_id,
                                now_iso,
                                idem_key.key,
                            ),
                        )
                        self._insert_event(
                            cursor=cursor,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            event_type=JobEventType.IDEMPOTENCY_RESERVED,
                            metadata={
                                "idempotency_key": idem_key.key,
                                "operation_kind": operation_kind,
                                "capability": effective_cap.value,
                                "attempt_id": attempt_id,
                                "reconciled_retry": True,
                            },
                            timestamp_iso=now_iso,
                        )
                        conn.commit()

                        existing_record.status = IdempotencyRecordStatus.RESERVED
                        existing_record.claimed_by_attempt = attempt_id
                        existing_record.updated_at = now_iso
                        return True, existing_record

                    elif effective_cap == OperationIdempotencyCapability.AE_GUARDED:
                        if existing_record.result_reference:
                            conn.commit()
                            return False, existing_record
                        cursor.execute(
                            """
                            UPDATE job_idempotency_records
                            SET status = ?, claimed_by_attempt = ?, updated_at = ?
                            WHERE idempotency_key = ?
                            """,
                            (
                                IdempotencyRecordStatus.RESERVED.value,
                                attempt_id,
                                now_iso,
                                idem_key.key,
                            ),
                        )
                        conn.commit()
                        existing_record.status = IdempotencyRecordStatus.RESERVED
                        existing_record.claimed_by_attempt = attempt_id
                        existing_record.updated_at = now_iso
                        return True, existing_record

                    else:
                        self._insert_event(
                            cursor=cursor,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            event_type=JobEventType.IDEMPOTENCY_OUTCOME_UNKNOWN,
                            metadata={
                                "idempotency_key": idem_key.key,
                                "operation_kind": operation_kind,
                                "capability": effective_cap.value,
                                "attempt_id": attempt_id,
                                "prohibited": True,
                                "reason": "abandoned_by_prior_attempt",
                            },
                            timestamp_iso=now_iso,
                        )
                        conn.commit()

                        raise NonRetryableOperationError(
                            f"Automatic retry prohibited for operation '{operation_kind}' (key {idem_key.key}): "
                            f"prior attempt '{prior_attempt_id}' abandoned the operation with outcome UNKNOWN, "
                            f"and capability '{effective_cap.value}' does not permit blind retry."
                        )

                if status == IdempotencyRecordStatus.FAILED_SAFE_TO_RETRY:
                    # Clean failure: re-reserve for this attempt
                    cursor.execute(
                        """
                        UPDATE job_idempotency_records
                        SET status = ?, claimed_by_attempt = ?, updated_at = ?
                        WHERE idempotency_key = ?
                        """,
                        (
                            IdempotencyRecordStatus.RESERVED.value,
                            attempt_id,
                            now_iso,
                            idem_key.key,
                        ),
                    )

                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_RESERVED,
                        metadata={
                            "idempotency_key": idem_key.key,
                            "operation_kind": operation_kind,
                            "capability": capability.value,
                            "attempt_id": attempt_id,
                            "retry": True,
                        },
                        timestamp_iso=now_iso,
                    )
                    conn.commit()

                    existing_record.status = IdempotencyRecordStatus.RESERVED
                    existing_record.claimed_by_attempt = attempt_id
                    existing_record.updated_at = now_iso
                    return True, existing_record

                if status == IdempotencyRecordStatus.OUTCOME_UNKNOWN:
                    effective_cap = (
                        capability
                        if capability != OperationIdempotencyCapability.UNKNOWN
                        else existing_record.capability
                    )

                    if effective_cap in (
                        OperationIdempotencyCapability.NATIVE_KEY,
                        OperationIdempotencyCapability.AE_GUARDED,
                        OperationIdempotencyCapability.NATURALLY_IDEMPOTENT,
                    ):
                        # Capable of safe retries despite unknown outcome
                        cursor.execute(
                            """
                            UPDATE job_idempotency_records
                            SET status = ?, claimed_by_attempt = ?, updated_at = ?
                            WHERE idempotency_key = ?
                            """,
                            (
                                IdempotencyRecordStatus.RESERVED.value,
                                attempt_id,
                                now_iso,
                                idem_key.key,
                            ),
                        )
                        self._insert_event(
                            cursor=cursor,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            event_type=JobEventType.IDEMPOTENCY_RESERVED,
                            metadata={
                                "idempotency_key": idem_key.key,
                                "operation_kind": operation_kind,
                                "capability": effective_cap.value,
                                "attempt_id": attempt_id,
                                "retry_after_unknown": True,
                            },
                            timestamp_iso=now_iso,
                        )
                        conn.commit()

                        existing_record.status = IdempotencyRecordStatus.RESERVED
                        existing_record.claimed_by_attempt = attempt_id
                        existing_record.updated_at = now_iso
                        return True, existing_record

                    # NON_IDEMPOTENT or UNKNOWN: Strictly prohibited from retrying!
                    self._insert_event(
                        cursor=cursor,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_OUTCOME_UNKNOWN,
                        metadata={
                            "idempotency_key": idem_key.key,
                            "operation_kind": operation_kind,
                            "capability": effective_cap.value,
                            "attempt_id": attempt_id,
                            "prohibited": True,
                        },
                        timestamp_iso=now_iso,
                    )
                    conn.commit()

                    raise NonRetryableOperationError(
                        f"Automatic retry prohibited for operation '{operation_kind}' (key {idem_key.key}): "
                        f"outcome is UNKNOWN and capability '{effective_cap.value}' does not permit blind retry."
                    )

                conn.rollback()
                raise NonRetryableOperationError(
                    f"Operation '{operation_kind}' with key '{idem_key.key}' has terminal status '{status.value}'."
                )

            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def record_in_progress(
        self,
        idempotency_key: str,
        attempt_id: str,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE job_idempotency_records
                    SET status = ?, updated_at = ?
                    WHERE idempotency_key = ? AND claimed_by_attempt = ?
                    """,
                    (
                        IdempotencyRecordStatus.IN_PROGRESS.value,
                        now_iso,
                        idempotency_key,
                        attempt_id,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    raise ValueError(
                        f"Cannot mark in-progress: record {idempotency_key} not held by attempt {attempt_id}."
                    )

                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                conn.commit()
                return self._row_to_record(row)
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def record_success(
        self,
        idempotency_key: str,
        attempt_id: str,
        result_payload: Optional[Dict[str, Any]] = None,
        result_reference: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        canonical_reference = (
            result_reference
            if (result_reference is not None and result_reference.strip())
            else f"ref://idempotency/{idempotency_key}"
        )
        minimized_payload = (
            minimize_result_payload(result_payload) if result_payload is not None else None
        )
        payload_json = json.dumps(minimized_payload) if minimized_payload is not None else None

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE job_idempotency_records
                    SET status = ?, result_payload_json = ?, result_reference = ?,
                        completed_at = ?, updated_at = ?
                    WHERE idempotency_key = ? AND claimed_by_attempt = ?
                    """,
                    (
                        IdempotencyRecordStatus.SUCCEEDED.value,
                        payload_json,
                        canonical_reference,
                        now_iso,
                        now_iso,
                        idempotency_key,
                        attempt_id,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    raise ValueError(
                        f"Cannot record success: record {idempotency_key} not held by attempt {attempt_id}."
                    )

                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                conn.commit()
                return self._row_to_record(row)
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def record_failure(
        self,
        idempotency_key: str,
        attempt_id: str,
        safe_to_retry: bool = False,
        outcome_unknown: bool = False,
        now: Optional[Union[datetime, str]] = None,
    ) -> IdempotencyRecord:
        now_dt = self._now_dt(override=now)
        now_iso = format_utc_iso(now_dt)

        if outcome_unknown:
            new_status = IdempotencyRecordStatus.OUTCOME_UNKNOWN
        elif safe_to_retry:
            new_status = IdempotencyRecordStatus.FAILED_SAFE_TO_RETRY
        else:
            new_status = IdempotencyRecordStatus.OUTCOME_UNKNOWN

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE job_idempotency_records
                    SET status = ?, updated_at = ?
                    WHERE idempotency_key = ? AND claimed_by_attempt = ?
                    """,
                    (
                        new_status.value,
                        now_iso,
                        idempotency_key,
                        attempt_id,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    raise ValueError(
                        f"Cannot record failure: record {idempotency_key} not held by attempt {attempt_id}."
                    )

                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                )
                row = cursor.fetchone()

                if new_status == IdempotencyRecordStatus.OUTCOME_UNKNOWN:
                    self._insert_event(
                        cursor=cursor,
                        job_id=row["job_id"],
                        attempt_id=attempt_id,
                        event_type=JobEventType.IDEMPOTENCY_OUTCOME_UNKNOWN,
                        metadata={
                            "idempotency_key": idempotency_key,
                            "operation_kind": row["operation_kind"],
                            "capability": row["capability"],
                            "attempt_id": attempt_id,
                        },
                        timestamp_iso=now_iso,
                    )

                conn.commit()
                return self._row_to_record(row)
            except Exception:
                conn.rollback()
                raise
            finally:
                if not self._is_memory:
                    conn.close()

    def get_record(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                return self._row_to_record(row) if row else None
            finally:
                if not self._is_memory:
                    conn.close()

    def list_records_for_job(self, job_id: str) -> List[IdempotencyRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT idempotency_key, job_id, operation_kind, argument_digest, capability,
                           status, claimed_by_attempt, result_reference, result_payload_json,
                           created_at, updated_at, completed_at
                    FROM job_idempotency_records
                    WHERE job_id = ?
                    ORDER BY created_at ASC
                    """,
                    (job_id,),
                )
                return [self._row_to_record(row) for row in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    def execute_with_idempotency(
        self,
        job_id: str,
        operation_kind: str,
        args: Dict[str, Any],
        fn: Callable[[], Any],
        capability: OperationIdempotencyCapability = OperationIdempotencyCapability.UNKNOWN,
        attempt_id: Optional[str] = None,
        scope: Optional[str] = None,
        now: Optional[Union[datetime, str]] = None,
    ) -> Any:
        """High-level helper executing a function with durable idempotency guarantee."""
        should_execute, record = self.reserve_operation(
            job_id=job_id,
            operation_kind=operation_kind,
            args=args,
            capability=capability,
            attempt_id=attempt_id,
            scope=scope,
            now=now,
        )

        if not should_execute:
            if record.result_payload is not None:
                return record.result_payload
            return record.result_reference

        self.record_in_progress(record.idempotency_key, attempt_id=attempt_id or "", now=now)

        try:
            res = fn()
            payload = res if isinstance(res, dict) else {"result": res}
            self.record_success(
                record.idempotency_key,
                attempt_id=attempt_id or "",
                result_payload=payload,
                now=now,
            )
            return res
        except Exception:
            self.record_failure(
                record.idempotency_key,
                attempt_id=attempt_id or "",
                outcome_unknown=True,
                now=now,
            )
            raise


def classify_failure(
    error: Union[Exception, str, None],
    error_code: Optional[str] = None,
    capability: Optional[OperationIdempotencyCapability] = None,
    outcome_unknown: bool = False,
) -> RetryClassification:
    """Classify execution failure into structured RetryClassification."""
    if isinstance(error, NonRetryableOperationError):
        return RetryClassification.NON_RETRYABLE

    if outcome_unknown and capability in (
        OperationIdempotencyCapability.NON_IDEMPOTENT,
        OperationIdempotencyCapability.UNKNOWN,
    ):
        return RetryClassification.NON_RETRYABLE

    if outcome_unknown:
        return RetryClassification.OUTCOME_UNKNOWN

    code_str = (error_code or "").lower()
    if code_str in ("policy_blocked", "permission_denied", "unauthorized"):
        return RetryClassification.POLICY_BLOCKED

    if code_str in ("non_retryable", "invalid_argument", "validation_error"):
        return RetryClassification.NON_RETRYABLE

    err_str = str(error).lower() if error else ""
    if "non-retryable" in err_str or "validation" in err_str:
        return RetryClassification.NON_RETRYABLE

    return RetryClassification.RETRYABLE
