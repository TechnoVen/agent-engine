"""Unified session store manager.

Coordinates cross-agent session lifecycles, message persistence, branching/forking,
search, and format export/import on top of the underlying StorageBackend repository.
"""

import json
import threading
from typing import Any, Dict, List, Optional, Union
import uuid

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
    _now_iso,
)
from core.storage import StorageBackend, get_storage_backend


class UnifiedSessionStore:
    """High-level session store managing cross-agent collaboration and persistence."""

    def __init__(self, backend: Optional[StorageBackend] = None):
        self.backend = backend or get_storage_backend()
        self._lock = threading.RLock()

    def create_session(
        self,
        session_id: Optional[str] = None,
        title: str = "Untitled Session",
        user_id: str = "default_user",
        tenant_id: str = "default",
        channel: str = "web",
        status: str = SessionStatus.ACTIVE.value,
        metadata: Optional[Dict[str, Any]] = None,
        participants: Optional[List[AgentParticipant]] = None,
    ) -> UnifiedSession:
        """Create and persist a new unified session."""
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        parts = participants or []
        meta = metadata or {}

        session = UnifiedSession(
            session_id=sid,
            title=title,
            user_id=user_id,
            tenant_id=tenant_id,
            channel=channel,
            status=status,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            participants=parts,
            messages=[],
            metadata=meta,
        )

        with self._lock:
            self.backend.create_session(
                session_id=sid,
                user_id=user_id,
                title=title,
                tenant_id=tenant_id,
                channel=channel,
                status=status,
                metadata={
                    **meta,
                    "title": title,
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "status": status,
                    "participants": [p.to_dict() for p in parts],
                },
            )

        return session

    def get_session(self, session_id: str) -> Optional[UnifiedSession]:
        """Retrieve a session by ID and reconstitute it into a UnifiedSession."""
        with self._lock:
            raw = self.backend.get_session(session_id)
            if not raw:
                return None

        return self._reconstitute_session(raw)

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[UnifiedSession]:
        """List sessions with optional filtering by user, tenant, channel, status, and search query."""
        with self._lock:
            raw_list = self.backend.list_sessions(
                user_id=user_id,
                tenant_id=tenant_id,
                channel=channel,
                status=status,
                limit=limit + offset,
            )

        sessions: List[UnifiedSession] = []
        for r in raw_list:
            s = self._reconstitute_session(r)
            if tenant_id and s.tenant_id != tenant_id:
                continue
            if channel and s.channel.lower() != channel.lower():
                continue
            if status and s.status.lower() != status.lower():
                continue
            if query:
                q = query.lower()
                title_match = q in s.title.lower()
                id_match = q in s.session_id.lower()
                tag_match = any(q in str(v).lower() for v in s.metadata.values())
                msg_match = any(q in m.content.lower() for m in s.messages)
                if not (title_match or id_match or tag_match or msg_match):
                    continue
            sessions.append(s)

        # Apply offset and limit
        return sessions[offset : offset + limit]

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[UnifiedSession]:
        """Update session metadata, title, status, or summary."""
        with self._lock:
            raw = self.backend.get_session(session_id)
            if not raw:
                return None

            meta = raw.get("metadata") or {}
            if title is not None:
                meta["title"] = title
            if status is not None:
                meta["status"] = status
            if summary is not None:
                meta["summary"] = summary
            if metadata is not None:
                meta.update(metadata)

            self.backend.update_session(session_id=session_id, metadata=meta)
            updated_raw = self.backend.get_session(session_id)
            return self._reconstitute_session(updated_raw) if updated_raw else None

    def append_message(
        self,
        session_id: str,
        role: str = MessageRole.USER.value,
        content: str = "",
        sender_id: str = "user",
        sender_name: Optional[str] = None,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
        tokens: Optional[Dict[str, int]] = None,
        cost_usd: Optional[float] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UnifiedMessage:
        """Append a new message to a session, updating participant list and metrics."""
        with self._lock:
            raw = self.backend.get_session(session_id)
            if not raw:
                raise ValueError(f"Session '{session_id}' not found")

            session = self._reconstitute_session(raw)
            msg = UnifiedMessage(
                session_id=session_id,
                role=role,
                content=content,
                sender_id=sender_id,
                sender_name=sender_name,
                agent_id=agent_id,
                model=model,
                tokens=tokens,
                cost_usd=cost_usd,
                tool_calls=tool_calls or [],
                metadata=metadata or {},
            )

            session.append_message(msg)

            # Persist updated messages and metadata (which holds participants, title, etc.)
            meta = session.metadata
            meta["title"] = session.title
            meta["tenant_id"] = session.tenant_id
            meta["channel"] = session.channel
            meta["status"] = session.status
            meta["participants"] = [p.to_dict() for p in session.participants]
            if session.summary:
                meta["summary"] = session.summary
            if session.parent_session_id:
                meta["parent_session_id"] = session.parent_session_id
            if session.fork_point_message_id:
                meta["fork_point_message_id"] = session.fork_point_message_id

            msg_dicts = [m.to_dict() for m in session.messages]
            self.backend.update_session(
                session_id=session_id,
                messages=msg_dicts,
                metadata=meta,
            )

            return msg

    def fork_session(
        self,
        session_id: str,
        fork_point_message_id: Optional[str] = None,
        new_title: Optional[str] = None,
        user_id: Optional[str] = None,
        new_session_id: Optional[str] = None,
    ) -> UnifiedSession:
        """Fork an existing session at a specific message point (or latest) into a new branch."""
        with self._lock:
            parent = self.get_session(session_id)
            if not parent:
                raise ValueError(f"Parent session '{session_id}' not found")

            # Determine messages to carry over
            forked_messages: List[UnifiedMessage] = []
            fork_msg_id = fork_point_message_id

            if fork_point_message_id:
                found = False
                for m in parent.messages:
                    forked_messages.append(m)
                    if m.message_id == fork_point_message_id:
                        found = True
                        break
                if not found:
                    raise ValueError(
                        f"Message ID '{fork_point_message_id}' not found in parent session"
                    )
            else:
                forked_messages = list(parent.messages)
                if forked_messages:
                    fork_msg_id = forked_messages[-1].message_id

            target_sid = new_session_id or f"sess_fork_{uuid.uuid4().hex[:10]}"
            target_user = user_id or parent.user_id
            target_title = new_title or f"Fork of {parent.title}"

            forked_session = UnifiedSession(
                session_id=target_sid,
                title=target_title,
                user_id=target_user,
                tenant_id=parent.tenant_id,
                channel=parent.channel,
                status=SessionStatus.ACTIVE.value,
                parent_session_id=session_id,
                fork_point_message_id=fork_msg_id,
                created_at=_now_iso(),
                updated_at=_now_iso(),
                summary=parent.summary,
                participants=list(parent.participants),
                messages=forked_messages,
                metadata={**parent.metadata, "forked_from": session_id},
            )

            # Persist to storage backend
            meta = {
                **forked_session.metadata,
                "title": target_title,
                "tenant_id": parent.tenant_id,
                "channel": parent.channel,
                "status": SessionStatus.ACTIVE.value,
                "parent_session_id": session_id,
                "fork_point_message_id": fork_msg_id,
                "participants": [p.to_dict() for p in forked_session.participants],
            }

            self.backend.create_session(
                session_id=target_sid,
                user_id=target_user,
                metadata=meta,
            )

            if forked_messages:
                self.backend.update_session(
                    session_id=target_sid,
                    messages=[m.to_dict() for m in forked_messages],
                    metadata=meta,
                )

            return forked_session

    def delete_session(self, session_id: str) -> bool:
        """Permanently delete a session."""
        with self._lock:
            return self.backend.delete_session(session_id)

    def search_sessions(
        self, query: str, user_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search across all sessions and messages for matching keywords."""
        q = query.lower()
        if hasattr(self.backend, "search_sessions"):
            raw_records = self.backend.search_sessions(query=query, user_id=user_id, limit=limit)
            results = []
            for r in raw_records:
                msgs = r.get("messages") or []
                matched_snippets = []
                for m in msgs:
                    content = m.get("content", "")
                    if q in content.lower():
                        snippet = content[:160] + ("..." if len(content) > 160 else "")
                        matched_snippets.append(
                            {
                                "message_id": m.get("message_id", ""),
                                "role": m.get("role", "user"),
                                "snippet": snippet,
                            }
                        )
                meta = r.get("metadata") or {}
                results.append(
                    {
                        "session_id": r["session_id"],
                        "title": r.get("title") or meta.get("title", "Untitled Session"),
                        "channel": r.get("channel") or meta.get("channel", "web"),
                        "matched_snippets": matched_snippets,
                        "total_messages": len(msgs),
                        "updated_at": r.get("updated_at") or _now_iso(),
                    }
                )
            return results[:limit]

        # Fallback to in-memory filter
        results = []
        sessions = self.list_sessions(user_id=user_id, limit=100)
        for s in sessions:
            matched_snippets = []
            for m in s.messages:
                if q in m.content.lower():
                    snippet = m.content[:160] + ("..." if len(m.content) > 160 else "")
                    matched_snippets.append(
                        {"message_id": m.message_id, "role": m.role, "snippet": snippet}
                    )
            if q in s.title.lower() or matched_snippets:
                results.append(
                    {
                        "session_id": s.session_id,
                        "title": s.title,
                        "channel": s.channel,
                        "matched_snippets": matched_snippets,
                        "total_messages": s.total_messages,
                        "updated_at": s.updated_at,
                    }
                )
        return results[:limit]

    def export_session(self, session_id: str, format: str = "json") -> str:
        """Export session content into the specified format."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")

        fmt = format.lower().strip()
        if fmt == "json":
            return json.dumps(session.to_dict(), indent=2)
        elif fmt in ("markdown", "md"):
            return to_markdown(session)
        elif fmt == "jsonl":
            return to_jsonl(session)
        elif fmt == "openai":
            return json.dumps(to_openai_messages(session), indent=2)
        elif fmt == "anthropic":
            sys_prompt, msgs = to_anthropic_messages(session)
            return json.dumps({"system": sys_prompt, "messages": msgs}, indent=2)
        elif fmt == "dspy":
            return json.dumps(to_dspy_history(session), indent=2)
        else:
            raise ValueError(
                f"Unsupported export format '{format}'. Use: json, markdown, jsonl, openai, anthropic, dspy"
            )

    def import_session(
        self, payload: Union[Dict[str, Any], str], format: str = "json"
    ) -> UnifiedSession:
        """Import a session from an external format or JSON payload."""
        fmt = format.lower().strip()
        if isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload

        if fmt == "openai" and isinstance(data, list):
            session = from_openai_messages(data)
        elif isinstance(data, dict):
            session = UnifiedSession.from_dict(data)
            if not session.session_id:
                session.session_id = f"sess_imported_{uuid.uuid4().hex[:8]}"
        else:
            raise ValueError(f"Invalid payload for format '{format}'")

        # Persist to backend
        meta = {
            **session.metadata,
            "title": session.title,
            "tenant_id": session.tenant_id,
            "channel": session.channel,
            "status": session.status,
            "participants": [p.to_dict() for p in session.participants],
        }
        self.backend.create_session(
            session_id=session.session_id,
            user_id=session.user_id,
            metadata=meta,
        )
        if session.messages:
            self.backend.update_session(
                session_id=session.session_id,
                messages=[m.to_dict() for m in session.messages],
                metadata=meta,
            )

        return session

    def _reconstitute_session(self, raw: Dict[str, Any]) -> UnifiedSession:
        """Convert a raw storage record dictionary into a rich UnifiedSession."""
        meta = raw.get("metadata") or {}
        msgs_raw = raw.get("messages") or []

        # Extract unified columns or fallback to metadata keys
        title = raw.get("title") or meta.get("title") or "Untitled Session"
        tenant_id = raw.get("tenant_id") or meta.get("tenant_id") or "default"
        channel = raw.get("channel") or meta.get("channel") or "web"
        status = raw.get("status") or meta.get("status") or SessionStatus.ACTIVE.value
        parent_sid = raw.get("parent_session_id") or meta.get("parent_session_id")
        fork_point_id = raw.get("fork_point_message_id") or meta.get("fork_point_message_id")
        summary = raw.get("summary") or meta.get("summary")

        # Parse participants
        parts_raw = meta.get("participants") or []
        participants = [
            p if isinstance(p, AgentParticipant) else AgentParticipant.from_dict(p)
            for p in parts_raw
        ]

        # Parse messages
        messages: List[UnifiedMessage] = []
        for idx, m in enumerate(msgs_raw):
            if isinstance(m, UnifiedMessage):
                messages.append(m)
            elif isinstance(m, dict):
                # Ensure message has an ID
                if "message_id" not in m:
                    m["message_id"] = f"msg_{raw['session_id']}_{idx}"
                messages.append(UnifiedMessage.from_dict(m))

        return UnifiedSession(
            session_id=raw["session_id"],
            title=title,
            user_id=raw.get("user_id", "default_user"),
            tenant_id=tenant_id,
            channel=channel,
            status=status,
            parent_session_id=parent_sid,
            fork_point_message_id=fork_point_id,
            created_at=raw.get("created_at") or _now_iso(),
            updated_at=raw.get("updated_at") or _now_iso(),
            summary=summary,
            participants=participants,
            messages=messages,
            metadata=meta,
        )


_GLOBAL_STORE_LOCK = threading.RLock()
_GLOBAL_SESSION_STORE: Optional[UnifiedSessionStore] = None


def get_session_store(
    backend: Optional[StorageBackend] = None, force_new: bool = False
) -> UnifiedSessionStore:
    """Retrieve or initialize the global UnifiedSessionStore singleton."""
    global _GLOBAL_SESSION_STORE
    with _GLOBAL_STORE_LOCK:
        if _GLOBAL_SESSION_STORE is None or force_new:
            _GLOBAL_SESSION_STORE = UnifiedSessionStore(backend=backend)
        return _GLOBAL_SESSION_STORE


def reset_session_store() -> None:
    """Reset the global session store singleton (useful for tests)."""
    global _GLOBAL_SESSION_STORE
    with _GLOBAL_STORE_LOCK:
        _GLOBAL_SESSION_STORE = None
