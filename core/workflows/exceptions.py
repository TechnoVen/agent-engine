"""core/workflows/exceptions.py

Domain exceptions for the Canonical Workflow Domain (Task R4.8).
Part of Milestone R4 (Task R4.8 - Absorb Legacy Phase 7 Runtime).
"""

from __future__ import annotations

from core.jobs.exceptions import JobDomainError


class WorkflowDomainError(JobDomainError):
    """Base exception for all workflow domain errors."""


class WorkflowNotFoundError(WorkflowDomainError):
    """Raised when a referenced workflow definition does not exist."""


class WorkflowRunNotFoundError(WorkflowDomainError):
    """Raised when a referenced workflow run instance does not exist."""


class WorkflowValidationError(WorkflowDomainError):
    """Raised when workflow schema, nodes, edges, or configuration are invalid."""


class WorkflowCycleError(WorkflowValidationError):
    """Raised when a workflow graph contains a directed dependency cycle."""


class WorkflowStateError(WorkflowDomainError):
    """Raised when an operation is invalid for the current workflow run state."""


class WorkflowExecutionError(WorkflowDomainError):
    """Raised when workflow coordination or step dispatch fails."""
