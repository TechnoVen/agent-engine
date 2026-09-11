"""Cross-agent format converters for unified sessions.

Provides bi-directional translation between Agent Engine's UnifiedSession format and:
- OpenAI Chat Completion format
- Anthropic Messages format
- DSPy module execution history
- GitHub Markdown transcripts
- JSONL datasets for RAG and fine-tuning
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from core.session.model import MessageRole, ToolCall, UnifiedMessage, UnifiedSession


def to_openai_messages(session: UnifiedSession) -> List[Dict[str, Any]]:
    """Convert UnifiedSession messages to OpenAI Chat Completion message format."""
    openai_msgs: List[Dict[str, Any]] = []

    for msg in session.messages:
        role = msg.role.lower()
        if role == MessageRole.AGENT.value:
            role = "assistant"

        item: Dict[str, Any] = {
            "role": role if role in ("system", "user", "assistant", "tool") else "assistant",
            "content": msg.content or "",
        }

        if msg.sender_name:
            item["name"] = "".join(c for c in msg.sender_name if c.isalnum() or c in "_-")[:64]

        # Handle tool calls on assistant turns
        if msg.tool_calls and item["role"] == "assistant":
            item["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.arguments)
                        if isinstance(tc.arguments, dict)
                        else str(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]

        # Handle tool output turns
        if item["role"] == "tool":
            tool_call_id = msg.metadata.get("tool_call_id")
            if not tool_call_id and msg.tool_calls:
                tool_call_id = msg.tool_calls[0].call_id
            if tool_call_id:
                item["tool_call_id"] = tool_call_id

        openai_msgs.append(item)

    return openai_msgs


def from_openai_messages(
    messages: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    title: Optional[str] = None,
    user_id: str = "default_user",
    channel: str = "api",
) -> UnifiedSession:
    """Create a UnifiedSession from a list of OpenAI format messages."""
    import uuid

    sid = session_id or f"sess_{uuid.uuid4().hex[:10]}"
    session = UnifiedSession(
        session_id=sid,
        title=title or "Imported OpenAI Session",
        user_id=user_id,
        channel=channel,
    )

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        sender_name = m.get("name")
        tool_calls: List[ToolCall] = []

        if "tool_calls" in m and isinstance(m["tool_calls"], list):
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args_raw = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except Exception:
                    args = {"raw": args_raw}
                tool_calls.append(
                    ToolCall(
                        call_id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                        tool_name=fn.get("name", "unknown_tool"),
                        arguments=args,
                    )
                )

        metadata = {}
        if "tool_call_id" in m:
            metadata["tool_call_id"] = m["tool_call_id"]

        session.append_message(
            UnifiedMessage(
                session_id=sid,
                role=role,
                content=content,
                sender_id="assistant" if role == "assistant" else user_id,
                sender_name=sender_name,
                tool_calls=tool_calls,
                metadata=metadata,
            )
        )

    return session


def to_anthropic_messages(session: UnifiedSession) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Convert UnifiedSession to Anthropic format: (system_prompt, messages_list)."""
    system_prompt: Optional[str] = None
    messages: List[Dict[str, Any]] = []

    for msg in session.messages:
        role = msg.role.lower()
        if role == MessageRole.SYSTEM.value:
            # Combine system messages
            if system_prompt:
                system_prompt += f"\n\n{msg.content}"
            else:
                system_prompt = msg.content
            continue

        anthropic_role = "assistant" if role in ("assistant", "agent", "tool") else "user"
        content_payload: List[Dict[str, Any]] = []

        if msg.content:
            content_payload.append({"type": "text", "text": msg.content})

        if msg.tool_calls and anthropic_role == "assistant":
            for tc in msg.tool_calls:
                content_payload.append(
                    {
                        "type": "tool_use",
                        "id": tc.call_id,
                        "name": tc.tool_name,
                        "input": tc.arguments,
                    }
                )

        if role == "tool":
            tc_id = msg.metadata.get("tool_call_id") or (
                msg.tool_calls[0].call_id if msg.tool_calls else "tool_0"
            )
            content_payload = [
                {
                    "type": "tool_result",
                    "tool_use_id": tc_id,
                    "content": msg.content,
                }
            ]

        if not content_payload:
            content_payload.append({"type": "text", "text": ""})

        messages.append({"role": anthropic_role, "content": content_payload})

    return system_prompt, messages


