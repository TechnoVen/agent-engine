"""
Unit and Integration Tests for Context Builder & Budget Enforcement (Task 1.8).

Validates:
- ContextSpec configuration and defaults.
- Field whitelisting (stripping unauthorized or sensitive keys).
- Missing required field exception handling and permissive mode.
- Token estimation accuracy (tiktoken cl100k_base with heuristic fallback).
- Priority-aware truncation preserving critical fields longest.
- Hard ceiling enforcement and <8,000 token target budgeting.
- Conditional RAG retrieval gating and retrieval budget limit.
- Conversation history compaction preserving system prompt & latest turn.
- BuiltContext dictionary compatibility (subclassing dict).
- REST API POST /v1/context/build integration.
"""

from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient

from core.context import (
    ContextSpec,
    MissingContextFieldError,
    build_context,
    estimate_object_tokens,
    estimate_tokens,
    truncate_message_history,
)
from services.python.server.api import app

client = TestClient(app)


def test_context_spec_defaults():
    """Verify default configurations adhere to Law 3 context constraints."""
    spec = ContextSpec(required_fields=["user_id"])
    assert spec.required_fields == ["user_id"]
    assert spec.optional_fields == []
    assert spec.max_tokens == 4000
    assert spec.hard_ceiling_tokens == 32000
    assert spec.allow_retrieval is False
    assert spec.retrieval_budget_tokens == 2000
    assert spec.strict_required is True
    assert spec.truncation_strategy == "priority"


def test_field_whitelisting():
    """Verify strict field whitelisting removes all unrequested fields."""
    spec = ContextSpec(
        required_fields=["account_id"],
        optional_fields=["company_name"],
    )
    available_data = {
        "account_id": "ACC-9982",
        "company_name": "Acme Corp",
        "api_secret_key": "sk_test_secret_do_not_leak",
        "raw_server_logs": "x" * 50000,
        "internal_debug_flag": True,
    }

    built = build_context(spec=spec, available=available_data)

    # Required & optional are kept
    assert built["account_id"] == "ACC-9982"
    assert built["company_name"] == "Acme Corp"

    # Unauthorized fields are strictly stripped
    assert "api_secret_key" not in built
    assert "raw_server_logs" not in built
    assert "internal_debug_flag" not in built


def test_missing_required_field_raises_error():
    """Verify MissingContextFieldError is raised when a required field is absent."""
    spec = ContextSpec(
        required_fields=["customer_id", "billing_period"],
        strict_required=True,
    )
    available = {"customer_id": "CUST-123"}

    with pytest.raises(MissingContextFieldError) as excinfo:
        build_context(spec=spec, available=available)

    assert "billing_period" in str(excinfo.value)


def test_missing_required_field_permissive():
    """Verify strict_required=False does not raise when a required field is missing."""
    spec = ContextSpec(
        required_fields=["customer_id", "optional_metadata"],
        strict_required=False,
    )
    available = {"customer_id": "CUST-123"}

    built = build_context(spec=spec, available=available)
    assert built["customer_id"] == "CUST-123"
    assert "optional_metadata" not in built


def test_token_estimation_accuracy():
    """Verify token estimation for strings and nested composite objects."""
    # Text token estimation
    empty_tokens = estimate_tokens("")
    assert empty_tokens == 0

    sample_sentence = "The quick brown fox jumps over the lazy dog."
    tok_count = estimate_tokens(sample_sentence)
    assert 8 <= tok_count <= 15

    # Composite structure token estimation
    composite = {
        "title": "Report",
        "values": [1, 2, 3, 4, 5],
        "nested": {"status": "ok", "description": "System operational"},
    }
    obj_tokens = estimate_object_tokens(composite)
    assert obj_tokens > 5


def test_priority_aware_truncation():
    """Verify fields with lower priority are truncated before high-priority fields."""
    spec = ContextSpec(
        required_fields=["system_directive", "background_notes"],
        max_tokens=80,  # Tight budget
        field_priorities={
            "system_directive": 10,  # High priority: preserve
            "background_notes": 1,  # Low priority: truncate first
        },
    )

    long_directive = "CRITICAL DIRECTIVE: You must verify all invoice calculations accurately."
    long_notes = "Background information: " + ("irrelevant details and audit trail notes " * 30)

    available = {
        "system_directive": long_directive,
        "background_notes": long_notes,
    }

    built = build_context(spec=spec, available=available)

    assert built.was_truncated is True
    assert "background_notes" in built.truncated_fields
    # System directive should be preserved intact or far more intact than notes
    assert "[truncated for token budget]" in built["background_notes"]
    assert built["system_directive"] == long_directive


def test_hard_ceiling_enforcement():
    """Verify context size never exceeds specified budget or hard ceiling."""
    spec = ContextSpec(
        required_fields=["huge_document"],
        max_tokens=150,
        hard_ceiling_tokens=200,
    )
    huge_text = "lorem ipsum dolor sit amet " * 1000  # ~5,000 tokens

    built = build_context(spec=spec, available={"huge_document": huge_text})

    assert built.was_truncated is True
    assert built.estimated_tokens <= 200
    assert built["huge_document"].endswith("[truncated for token budget]")


