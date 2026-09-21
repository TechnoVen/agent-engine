import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    """Recursively normalize data structures for deterministic serialization."""
    if isinstance(val, dict):
        return {
            str(k): normalize_for_digest(v)
            for k, v in sorted(val.items(), key=lambda item: str(item[0]))
        }
    elif isinstance(val, (list, tuple)):
        return [normalize_for_digest(x) for x in val]
    elif isinstance(val, set):
        return sorted([normalize_for_digest(x) for x in val], key=lambda x: str(x))
    elif isinstance(val, (int, float, bool, str)) or val is None:
        return val
    else:
        return str(val)


def compute_operation_digest(
    tool_name: str,
    tool_args: Dict[str, Any],
    execution_id: Optional[str] = None,
) -> str:
    """
    Compute a deterministic SHA-256 digest binding tool name, normalized arguments,
    and optional execution ID.
    """
    payload: Dict[str, Any] = {
        "tool_name": str(tool_name).strip(),
        "tool_args": normalize_for_digest(tool_args),
    }
    if execution_id:
        payload["execution_id"] = str(execution_id).strip()
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


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
    approval_token: Optional[str] = None
    actor: Optional[str] = None
    decision_reason: Optional[str] = None
    digest: Optional[str] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        current_time = now if now is not None else time.time()
        return current_time > self.expires_at

    def to_dict(self, redact: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if redact:
            data["tool_args"] = redact_sensitive_data(data["tool_args"])
            if data.get("diff"):
                data["diff"] = redact_sensitive_data(data["diff"])
        return data

    def to_public_dict(self) -> Dict[str, Any]:
        """Return public representation with sensitive argument values redacted."""
        return self.to_dict(redact=True)


class PendingOperationRegistry:
    """
    Centralized server-side registry of high-risk pending tool operations.
    Enforces:
    - 60-second expiration window
    - Cryptographic argument binding via SHA-256 digest
    - Single-use, one-time execution token consumption
    - Fail-closed security boundary
    """

    def __init__(self, default_ttl_seconds: float = 60.0):
        self.default_ttl_seconds = default_ttl_seconds
        self._lock = threading.RLock()
        self._operations: Dict[str, PendingOperation] = {}
        self._token_map: Dict[str, str] = {}  # approval_token -> operation_id

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
    ) -> str:
        return compute_operation_digest(tool_name, tool_args, execution_id)

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
    ) -> PendingOperation:
        with self._lock:
            op_id = f"op_{uuid.uuid4().hex[:12]}"
            args_hash = self.compute_args_hash(tool_args)
            digest = self.compute_operation_digest(tool_name, tool_args, execution_id)
            now = time.time()
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
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
            )
            self._operations[op_id] = op
            return op

    def get_operation(self, operation_id: str) -> Optional[PendingOperation]:
        with self._lock:
            op = self._operations.get(operation_id)
            if not op:
                return None
            if op.status == "pending" and op.is_expired():
                op.status = "expired"
            return op

    def list_operations(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[PendingOperation]:
        with self._lock:
            now = time.time()
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
        actor: str = "operator",
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
                raise OperationExpiredError(f"Operation '{operation_id}' has expired (>60s limit)")
            if op.status != "pending":
                raise ValueError(f"Cannot approve operation in state '{op.status}'")

            if modified_args is not None:
                op.tool_args = modified_args
                op.args_hash = self.compute_args_hash(modified_args)
                op.digest = self.compute_operation_digest(
                    op.tool_name, modified_args, op.execution_id or execution_id
                )

            if execution_id is not None and not op.execution_id:
                op.execution_id = execution_id
                op.digest = self.compute_operation_digest(op.tool_name, op.tool_args, execution_id)

            # Generate cryptographically secure single-use token bound to operation_id & args_hash
            raw_token = secrets.token_hex(16)
            token = f"tok_{raw_token}_{op.args_hash[:12]}"

            op.status = "approved"
            op.approval_token = token
            op.actor = actor
            op.decision_reason = f"Approved by {actor}"
            self._token_map[token] = operation_id
            return op, token

    def reject_operation(
        self,
        operation_id: str,
        actor: str = "operator",
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
                raise OperationExpiredError(f"Operation '{operation_id}' has expired")
            if op.status != "pending":
                raise ValueError(f"Cannot reject operation in state '{op.status}'")

            op.status = "rejected"
            op.actor = actor
            op.decision_reason = reason
            return op

    def consume_token(
        self,
        approval_token: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        execution_id: Optional[str] = None,
    ) -> PendingOperation:
        """
        Validate and immediately consume a single-use execution token.
        Fails closed with SecurityBoundaryViolation if token is missing, invalid,
        expired, replayed, or arguments/execution_id do not cryptographically match.
        """
        with self._lock:
            if not approval_token or not isinstance(approval_token, str):
                raise SecurityBoundaryViolation("Invalid or missing approval token")

            op_id = self._token_map.get(approval_token)
            if not op_id:
                raise SecurityBoundaryViolation("Invalid or unknown approval token")

            op = self._operations.get(op_id)
            if not op:
                raise SecurityBoundaryViolation("Referenced operation does not exist")

            # Check status
            if op.status == "consumed":
                raise SecurityBoundaryViolation(
                    "Approval token has already been consumed (replay attack detected)"
                )
            if op.status == "rejected":
                raise SecurityBoundaryViolation(f"Cannot consume rejected operation '{op_id}'")
            if op.status != "approved":
                raise SecurityBoundaryViolation(
                    f"Operation is in non-executable state: {op.status}"
                )

            # Check expiration
            if op.is_expired():
                op.status = "expired"
                raise SecurityBoundaryViolation("Approval token has expired (>60s limit)")

            # Constant-time token verification against bound token
            if not op.approval_token or not hmac.compare_digest(approval_token, op.approval_token):
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

            # Cryptographic argument verification
            incoming_hash = self.compute_args_hash(tool_args)
            if not hmac.compare_digest(incoming_hash, op.args_hash):
                raise SecurityBoundaryViolation(
                    "Cryptographic argument verification failed: tool arguments do not match approved digest"
                )

            # Burn the token atomically
            op.status = "consumed"
            return op


_pending_registry: Optional[PendingOperationRegistry] = None
_registry_lock = threading.Lock()


def get_pending_registry() -> PendingOperationRegistry:
    global _pending_registry
    if _pending_registry is None:
        with _registry_lock:
            if _pending_registry is None:
                _pending_registry = PendingOperationRegistry()
    return _pending_registry
