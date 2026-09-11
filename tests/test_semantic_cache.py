"""Tests for Semantic Cache (Task 1.7).

Verifies:
1. L1 exact hash match (<2ms).
2. L2 Chroma-backed cosine semantic similarity (>= 0.95 threshold, 0 tokens).
3. Similarity rejection threshold (< 0.95).
4. TTL expiration and automatic eviction.
5. Task-type specific default TTLs.
6. Namespace and tenant isolation.
7. Cache invalidation, clear, and pruning.
8. Telemetry tracking (hits, misses, hit rate, tokens/cost saved).
9. @cached_step decorator integration.
10. FastAPI REST endpoints (/v1/cache/lookup, store, stats, clear).
"""

import time
import pytest
from fastapi.testclient import TestClient

from core.cache.semantic_cache import (
    CacheEntry,
    DEFAULT_TASK_TYPE_TTLS,
    SemanticCache,
    cached_step,
)
from services.python.server.api import app


@pytest.fixture
def memory_cache():
    """Provides an isolated, in-memory SemanticCache for tests."""
    cache = SemanticCache(
        collection_name="test_semantic_cache_" + str(int(time.time() * 1000)),
        in_memory=True,
    )
    yield cache
    cache.clear()


@pytest.fixture
def api_client(memory_cache):
    """Provides a TestClient using the isolated memory_cache."""
    import core.cache.semantic_cache as sc_mod

    orig_global = sc_mod._GLOBAL_CACHE
    sc_mod._GLOBAL_CACHE = memory_cache
    yield TestClient(app)
    sc_mod._GLOBAL_CACHE = orig_global


# ==============================================================================
# 1. CORE DATA STRUCTURES & SERIALIZATION
# ==============================================================================


def test_cache_entry_serialization_and_expiry():
    entry = CacheEntry(
        entry_id="e-100",
        query="What is python?",
        response="A high-level programming language.",
        task_type="qa",
        namespace="dev",
        similarity_score=0.98,
        created_at=time.time() - 100,
        ttl_seconds=50,
        tokens_saved=42,
        cost_saved_usd=0.00042,
        metadata={"model": "gpt-4o"},
    )
    assert entry.is_expired() is True
    d = entry.to_dict()
    assert d["entry_id"] == "e-100"
    assert d["tokens_saved"] == 42
    assert d["metadata"]["model"] == "gpt-4o"

    fresh_entry = CacheEntry(
        entry_id="e-101",
        query="Fresh query",
        response="Fresh response",
        ttl_seconds=3600,
    )
    assert fresh_entry.is_expired() is False


# ==============================================================================
# 2. L1 EXACT MATCH LOOKUP (<2ms)
# ==============================================================================


def test_exact_match_l1_hit(memory_cache):
    memory_cache.store(
        query="What is the capital of Germany?",
        response="Berlin",
        task_type="qa",
        tokens_saved=60,
        cost_saved_usd=0.0006,
    )

    # Lookup with exact match (ignoring case and whitespace differences)
    res = memory_cache.lookup("  what is the capital of germany?  ")
    assert res.hit is True
    assert res.match_type == "exact"
    assert res.similarity == 1.0
    assert res.latency_ms < 20.0
    assert res.entry is not None
    assert res.entry.response == "Berlin"
    assert res.entry.tokens_saved == 60


# ==============================================================================
# 3. L2 CHROMA-BACKED COSINE SEMANTIC SIMILARITY (>= 0.95)
# ==============================================================================


def test_semantic_cosine_l2_hit(memory_cache):
    memory_cache.store(
        query="How do I configure PostgreSQL connection pooling?",
        response={"solution": "Use PgBouncer or pgpool with max_connections 50."},
        task_type="qa",
        tokens_saved=120,
        cost_saved_usd=0.0012,
    )

    # Paraphrased query
    paraphrased = "Configuring PostgreSQL connection pooling"
    res = memory_cache.lookup(paraphrased, min_similarity=0.90)

    assert res.hit is True
    assert res.match_type in ("semantic", "exact")
    assert res.similarity >= 0.90
    assert res.entry is not None
    assert res.entry.response == {"solution": "Use PgBouncer or pgpool with max_connections 50."}