def test_conditional_rag_retrieval_gated():
    """Verify retrieval function is NOT called when allow_retrieval=False."""
    spec = ContextSpec(
        required_fields=["query"],
        allow_retrieval=False,
    )

    call_count = 0

    def mock_retrieval(ctx: Dict[str, Any]):
        nonlocal call_count
        call_count += 1
        return "Retrieved secret documentation"

    built = build_context(
        spec=spec,
        available={"query": "How to file taxes?"},
        retrieval_fn=mock_retrieval,
    )

    assert call_count == 0
    assert "retrieved_context" not in built


def test_conditional_rag_retrieval_executed_and_budgeted():
    """Verify retrieval is invoked when allow_retrieval=True and budgeted."""
    spec = ContextSpec(
        required_fields=["query"],
        allow_retrieval=True,
        retrieval_budget_tokens=50,
    )

    def mock_retrieval(ctx: Dict[str, Any]):
        return "Relevant article: " + ("important facts about the topic " * 50)

    built = build_context(
        spec=spec,
        available={"query": "Tell me about quantum computing"},
        retrieval_fn=mock_retrieval,
    )

    assert "retrieved_context" in built
    assert "[truncated RAG context]" in built["retrieved_context"]


def test_conversation_history_compaction():
    """Verify multi-turn history compacts intermediate turns while keeping system & latest."""
    messages = [
        {"role": "system", "content": "You are a professional financial assistant."},
        {"role": "user", "content": "Turn 1 question: " + "detail " * 40},
        {"role": "assistant", "content": "Turn 1 answer: " + "explanation " * 40},
        {"role": "user", "content": "Turn 2 question: " + "detail " * 40},
        {"role": "assistant", "content": "Turn 2 answer: " + "explanation " * 40},
        {"role": "user", "content": "Latest question: What is the net total?"},
    ]

    # Compact down to small budget
    compacted = truncate_message_history(messages, max_tokens=60, preserve_system=True)

    assert len(compacted) < len(messages)
    # First message must be system
    assert compacted[0]["role"] == "system"
    # Last message must be the latest user question
    assert compacted[-1]["content"] == "Latest question: What is the net total?"


def test_built_context_dict_compatibility():
    """Verify BuiltContext behaves as a standard dictionary and serialization helper."""
    spec = ContextSpec(
        required_fields=["key1"],
        optional_fields=["key2"],
    )
    available = {"key1": "val1", "key2": "val2", "ignored": "val3"}

    built = build_context(spec=spec, available=available)

    # Dict standard operations
    assert isinstance(built, dict)
    assert built["key1"] == "val1"
    assert built.get("key2") == "val2"
    assert "key1" in built
    assert list(built.keys()) == ["key1", "key2"]

    # Metadata attributes
    assert isinstance(built.estimated_tokens, int)
    assert built.estimated_tokens > 0
    assert built.was_truncated is False
    assert built.truncated_fields == []
    assert isinstance(built.warnings, list)

    # Serialization helper
    envelope = built.to_dict()
    assert "data" in envelope
    assert envelope["data"]["key1"] == "val1"
    assert "estimated_tokens" in envelope


def test_rest_api_context_build_success():
    """Verify POST /v1/context/build API endpoint."""
    payload = {
        "required_fields": ["order_id", "summary"],
        "optional_fields": ["shipping_notes"],
        "available_data": {
            "order_id": "ORD-12345",
            "summary": "High priority delivery",
            "shipping_notes": "Handle with care",
            "internal_token": "secret_abc_123",
        },
        "max_tokens": 500,
        "allow_retrieval": False,
    }

    res = client.post("/v1/context/build", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "data" in data
    assert data["data"]["order_id"] == "ORD-12345"
    assert data["data"]["summary"] == "High priority delivery"
    assert data["data"]["shipping_notes"] == "Handle with care"
    assert "internal_token" not in data["data"]
    assert data["was_truncated"] is False
    assert data["estimated_tokens"] > 0


def test_rest_api_context_build_missing_required():
    """Verify POST /v1/context/build returns 400 when required field is missing."""
    payload = {
        "required_fields": ["order_id", "missing_mandate"],
        "available_data": {
            "order_id": "ORD-12345",
        },
        "strict_required": True,
    }

    res = client.post("/v1/context/build", json=payload)
    assert res.status_code == 400
    detail = res.json().get("detail", "")
    assert "missing_mandate" in detail


def test_warning_when_context_exceeds_8k():
    """Verify warning is recorded when context exceeds the recommended 8,000 token target."""
    spec = ContextSpec(
        required_fields=["massive_data"],
        max_tokens=10000,
        hard_ceiling_tokens=32000,
    )
    # Generate ~9,000 tokens of data (approx 36,000 characters)
    massive_text = "Analysis report with substantial data records: " + ("segment " * 9000)
    built = build_context(spec=spec, available={"massive_data": massive_text})

    assert any("exceeds recommended < 8,000 target" in w for w in built.warnings)
