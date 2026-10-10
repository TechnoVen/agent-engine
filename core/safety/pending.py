from __future__ import annotations

import decimal
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

OPERATION_DIGEST_VERSION: int = 1

SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|token|secret|api[_-]?key|auth|authorization|credential|private[_-]?key|cert)",
    re.IGNORECASE,
)


def redact_sensitive_data(val: Any) -> Any:
    """Recursively redact sensitive fields from a data structure for audit/presentation."""
    if isinstance(val, dict):
        redacted = {}
        for k, v in val.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_sensitive_data(v)
        return redacted
    elif isinstance(val, (list, tuple)):
        return [redact_sensitive_data(x) for x in val]
    elif isinstance(val, set):
        return {redact_sensitive_data(x) for x in val}
    return val


def normalize_for_digest(val: Any) -> Any:
    """Recursively normalize data structures for deterministic canonical serialization."""
    if isinstance(val, dict):
        return {
            str(k): normalize_for_digest(v)
            for k, v in sorted(val.items(), key=lambda item: str(item[0]))
        }
    elif isinstance(val, (list, tuple)):
        return [normalize_for_digest(x) for x in val]
    elif isinstance(val, set):
        return sorted([normalize_for_digest(x) for x in val], key=lambda x: str(x))
    elif isinstance(val, bool):
        return val
    elif isinstance(val, int):
        return val
    elif isinstance(val, float):
        return f"{val:.8f}".rstrip("0").rstrip(".")
    elif isinstance(val, decimal.Decimal):
        return str(val)
    elif isinstance(val, Path):
        return str(val.as_posix())
    elif val is None:
        return None
    else:
        return unicodedata.normalize("NFC", str(val))