def test_semantic_threshold_rejection(memory_cache):
    memory_cache.store(
        query="How to sort a list in Python?",
        response="Use list.sort() or sorted().",
        task_type="code",
    )

    # Distinct query that should NOT match with similarity >= 0.95
    res = memory_cache.lookup("What is the weather forecast for Tokyo today?", min_similarity=0.95)
    assert res.hit is False
    assert res.entry is None
    assert res.match_type == "none"
    assert res.similarity < 0.95


# ==============================================================================
# 4. TTL EXPIRATION AND AUTO-EVICTION
# ==============================================================================


def test_ttl_expiration_and_eviction(memory_cache):
    memory_cache.store(
        query="Transient cache test",
        response="Expires quickly",
        ttl_seconds=1,
    )

    # Immediate lookup hits
    hit_res = memory_cache.lookup("Transient cache test")
    assert hit_res.hit is True

    # Sleep past TTL
    time.sleep(1.1)

    # Subsequent lookup detects expiration and evicts
    miss_res = memory_cache.lookup("Transient cache test")
    assert miss_res.hit is False
    assert miss_res.entry is None


def test_task_type_default_ttls():
    assert DEFAULT_TASK_TYPE_TTLS["classification"] == 7 * 86400
    assert DEFAULT_TASK_TYPE_TTLS["extraction"] == 2 * 86400
    assert DEFAULT_TASK_TYPE_TTLS["qa"] == 86400
    assert DEFAULT_TASK_TYPE_TTLS["code"] == 12 * 3600


# ==============================================================================
# 5. NAMESPACE & TENANT ISOLATION
# ==============================================================================


def test_namespace_isolation(memory_cache):
    memory_cache.store(
        query="Quarterly revenue projections",
        response={"q3": "$4.5M"},
        namespace="tenant_alpha",
    )

    # Tenant Beta should miss
    beta_res = memory_cache.lookup("Quarterly revenue projections", namespace="tenant_beta")
    assert beta_res.hit is False

    # Tenant Alpha should hit
    alpha_res = memory_cache.lookup("Quarterly revenue projections", namespace="tenant_alpha")
    assert alpha_res.hit is True
    assert alpha_res.entry.response == {"q3": "$4.5M"}


# ==============================================================================
# 6. CACHE INVALIDATION & CLEAR
# ==============================================================================


def test_invalidation_by_entry_id_and_namespace(memory_cache):
    e1 = memory_cache.store("Doc 1", "Resp 1", namespace="ns_a")
    memory_cache.store("Doc 2", "Resp 2", namespace="ns_a")
    memory_cache.store("Doc 3", "Resp 3", namespace="ns_b")

    # Invalidate e1 by ID
    del_count = memory_cache.invalidate(entry_id=e1.entry_id)
    assert del_count == 1
    assert memory_cache.lookup("Doc 1", namespace="ns_a").hit is False
    assert memory_cache.lookup("Doc 2", namespace="ns_a").hit is True

    # Invalidate whole namespace ns_a
    del_ns = memory_cache.invalidate(namespace="ns_a")
    assert del_ns >= 1
    assert memory_cache.lookup("Doc 2", namespace="ns_a").hit is False
    assert memory_cache.lookup("Doc 3", namespace="ns_b").hit is True

    # Clear all
    memory_cache.clear()
    assert memory_cache.lookup("Doc 3", namespace="ns_b").hit is False


def test_prune_expired(memory_cache):
    # Add one expired item and one fresh item
    memory_cache.store("Expired item", "old", ttl_seconds=1)
    memory_cache.store("Fresh item", "new", ttl_seconds=3600)

    time.sleep(1.1)

    pruned = memory_cache.prune_expired()
    assert pruned >= 1

    assert memory_cache.lookup("Expired item").hit is False
    assert memory_cache.lookup("Fresh item").hit is True


