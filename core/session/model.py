"""Unified session and message domain models.

Provides cross-agent unified data structures for sessions, messages, participants,
tool executions, and branching across the Agent Engine ecosystem.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    AGENT = "agent"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    CLOSED = "closed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolCall:
    """Represents a tool or function invocation executed during a conversation turn."""

    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:10]}")
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    status: str = "success"  # "pending", "success", "failed"
    error: Optional[str] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "status": self.status,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(
            call_id=data.get("call_id") or f"call_{uuid.uuid4().hex[:10]}",
            tool_name=data.get("tool_name", ""),
            arguments=data.get("arguments") or {},
            result=data.get("result"),
            status=data.get("status", "success"),
            error=data.get("error"),
            latency_ms=data.get("latency_ms"),
        )


@dataclass
class AgentParticipant:
    """Represents an agent or human participant collaborating within a session."""

    agent_id: str
    agent_name: str
    role: str = "assistant"  # "primary", "assistant", "critic", "tool_executor", "observer"
    model: Optional[str] = None
    joined_at: str = field(default_factory=_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "role": self.role,
            "model": self.model,
            "joined_at": self.joined_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentParticipant":
        return cls(
            agent_id=data.get("agent_id", "unknown_agent"),
            agent_name=data.get("agent_name", "Unknown Agent"),
            role=data.get("role", "assistant"),
            model=data.get("model"),
            joined_at=data.get("joined_at") or _now_iso(),
            metadata=data.get("metadata") or {},
        )


@dataclass
class UnifiedMessage:
    """Canonical message model shared across all agents, pipelines, and adapters."""

    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    role: str = MessageRole.USER.value  # "user", "assistant", "system", "tool", "agent"
    content: str = ""
    sender_id: str = "user"
    sender_name: Optional[str] = None
    agent_id: Optional[str] = None
    model: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    tokens: Optional[Dict[str, int]] = None  # {"prompt": int, "completion": int, "total": int}
    cost_usd: Optional[float] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "agent_id": self.agent_id,
            "model": self.model,
            "timestamp": self.timestamp,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMessage":
        tcs_raw = data.get("tool_calls") or []
        tool_calls = [tc if isinstance(tc, ToolCall) else ToolCall.from_dict(tc) for tc in tcs_raw]
        return cls(
            message_id=data.get("message_id") or f"msg_{uuid.uuid4().hex[:12]}",
            session_id=data.get("session_id", ""),
            role=data.get("role", MessageRole.USER.value),
            content=data.get("content", ""),
            sender_id=data.get("sender_id", "user"),
            sender_name=data.get("sender_name"),
            agent_id=data.get("agent_id"),
            model=data.get("model"),
            timestamp=data.get("timestamp") or _now_iso(),
            tokens=data.get("tokens"),
            cost_usd=data.get("cost_usd"),
            tool_calls=tool_calls,
            metadata=data.get("metadata") or {},
        )


@dataclass
class UnifiedSession:
    """Canonical cross-agent session containing participants, branching, and message history."""

    session_id: str
    title: str = "Untitled Session"
    user_id: str = "default_user"
    tenant_id: str = "default"
    channel: str = "web"  # "web", "desktop", "slack", "teams", "whatsapp", "telegram", "cli", "api"
    status: str = SessionStatus.ACTIVE.value
    parent_session_id: Optional[str] = None
    fork_point_message_id: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    summary: Optional[str] = None
    participants: List[AgentParticipant] = field(default_factory=list)
    messages: List[UnifiedMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_messages(self) -> int:
        return len(self.messages)

    @property
    def total_tokens(self) -> int:
        total = 0
        for m in self.messages:
            if m.tokens:
                total += m.tokens.get("total", 0)
        return total

    @property
    def total_cost_usd(self) -> float:
        return sum((m.cost_usd or 0.0) for m in self.messages)

    def add_participant(self, participant: AgentParticipant) -> None:
        """Register or update an agent participant in this session."""
        for idx, existing in enumerate(self.participants):
            if existing.agent_id == participant.agent_id:
                self.participants[idx] = participant
                return
        self.participants.append(participant)

    def get_participant(self, agent_id: str) -> Optional[AgentParticipant]:
        """Find participant by agent ID."""
        for p in self.participants:
            if p.agent_id == agent_id:
                return p
        return None

    def append_message(self, message: UnifiedMessage) -> None:
        """Append a message to the session and update the session's updated_at timestamp."""
        if not message.session_id:
            message.session_id = self.session_id
        self.messages.append(message)
        self.updated_at = _now_iso()

        # Auto-register sender as participant if agent_id is provided
        if message.agent_id and not self.get_participant(message.agent_id):
            self.add_participant(
                AgentParticipant(
                    agent_id=message.agent_id,
                    agent_name=message.sender_name or message.agent_id,
                    role="assistant",
                    model=message.model,
                )
            )

    def get_message(self, message_id: str) -> Optional[UnifiedMessage]:
        """Retrieve a specific message by its ID."""
        for m in self.messages:
            if m.message_id == message_id:
                return m
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "channel": self.channel,
            "status": self.status,
            "parent_session_id": self.parent_session_id,
            "fork_point_message_id": self.fork_point_message_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "participants": [p.to_dict() for p in self.participants],
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "total_messages": self.total_messages,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedSession":
        parts_raw = data.get("participants") or []
        participants = [
            p if isinstance(p, AgentParticipant) else AgentParticipant.from_dict(p)
            for p in parts_raw
        ]

        msgs_raw = data.get("messages") or []
        messages = [
            m if isinstance(m, UnifiedMessage) else UnifiedMessage.from_dict(m) for m in msgs_raw
        ]

        return cls(
            session_id=data.get("session_id", ""),
            title=data.get("title", "Untitled Session"),
            user_id=data.get("user_id", "default_user"),
            tenant_id=data.get("tenant_id", "default"),
            channel=data.get("channel", "web"),
            status=data.get("status", SessionStatus.ACTIVE.value),
            parent_session_id=data.get("parent_session_id"),
            fork_point_message_id=data.get("fork_point_message_id"),
            created_at=data.get("created_at") or _now_iso(),
            updated_at=data.get("updated_at") or _now_iso(),
            summary=data.get("summary"),
            participants=participants,
            messages=messages,
            metadata=data.get("metadata") or {},
        )