def compute_canonical_operation_digest(
    tool_name: str,
    tool_args: Dict[str, Any],
    capability: Optional[str] = None,
    execution_id: Optional[str] = None,
    actor: Optional[str] = None,
    version: int = OPERATION_DIGEST_VERSION,
) -> str:
    """Compute a deterministic versioned SHA-256 digest binding version, capability,

    operation, normalized arguments, execution binding, and actor binding.
    """
    payload: Dict[str, Any] = {
        "actor_binding": str(actor).strip() if actor else "local_operator",
        "capability": str(capability or tool_name).strip(),
        "execution_binding": str(execution_id).strip() if execution_id else None,
        "normalized_arguments": normalize_for_digest(tool_args),
        "operation": str(tool_name).strip(),
        "version": int(version),
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_operation_digest(
    tool_name: str,
    tool_args: Dict[str, Any],
    execution_id: Optional[str] = None,
    actor: Optional[str] = None,
    capability: Optional[str] = None,
) -> str:
    """Backward-compatible wrapper for compute_canonical_operation_digest."""
    return compute_canonical_operation_digest(
        tool_name=tool_name,
        tool_args=tool_args,
        capability=capability,
        execution_id=execution_id,
        actor=actor,
    )


class OperationExpiredError(Exception):
    """Raised when attempting an action on an expired operation."""


class SecurityBoundaryViolation(Exception):
    """Raised when an unauthorized or invalid execution token is presented."""


@dataclass
class PendingOperation:
    operation_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    args_hash: str
    risk_level: str  # low, medium, high, critical
    risk_score: float
    status: str  # pending, approved, rejected, expired, consumed
    created_at: float
    expires_at: float
    session_id: Optional[str] = None
    execution_id: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    diff: Optional[Dict[str, Any]] = None
    token_verifier: Optional[str] = None  # SHA-256 verifier, never raw bearer secret
    actor: Optional[str] = None
    decision_reason: Optional[str] = None
    digest: Optional[str] = None
    digest_version: int = OPERATION_DIGEST_VERSION
    capability: Optional[str] = None
    consumed_at: Optional[float] = None

    @property
    def approval_token(self) -> Optional[str]:
        # Ephemeral raw bearer secret is never stored on the record
        return None

    def is_expired(self, now: Optional[float] = None) -> bool:
        current_time = now if now is not None else time.time()
        return current_time > self.expires_at

    def to_dict(self, redact: bool = False) -> Dict[str, Any]:
        data = {
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "tool_args": redact_sensitive_data(self.tool_args) if redact else self.tool_args,
            "args_hash": self.args_hash,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "diff": redact_sensitive_data(self.diff) if (redact and self.diff) else self.diff,
            "actor": self.actor,
            "decision_reason": self.decision_reason,
            "digest": self.digest,
            "digest_version": self.digest_version,
            "capability": self.capability,
            "consumed_at": self.consumed_at,
            "token_verifier": self.token_verifier,
        }
        return data

    def to_public_dict(self) -> Dict[str, Any]:
        """Return public representation with sensitive argument values and verifiers omitted."""
        data = self.to_dict(redact=True)
        data.pop("token_verifier", None)
        return data


class PendingOperationRegistry:
    """Centralized server-side registry of high-risk pending tool operations.

    Enforces:
    - Policy-driven bounded expiration window (default 60s)
    - Versioned cryptographic argument binding via SHA-256 digest
    - Single-use, one-time execution token consumption
    - Durable SQLite persistence with atomic CAS consumption
    - Fail-closed security boundary
    """

    def __init__(
        self,
        storage: Optional[Any] = None,
        default_ttl_seconds: float = 60.0,
    ):
        self.storage = storage
        self.default_ttl_seconds = max(0.001, float(default_ttl_seconds))
        self._lock = threading.RLock()
        self._operations: Dict[str, PendingOperation] = {}
        self._verifier_map: Dict[str, str] = {}  # token_verifier -> operation_id

    @staticmethod
    def compute_args_hash(tool_args: Dict[str, Any]) -> str:
        """Compute deterministic SHA-256 digest of canonical tool arguments."""
        normalized = normalize_for_digest(tool_args)
        canonical_json = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_operation_digest(
        tool_name: str,
        tool_args: Dict[str, Any],
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> str:
        return compute_canonical_operation_digest(
            tool_name=tool_name,
            tool_args=tool_args,
            capability=capability,
            execution_id=execution_id,
            actor=actor,
        )

    def _sync_to_storage(self, op: PendingOperation) -> None:
        if self.storage is None:
            return
        try:
            self.storage.save_approval(
                {
                    "approval_id": op.operation_id,
                    "execution_id": op.execution_id,
                    "actor": op.actor or "local_operator",
                    "capability": op.capability or op.tool_name,
                    "operation_digest": op.digest,
                    "digest_version": op.digest_version,
                    "token_verifier": op.token_verifier or "",
                    "issued_at": op.created_at,
                    "expires_at": op.expires_at,
                    "decision": "approved" if op.status == "approved" else op.status,
                    "status": op.status,
                    "consumed_at": op.consumed_at,
                    "metadata": {
                        "tool_name": op.tool_name,
                        "args_hash": op.args_hash,
                        "tool_args": redact_sensitive_data(op.tool_args),
                        "risk_level": op.risk_level,
                        "risk_score": op.risk_score,
                    },
                }
            )
        except Exception as e:
            # If storage sync fails, fail closed
            raise SecurityBoundaryViolation(f"Failed to persist approval to storage: {e}")

    def _load_from_storage_record(self, record: Dict[str, Any]) -> PendingOperation:
        meta = record.get("metadata", {})
        tool_name = meta.get("tool_name") or record.get("capability") or "unknown_tool"
        tool_args = meta.get("tool_args") or {}
        args_hash = meta.get("args_hash") or self.compute_args_hash(tool_args)
        op = PendingOperation(
            operation_id=record["approval_id"],
            tool_name=tool_name,
            tool_args=tool_args,
            args_hash=args_hash,
            risk_level=meta.get("risk_level", "high"),
            risk_score=meta.get("risk_score", 0.85),
            status=record.get("status", "pending"),
            created_at=float(record.get("issued_at", time.time())),
            expires_at=float(record.get("expires_at", time.time() + self.default_ttl_seconds)),
            session_id=meta.get("session_id"),
            execution_id=record.get("execution_id"),
            token_verifier=record.get("token_verifier"),
            actor=record.get("actor", "local_operator"),
            digest=record.get("operation_digest"),
            digest_version=int(record.get("digest_version", OPERATION_DIGEST_VERSION)),
            capability=record.get("capability"),
            consumed_at=float(record["consumed_at"])
            if record.get("consumed_at") is not None
            else None,
        )
        self._operations[op.operation_id] = op
        if op.token_verifier:
            self._verifier_map[op.token_verifier] = op.operation_id
        return op

    def register_operation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        risk_level: str = "high",
        risk_score: float = 0.85,
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[str] = None,
        diff: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[float] = None,
        actor: Optional[str] = "local_operator",
        capability: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> PendingOperation:
        with self._lock:
            op_id = operation_id or f"op_{uuid.uuid4().hex[:12]}"
            args_hash = self.compute_args_hash(tool_args)
            effective_capability = capability or tool_name
            effective_actor = actor or "local_operator"
            digest = compute_canonical_operation_digest(
                tool_name=tool_name,
                tool_args=tool_args,
                capability=effective_capability,
                execution_id=execution_id,
                actor=effective_actor,
                version=OPERATION_DIGEST_VERSION,
            )
            # Check for existing pending operation with identical operation_id and digest (deduplication)
            if operation_id:
                existing = self.get_operation(op_id)
                if (
                    existing
                    and existing.status == "pending"
                    and existing.digest == digest
                    and not existing.is_expired()
                ):
                    return existing
            now = time.time()
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
            if ttl <= 0:
                raise ValueError("Approval TTL must be positive and bounded")
            expires_at = now + ttl

            op = PendingOperation(
                operation_id=op_id,
                tool_name=tool_name,
                tool_args=tool_args,
                args_hash=args_hash,
                risk_level=risk_level,
                risk_score=risk_score,
                status="pending",
                created_at=now,
                expires_at=expires_at,
                session_id=session_id,
                execution_id=execution_id,
                reason=reason,
                suggestion=suggestion,
                diff=diff,
                digest=digest,
                digest_version=OPERATION_DIGEST_VERSION,
                actor=effective_actor,
                capability=effective_capability,
            )
            self._operations[op_id] = op
            self._sync_to_storage(op)
            return op

    def get_operation(self, operation_id: str) -> Optional[PendingOperation]:
        with self._lock:
            op = self._operations.get(operation_id)
            if not op and self.storage:
                db_rec = self.storage.get_approval(operation_id)
                if db_rec:
                    op = self._load_from_storage_record(db_rec)
            if not op:
                return None
            if op.status == "pending" and op.is_expired():
                op.status = "expired"
                self._sync_to_storage(op)
            return op

    def list_operations(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[PendingOperation]:
        with self._lock:
            now = time.time()
            if self.storage:
                db_records = self.storage.list_approvals(status=status)
                for rec in db_records:
                    if rec["approval_id"] not in self._operations:
                        self._load_from_storage_record(rec)

            result = []
            for op in self._operations.values():
                if op.status == "pending" and op.is_expired(now):
                    op.status = "expired"
                if status and op.status != status:
                    continue
                if session_id and op.session_id != session_id:
                    continue
                result.append(op)
            return sorted(result, key=lambda x: x.created_at, reverse=True)

    def approve_operation(
        self,
        operation_id: str,
        actor: str = "local_operator",
        modified_args: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
    ) -> Tuple[PendingOperation, str]:
        with self._lock:
            op = self.get_operation(operation_id)
            if not op:
                raise ValueError(f"Operation '{operation_id}' not found")
            if op.status == "rejected":
                raise ValueError(f"Cannot approve rejected operation '{operation_id}'")
            if op.status == "consumed":
                raise ValueError(f"Cannot approve already consumed operation '{operation_id}'")
            if op.status == "expired" or op.is_expired():
                op.status = "expired"
                self._sync_to_storage(op)
                raise OperationExpiredError(f"Operation '{operation_id}' has expired (>60s limit)")
            if op.status != "pending":
                raise ValueError(f"Cannot approve operation in state '{op.status}'")

            effective_actor = actor or "local_operator"
            if modified_args is not None:
                op.tool_args = modified_args
                op.args_hash = self.compute_args_hash(modified_args)

            if execution_id is not None and not op.execution_id:
                op.execution_id = execution_id

            op.actor = effective_actor
            op.digest = compute_canonical_operation_digest(
                tool_name=op.tool_name,
                tool_args=op.tool_args,
                capability=op.capability or op.tool_name,
                execution_id=op.execution_id,
                actor=effective_actor,
                version=op.digest_version,
            )

            # Generate cryptographically secure single-use bearer token
            raw_token = secrets.token_hex(32)
            bearer_token = f"tok_{raw_token}_{op.digest[:12]}"

            # Store only SHA-256 verifier, never the raw bearer secret!
            token_verifier = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()

            op.status = "approved"
            op.actor = effective_actor
            op.token_verifier = token_verifier
            op.decision_reason = f"Approved by {effective_actor}"
            self._verifier_map[token_verifier] = operation_id
            self._sync_to_storage(op)

            # Return bearer token only to authorized caller
            return op, bearer_token

    def reject_operation(
        self,
        operation_id: str,
        actor: str = "local_operator",
        reason: str = "Rejected by operator",
    ) -> PendingOperation:
        with self._lock:
            op = self.get_operation(operation_id)
            if not op:
                raise ValueError(f"Operation '{operation_id}' not found")
            if op.status == "consumed":
                raise ValueError(f"Cannot reject consumed operation '{operation_id}'")
            if op.status == "expired" or op.is_expired():
                op.status = "expired"
                self._sync_to_storage(op)
                raise OperationExpiredError(f"Operation '{operation_id}' has expired")
            if op.status != "pending":
                raise ValueError(f"Cannot reject operation in state '{op.status}'")

            op.status = "rejected"
            op.actor = actor or "local_operator"
            op.decision_reason = reason
            self._sync_to_storage(op)
            return op

    def consume_token(
        self,
        approval_token: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> PendingOperation:
        """Validate and immediately consume a single-use execution token using atomic CAS.

        Fails closed with SecurityBoundaryViolation if token is missing, invalid,
        expired, replayed, or arguments/execution_id/actor do not cryptographically match.
        """
        with self._lock:
            if not approval_token or not isinstance(approval_token, str):
                raise SecurityBoundaryViolation("Invalid or missing approval token")

            presented_verifier = hashlib.sha256(approval_token.encode("utf-8")).hexdigest()

            op_id = self._verifier_map.get(presented_verifier)
            op: Optional[PendingOperation] = None
            if op_id:
                op = self._operations.get(op_id)

            if not op and self.storage:
                db_rec = self.storage.get_approval_by_verifier(presented_verifier)
                if db_rec:
                    op = self._load_from_storage_record(db_rec)
                    op_id = op.operation_id

            if not op:
                raise SecurityBoundaryViolation("Invalid or unknown approval token")

            # Check status
            if op.status == "consumed":
                raise SecurityBoundaryViolation(
                    "Approval token has already been consumed (replay attack detected)"
                )
            if op.status == "rejected":
                raise SecurityBoundaryViolation(
                    f"Cannot consume rejected operation '{op.operation_id}'"
                )
            if op.status != "approved":
                raise SecurityBoundaryViolation(
                    f"Operation is in non-executable state: {op.status}"
                )

            # Check expiration
            if op.is_expired():
                op.status = "expired"
                self._sync_to_storage(op)
                raise SecurityBoundaryViolation("Approval token has expired (>60s limit)")

            # Constant-time token verification against stored verifier
            if not op.token_verifier or not hmac.compare_digest(
                presented_verifier, op.token_verifier
            ):
                raise SecurityBoundaryViolation("Approval token verification failed")

            # Check tool name
            if op.tool_name != tool_name:
                raise SecurityBoundaryViolation(
                    f"Tool name mismatch: token bound to '{op.tool_name}', got '{tool_name}'"
                )

            # Check execution ID binding if present on operation or caller
            if op.execution_id and execution_id:
                if op.execution_id != execution_id:
                    raise SecurityBoundaryViolation(
                        f"Execution ID mismatch: token bound to execution '{op.execution_id}', got '{execution_id}'"
                    )

            # Check actor binding if explicitly provided by caller
            if (
                actor is not None
                and op.actor is not None
                and not hmac.compare_digest(op.actor, actor)
            ):
                raise SecurityBoundaryViolation(
                    f"Actor mismatch: token bound to actor '{op.actor}', got '{actor}'"
                )

            # Check canonical args hash first
            presented_args_hash = self.compute_args_hash(tool_args)
            if not hmac.compare_digest(presented_args_hash, op.args_hash):
                raise SecurityBoundaryViolation(
                    "Cryptographic argument verification failed: tool arguments do not match approved digest"
                )

            # Rebuild canonical operation representation and recompute exact digest immediately before execution
            incoming_digest = compute_canonical_operation_digest(
                tool_name=tool_name,
                tool_args=tool_args,
                capability=capability or op.capability or tool_name,
                execution_id=op.execution_id,
                actor=op.actor,
                version=op.digest_version,
            )
            if not hmac.compare_digest(incoming_digest, op.digest):
                raise SecurityBoundaryViolation(
                    "Cryptographic argument verification failed: tool arguments do not match approved digest"
                )

            # Atomic database CAS transition
            now = time.time()
            if self.storage is not None:
                consumed = self.storage.atomic_consume_approval(
                    approval_id=op.operation_id,
                    token_verifier=presented_verifier,
                    now=now,
                )
                if not consumed:
                    raise SecurityBoundaryViolation(
                        "Approval token has already been consumed (replay attack detected)"
                    )

            # Burn the token in memory
            op.status = "consumed"
            op.consumed_at = now
            return op

    def consume_exact_approval(
        self,
        approval_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> PendingOperation:
        """Validate and immediately consume an exact approved operation using atomic CAS.

        Fails closed with SecurityBoundaryViolation if approval is missing, invalid,
        non-approved, expired, replayed, or arguments/execution_id/actor do not cryptographically match.
        """
        with self._lock:
            op = self.get_operation(approval_id)
            if not op:
                raise SecurityBoundaryViolation(f"Unknown approval id: '{approval_id}'")

            # Check status
            if op.status == "consumed":
                raise SecurityBoundaryViolation(
                    f"Approval '{approval_id}' has already been consumed (replay attack detected)"
                )
            if op.status == "rejected":
                raise SecurityBoundaryViolation(
                    f"Cannot consume rejected operation '{approval_id}'"
                )
            if op.status != "approved":
                raise SecurityBoundaryViolation(
                    f"Operation '{approval_id}' is in non-executable state: {op.status}"
                )

            # Check expiration
            if op.is_expired():
                op.status = "expired"
                self._sync_to_storage(op)
                raise OperationExpiredError(f"Approval '{approval_id}' has expired")

            # Check tool name
            if op.tool_name != tool_name:
                raise SecurityBoundaryViolation(
                    f"Tool name mismatch: approved '{op.tool_name}', got '{tool_name}'"
                )

            # Check execution ID binding if present
            if op.execution_id and execution_id and op.execution_id != execution_id:
                raise SecurityBoundaryViolation(
                    f"Execution ID mismatch: token bound to execution '{op.execution_id}', got '{execution_id}'"
                )

            # Check actor binding if explicitly provided
            if (
                actor is not None
                and op.actor is not None
                and not hmac.compare_digest(op.actor, actor)
            ):
                raise SecurityBoundaryViolation(
                    f"Actor mismatch: token bound to actor '{op.actor}', got '{actor}'"
                )

            # Verify cryptographic arguments digest
            incoming_digest = compute_canonical_operation_digest(
                tool_name=tool_name,
                tool_args=tool_args,
                capability=capability or op.capability or tool_name,
                execution_id=op.execution_id,
                actor=op.actor,
                version=op.digest_version,
            )
            if not hmac.compare_digest(incoming_digest, op.digest):
                raise SecurityBoundaryViolation(
                    "Cryptographic argument verification failed: tool arguments do not match approved digest"
                )

            # Atomic database CAS transition
            now = time.time()
            if self.storage is not None:
                consumed = self.storage.atomic_consume_approval_exact(
                    approval_id=op.operation_id,
                    expected_digest=op.digest,
                    now=now,
                )
                if not consumed:
                    raise SecurityBoundaryViolation(
                        f"Approval '{approval_id}' has already been consumed or expired (atomic CAS race failed)"
                    )

            # Burn in memory
            op.status = "consumed"
            op.consumed_at = now
            return op


_pending_registry: Optional[PendingOperationRegistry] = None
_registry_lock = threading.Lock()


def get_pending_registry(storage: Optional[Any] = None) -> PendingOperationRegistry:
    global _pending_registry
    if _pending_registry is None:
        with _registry_lock:
            if _pending_registry is None:
                _pending_registry = PendingOperationRegistry(storage=storage)
    elif storage is not None and _pending_registry.storage is None:
        _pending_registry.storage = storage
    return _pending_registry


def reset_pending_registry() -> None:
    global _pending_registry
    with _registry_lock:
        _pending_registry = None
