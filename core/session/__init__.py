"""Unified session package for Agent Engine.

Provides a cross-agent unified session model, participant management, message branching,
format converters, and high-level session persistence.
"""

from core.session.converters import (
    from_openai_messages,
    to_anthropic_messages,
    to_dspy_history,
    to_jsonl,
    to_markdown,
    to_openai_messages,
)
from core.session.model import (
    AgentParticipant,
    MessageRole,
    SessionStatus,
    ToolCall,
    UnifiedMessage,
    UnifiedSession,
)
from core.session.store import (
    UnifiedSessionStore,
    get_session_store,
    reset_session_store,
)

__all__ = [
    "UnifiedSession",
    "UnifiedMessage",
    "AgentParticipant",
    "ToolCall",
    "MessageRole",
    "SessionStatus",
    "UnifiedSessionStore",
    "get_session_store",
    "reset_session_store",
    "to_openai_messages",
    "from_openai_messages",
    "to_anthropic_messages",
    "to_dspy_history",
    "to_markdown",
    "to_jsonl",
]
