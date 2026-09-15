import logging
from typing import Any, Dict, List, Optional

from core.storage import get_storage_backend

logger = logging.getLogger("agent_engine.safety.audit")


class AuditLogger:
    """
    Central safety audit logger for tool calls, risk evaluations, and policy enforcement decisions.
    Persists records to configured StorageBackend (SQLite / Postgres).
    """

    def __init__(self, storage=None):
        self._storage = storage

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_backend()
        return self._storage

    def log_evaluation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        decision: str,
        risk_level: str,
        risk_score: float,
        policy_id: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """
        Record a safety evaluation event in the persistent audit log table.
        """
        try:
            record_id = self.storage.record_audit_log(
                tool_name=tool_name,
                tool_args=tool_args,
                decision=decision,
                risk_level=risk_level,
                risk_score=risk_score,
                policy_id=policy_id,
                reason=reason,
                suggestion=suggestion,
                session_id=session_id,
            )
            logger.info(
                "Safety audit event logged [#%s]: tool=%s decision=%s risk=%s score=%.2f",
                record_id,
                tool_name,
                decision,
                risk_level,
                risk_score,
            )
            return record_id
        except Exception as e:
            logger.error("Failed to log safety audit event: %s", e)
            return -1

    def list_logs(
        self,
        limit: int = 50,
        offset: int = 0,
        decision: Optional[str] = None,
        risk_level: Optional[str] = None,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent safety audit logs with filtering and pagination.
        """
        try:
            return self.storage.list_audit_logs(
                limit=limit,
                offset=offset,
                decision=decision,
                risk_level=risk_level,
                tool_name=tool_name,
                session_id=session_id,
            )
        except Exception as e:
            logger.error("Failed to list safety audit logs: %s", e)
            return []

    def count_logs(
        self,
        decision: Optional[str] = None,
        risk_level: Optional[str] = None,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """
        Count total matching safety audit logs.
        """
        try:
            return self.storage.count_audit_logs(
                decision=decision,
                risk_level=risk_level,
                tool_name=tool_name,
                session_id=session_id,
            )
        except Exception as e:
            logger.error("Failed to count safety audit logs: %s", e)
            return 0