def to_dspy_history(session: UnifiedSession) -> List[Dict[str, Any]]:
    """Convert UnifiedSession turns into DSPy history / demonstration context."""
    turns: List[Dict[str, Any]] = []
    current_input: Optional[str] = None

    for msg in session.messages:
        if msg.role == MessageRole.USER.value:
            current_input = msg.content
        elif msg.role in (MessageRole.ASSISTANT.value, MessageRole.AGENT.value):
            turns.append(
                {
                    "input": current_input or "",
                    "response": msg.content,
                    "agent_id": msg.agent_id or "default",
                    "model": msg.model,
                    "timestamp": msg.timestamp,
                }
            )
            current_input = None

    return turns


def to_markdown(session: UnifiedSession) -> str:
    """Render the UnifiedSession as a formatted GitHub markdown transcript."""
    lines: List[str] = [
        f"# Session: {session.title}",
        "",
        f"- **Session ID:** `{session.session_id}`",
        f"- **User:** `{session.user_id}` | **Tenant:** `{session.tenant_id}` | **Channel:** `{session.channel}`",
        f"- **Status:** `{session.status}` | **Created:** `{session.created_at}` | **Updated:** `{session.updated_at}`",
        f"- **Total Messages:** {session.total_messages} | **Total Tokens:** {session.total_tokens:,} | **Total Cost:** ${session.total_cost_usd:.6f}",
    ]

    if session.parent_session_id:
        lines.append(
            f"- **Forked from:** `{session.parent_session_id}` (at message `{session.fork_point_message_id}`)"
        )

    if session.summary:
        lines.extend(["", "### Summary", f"> {session.summary}"])

    if session.participants:
        lines.extend(["", "### Participating Agents"])
        for p in session.participants:
            lines.append(
                f"- **{p.agent_name}** (`{p.agent_id}`) - Role: *{p.role}* (Model: {p.model or 'default'})"
            )

    lines.extend(["", "---", "", "## Conversation History", ""])

    for msg in session.messages:
        role_label = msg.role.upper()
        sender = msg.sender_name or msg.sender_id
        time_str = msg.timestamp[11:19] if len(msg.timestamp) >= 19 else msg.timestamp

        lines.append(f"### {role_label} — {sender} ({time_str})")
        if msg.model:
            lines.append(f"*Model: `{msg.model}`*")
        lines.append("")
        lines.append(msg.content or "*(No text content)*")
        lines.append("")

        if msg.tool_calls:
            for tc in msg.tool_calls:
                lines.append("<details>")
                lines.append(
                    f"<summary>🔨 Tool Call: <code>{tc.tool_name}</code> ({tc.status})</summary>"
                )
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(tc.arguments, indent=2))
                lines.append("```")
                if tc.result is not None:
                    lines.append("**Result:**")
                    lines.append("```")
                    lines.append(str(tc.result))
                    lines.append("```")
                if tc.error:
                    lines.append(f"**Error:** `{tc.error}`")
                lines.append("</details>")
                lines.append("")

        if msg.tokens or msg.cost_usd is not None:
            t_str = f"Tokens: {msg.tokens.get('total', 0)}" if msg.tokens else ""
            c_str = f"Cost: ${msg.cost_usd:.6f}" if msg.cost_usd is not None else ""
            meta_str = " | ".join(filter(None, [t_str, c_str]))
            if meta_str:
                lines.append(f"> <sub>{meta_str}</sub>")
                lines.append("")

    return "\n".join(lines)


def to_jsonl(session: UnifiedSession) -> str:
    """Export the session as line-delimited JSON messages."""
    return "\n".join(json.dumps(m.to_dict()) for m in session.messages)