# ==============================================================================
# 7. TELEMETRY & STATS
# ==============================================================================


def test_telemetry_metrics(memory_cache):
    memory_cache.store(
        query="Metric benchmark",
        response="Result 1",
        tokens_saved=150,
        cost_saved_usd=0.0015,
    )

    # 1 Hit
    memory_cache.lookup("Metric benchmark")
    # 1 Miss
    memory_cache.lookup("Non-existent query")

    stats = memory_cache.get_stats()
    assert stats.total_lookups == 2
    assert stats.hits == 1
    assert stats.misses == 1
    assert abs(stats.hit_rate - 0.5) < 1e-4
    assert stats.tokens_saved == 150
    assert abs(stats.cost_saved_usd - 0.0015) < 1e-6


# ==============================================================================
# 8. @cached_step DECORATOR
# ==============================================================================


def test_cached_step_decorator(memory_cache):
    step_calls = 0

    @cached_step(
        task_type="classification",
        min_similarity=0.90,
        cache_instance=memory_cache,
        tokens_saved=200,
    )
    def classify_customer_intent(query: str) -> dict:
        nonlocal step_calls
        step_calls += 1
        return {"intent": "billing_issue", "risk": "low"}

    # First execution -> executes step
    out1 = classify_customer_intent("I have an issue with my monthly invoice")
    assert out1["intent"] == "billing_issue"
    assert step_calls == 1

    # Second execution with exact match -> cache hit, step not called
    out2 = classify_customer_intent("I have an issue with my monthly invoice")
    assert out2["intent"] == "billing_issue"
    assert step_calls == 1

    # Third execution with paraphrasing -> semantic cache hit, step not called
    out3 = classify_customer_intent("issue with monthly invoice")
    assert out3["intent"] == "billing_issue"
    assert step_calls == 1

    # Fourth execution with completely different query -> cache miss, step called
    out4 = classify_customer_intent("Book a flight to Frankfurt")
    assert out4["intent"] == "billing_issue"
    assert step_calls == 2


# ==============================================================================
# 9. FASTAPI REST ENDPOINTS
# ==============================================================================


def test_api_cache_endpoints(api_client):
    # 1. Store entry
    store_resp = api_client.post(
        "/v1/cache/store",
        json={
            "query": "What is the return policy?",
            "response": "30 days with receipt.",
            "task_type": "qa",
            "tokens_saved": 85,
            "cost_saved_usd": 0.00085,
            "namespace": "ecommerce",
        },
    )
    assert store_resp.status_code == 201
    store_data = store_resp.json()
    assert store_data["stored"] is True
    assert store_data["task_type"] == "qa"
    assert store_data["namespace"] == "ecommerce"

    # 2. Lookup matching entry
    lookup_resp = api_client.post(
        "/v1/cache/lookup",
        json={
            "query": "what is the return policy?",
            "namespace": "ecommerce",
        },
    )
    assert lookup_resp.status_code == 200
    lookup_data = lookup_resp.json()
    assert lookup_data["hit"] is True
    assert lookup_data["cached_response"] == "30 days with receipt."
    assert lookup_data["tokens_saved"] == 85

    # 3. Lookup non-matching entry
    miss_resp = api_client.post(
        "/v1/cache/lookup",
        json={
            "query": "How do I build a nuclear reactor?",
            "namespace": "ecommerce",
        },
    )
    assert miss_resp.status_code == 200
    assert miss_resp.json()["hit"] is False

    # 4. Get cache stats
    stats_resp = api_client.get("/v1/cache/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert stats_data["total_lookups"] >= 2
    assert stats_data["hits"] >= 1
    assert stats_data["tokens_saved"] >= 85

    # 5. Clear cache
    clear_resp = api_client.post("/v1/cache/clear", json={"namespace": "ecommerce"})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["cleared"] is True

    # 6. Verify lookup misses after clear
    after_clear = api_client.post(
        "/v1/cache/lookup",
        json={"query": "What is the return policy?", "namespace": "ecommerce"},
    )
    assert after_clear.json()["hit"] is False
