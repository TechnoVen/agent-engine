"""Agent Engine - Semantic Cache (Task 1.7).

Provides a high-performance, Chroma-backed semantic cache with a 0.95 cosine
similarity threshold and L1 exact-match hash acceleration. Reduces repetitive LLM calls
to 0 tokens and sub-20ms latency in compliance with Law 4 (Cache Before You Call).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import functools
import hashlib
import inspect
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

import chromadb

logger = logging.getLogger(__name__)

# Default TTL policies per task type (in seconds)
DEFAULT_TASK_TYPE_TTLS: Dict[str, int] = {
    "classification": 7 * 86400,  # 7 days
    "extraction": 2 * 86400,  # 48 hours
    "qa": 1 * 86400,  # 24 hours
    "code": 12 * 3600,  # 12 hours
    "default": 1 * 86400,  # 24 hours
}


@dataclass
class CacheEntry:
    """Represents a cached response along with metadata and expiration information."""

    entry_id: str
    query: str
    response: Any
    task_type: str = "qa"
    namespace: str = "default"
    similarity_score: float = 1.0
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 86400
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Check if this cache entry has exceeded its time-to-live."""
        curr = now if now is not None else time.time()
        return curr >= (self.created_at + self.ttl_seconds)

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry into serializable dictionary."""
        return {
            "entry_id": self.entry_id,
            "query": self.query,
            "response": self.response,
            "task_type": self.task_type,
            "namespace": self.namespace,
            "similarity_score": self.similarity_score,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "tokens_saved": self.tokens_saved,
            "cost_saved_usd": self.cost_saved_usd,
            "metadata": self.metadata,
        }


@dataclass
class CacheLookupResult:
    """Result of a semantic cache lookup."""

    hit: bool
    entry: Optional[CacheEntry] = None
    similarity: float = 0.0
    latency_ms: float = 0.0
    query: str = ""
    match_type: str = "none"  # "exact" | "semantic" | "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hit": self.hit,
            "entry": self.entry.to_dict() if self.entry else None,
            "similarity": round(self.similarity, 4),
            "latency_ms": round(self.latency_ms, 2),
            "query": self.query,
            "match_type": self.match_type,
        }


@dataclass
class CacheStats:
    """Aggregated runtime statistics for the semantic cache."""

    total_lookups: int = 0
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    total_entries: int = 0
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lookups": self.total_lookups,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "total_entries": self.total_entries,
            "tokens_saved": self.tokens_saved,
            "cost_saved_usd": round(self.cost_saved_usd, 6),
        }


def _hash_query(query: str, namespace: str, task_type: Optional[str]) -> str:
    """Generate deterministic SHA-256 hash for L1 exact match lookup."""
    normalized = " ".join(query.strip().lower().split())
    tt = (task_type or "*").strip().lower()
    ns = namespace.strip().lower()
    raw = f"{ns}::{tt}::{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SemanticCache:
    """
    Chroma-backed dual-layer semantic cache.
    - L1: In-memory exact-match hash dictionary for sub-millisecond retrieval.
    - L2: ChromaDB cosine distance vector collection for semantic near-duplicate retrieval (similarity >= 0.95).
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: str = "semantic_cache",
        default_similarity_threshold: float = 0.95,
        default_ttl_seconds: int = 86400,
        task_type_ttls: Optional[Dict[str, int]] = None,
        client: Optional[Any] = None,
        in_memory: bool = False,
    ):
        self.collection_name = collection_name
        self.default_similarity_threshold = default_similarity_threshold
        self.default_ttl_seconds = default_ttl_seconds
        self.task_type_ttls = {**DEFAULT_TASK_TYPE_TTLS, **(task_type_ttls or {})}
        self._lock = threading.RLock()

        # Telemetry metrics
        self._total_lookups = 0
        self._hits = 0
        self._misses = 0
        self._tokens_saved = 0
        self._cost_saved_usd = 0.0

        # L1 exact hash index: { hash_key: CacheEntry }
        self._l1_exact_cache: Dict[str, CacheEntry] = {}

        # Initialize Chroma vector store client
        if client is not None:
            self.client = client
        elif in_memory:
            self.client = chromadb.EphemeralClient()
        else:
            self.persist_directory = persist_directory or os.getenv(
                "CHROMA_PERSIST_DIR", "/home/nadir/agent_engine/data/chroma"
            )
            os.makedirs(self.persist_directory, exist_ok=True)
            self.client = chromadb.PersistentClient(path=self.persist_directory)

        # Chroma collection with Cosine Distance
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine", "description": "Agent Engine Semantic Cache"},
        )

    def lookup(
        self,
        query: str,
        namespace: str = "default",
        task_type: Optional[str] = None,
        min_similarity: Optional[float] = None,
    ) -> CacheLookupResult:
        """
        Check cache for matching query.
        First attempts L1 exact match (<1ms).
        Falls back to L2 Chroma vector similarity match (>= min_similarity, default 0.95).
        """
        start_time = time.perf_counter()
        threshold = (
            min_similarity if min_similarity is not None else self.default_similarity_threshold
        )
        now = time.time()

        with self._lock:
            self._total_lookups += 1

            # ------------------------------------------------------------------
            # 1. L1 Exact Match Check (Sub-millisecond)
            # ------------------------------------------------------------------
            hash_key = _hash_query(query, namespace, task_type)
            if hash_key in self._l1_exact_cache:
                entry = self._l1_exact_cache[hash_key]
                if not entry.is_expired(now):
                    latency_ms = (time.perf_counter() - start_time) * 1000.0
                    self._hits += 1
                    self._tokens_saved += entry.tokens_saved
                    self._cost_saved_usd += entry.cost_saved_usd
                    entry.similarity_score = 1.0
                    return CacheLookupResult(
                        hit=True,
                        entry=entry,
                        similarity=1.0,
                        latency_ms=latency_ms,
                        query=query,
                        match_type="exact",
                    )
                else:
                    # Evict expired entry from L1 and Chroma
                    del self._l1_exact_cache[hash_key]
                    try:
                        self.collection.delete(ids=[entry.entry_id])
                    except Exception as e:
                        logger.debug(
                            "Failed deleting expired Chroma entry %s: %s", entry.entry_id, e
                        )

            # ------------------------------------------------------------------
            # 2. L2 Semantic Vector Similarity Check (Chroma)
            # ------------------------------------------------------------------
            if self.collection.count() == 0:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                self._misses += 1
                return CacheLookupResult(
                    hit=False,
                    entry=None,
                    similarity=0.0,
                    latency_ms=latency_ms,
                    query=query,
                    match_type="none",
                )

            where_filter: Dict[str, Any] = {"namespace": namespace}
            if task_type:
                where_filter = {"$and": [{"namespace": namespace}, {"task_type": task_type}]}

            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=1,
                    where=where_filter,
                )
            except Exception as e:
                logger.warning("Chroma semantic cache query error: %s", e)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                self._misses += 1
                return CacheLookupResult(
                    hit=False,
                    entry=None,
                    similarity=0.0,
                    latency_ms=latency_ms,
                    query=query,
                    match_type="none",
                )

            matched_ids = results.get("ids", [[]])[0]
            matched_distances = results.get("distances", [[]])[0]
            matched_metadatas = results.get("metadatas", [[]])[0]
            matched_documents = results.get("documents", [[]])[0]

            if not matched_ids or not matched_distances:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                self._misses += 1
                return CacheLookupResult(
                    hit=False,
                    entry=None,
                    similarity=0.0,
                    latency_ms=latency_ms,
                    query=query,
                    match_type="none",
                )

            distance = matched_distances[0]
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))

            if similarity >= threshold:
                raw_meta = matched_metadatas[0] if matched_metadatas else {}
                entry_id = matched_ids[0]

                # Deserialize payload
                try:
                    response_val = json.loads(raw_meta.get("response_json", "null"))
                except Exception:
                    response_val = raw_meta.get("response_json")

                try:
                    meta_extra = json.loads(raw_meta.get("metadata_json", "{}"))
                except Exception:
                    meta_extra = {}

                entry = CacheEntry(
                    entry_id=entry_id,
                    query=matched_documents[0] if matched_documents else query,
                    response=response_val,
                    task_type=raw_meta.get("task_type", task_type or "qa"),
                    namespace=raw_meta.get("namespace", namespace),
                    similarity_score=similarity,
                    created_at=float(raw_meta.get("created_at", now)),
                    ttl_seconds=int(raw_meta.get("ttl_seconds", self.default_ttl_seconds)),
                    tokens_saved=int(raw_meta.get("tokens_saved", 0)),
                    cost_saved_usd=float(raw_meta.get("cost_saved_usd", 0.0)),
                    metadata=meta_extra,
                )

                if entry.is_expired(now):
                    # Evict expired entry from Chroma & L1
                    try:
                        self.collection.delete(ids=[entry_id])
                    except Exception as e:
                        logger.debug("Failed deleting expired Chroma entry %s: %s", entry_id, e)
                    self._l1_exact_cache.pop(hash_key, None)

                    latency_ms = (time.perf_counter() - start_time) * 1000.0
                    self._misses += 1
                    return CacheLookupResult(
                        hit=False,
                        entry=None,
                        similarity=similarity,
                        latency_ms=latency_ms,
                        query=query,
                        match_type="none",
                    )

                # Check if exact text match
                is_exact = " ".join(query.strip().lower().split()) == " ".join(
                    (matched_documents[0] if matched_documents else "").strip().lower().split()
                )
                match_type = "exact" if is_exact else "semantic"

                # Cache hit! Cache in L1 for future instant lookups
                self._l1_exact_cache[hash_key] = entry
                self._hits += 1
                self._tokens_saved += entry.tokens_saved
                self._cost_saved_usd += entry.cost_saved_usd
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                return CacheLookupResult(
                    hit=True,
                    entry=entry,
                    similarity=1.0 if is_exact else similarity,
                    latency_ms=latency_ms,
                    query=query,
                    match_type=match_type,
                )

            # Similarity below threshold -> Cache miss
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self._misses += 1
            return CacheLookupResult(
                hit=False,
                entry=None,
                similarity=similarity,
                latency_ms=latency_ms,
                query=query,
                match_type="none",
            )

    def store(
        self,
        query: str,
        response: Any,
        task_type: str = "qa",
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        namespace: str = "default",
        tokens_saved: int = 0,
        cost_saved_usd: float = 0.0,
    ) -> CacheEntry:
        """
        Store a query and response in the semantic cache.
        Stores in both L1 (exact-match hash map) and L2 (Chroma vector collection).
        """
        now = time.time()
        resolved_ttl = ttl_seconds
        if resolved_ttl is None:
            resolved_ttl = self.task_type_ttls.get(task_type, self.default_ttl_seconds)

        entry_id = str(uuid.uuid4())
        extra_meta = metadata or {}

        entry = CacheEntry(
            entry_id=entry_id,
            query=query,
            response=response,
            task_type=task_type,
            namespace=namespace,
            similarity_score=1.0,
            created_at=now,
            ttl_seconds=resolved_ttl,
            tokens_saved=tokens_saved,
            cost_saved_usd=cost_saved_usd,
            metadata=extra_meta,
        )

        # Prepare Chroma metadata (only primitive types permitted by Chroma)
        chroma_meta: Dict[str, Any] = {
            "entry_id": entry_id,
            "task_type": task_type,
            "namespace": namespace,
            "created_at": now,
            "ttl_seconds": resolved_ttl,
            "tokens_saved": tokens_saved,
            "cost_saved_usd": cost_saved_usd,
            "response_json": json.dumps(response),
            "metadata_json": json.dumps(extra_meta),
        }

        with self._lock:
            # Store into Chroma
            self.collection.add(
                documents=[query],
                metadatas=[chroma_meta],
                ids=[entry_id],
            )

            # Store into L1 exact cache
            hash_key = _hash_query(query, namespace, task_type)
            self._l1_exact_cache[hash_key] = entry
            # Also index under wildcard task_type for lookups without task_type
            wildcard_key = _hash_query(query, namespace, None)
            self._l1_exact_cache[wildcard_key] = entry

        return entry

    def invalidate(
        self,
        query: Optional[str] = None,
        entry_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> int:
        """
        Invalidate cached entries by query, entry_id, or namespace.
        Returns the number of invalidated entries.
        """
        deleted_count = 0
        with self._lock:
            if entry_id:
                try:
                    self.collection.delete(ids=[entry_id])
                    deleted_count += 1
                except Exception as e:
                    logger.debug("Failed deleting Chroma entry %s: %s", entry_id, e)

                # Remove from L1
                keys_to_delete = [
                    k for k, v in self._l1_exact_cache.items() if v.entry_id == entry_id
                ]
                for k in keys_to_delete:
                    del self._l1_exact_cache[k]

            elif query and namespace:
                hash_key = _hash_query(query, namespace, None)
                if hash_key in self._l1_exact_cache:
                    e_id = self._l1_exact_cache[hash_key].entry_id
                    del self._l1_exact_cache[hash_key]
                    try:
                        self.collection.delete(ids=[e_id])
                        deleted_count += 1
                    except Exception:
                        pass
                else:
                    # Query Chroma to find matching IDs
                    try:
                        res = self.collection.get(where={"namespace": namespace})
                        for doc_id, doc in zip(res.get("ids", []), res.get("documents", [])):
                            if doc.strip().lower() == query.strip().lower():
                                self.collection.delete(ids=[doc_id])
                                deleted_count += 1
                    except Exception:
                        pass

            elif namespace:
                try:
                    res = self.collection.get(where={"namespace": namespace})
                    ids_to_del = res.get("ids", [])
                    if ids_to_del:
                        self.collection.delete(ids=ids_to_del)
                        deleted_count += len(ids_to_del)
                except Exception:
                    pass

                keys_to_delete = [
                    k for k, v in self._l1_exact_cache.items() if v.namespace == namespace
                ]
                for k in keys_to_delete:
                    del self._l1_exact_cache[k]

        return deleted_count

    def prune_expired(self) -> int:
        """
        Sweep cache and evict all expired entries from L1 and Chroma.
        Returns count of pruned entries.
        """
        now = time.time()
        pruned_count = 0

        with self._lock:
            # 1. Prune L1
            expired_l1_keys = [k for k, v in self._l1_exact_cache.items() if v.is_expired(now)]
            expired_chroma_ids = set()

            for k in expired_l1_keys:
                expired_chroma_ids.add(self._l1_exact_cache[k].entry_id)
                del self._l1_exact_cache[k]

            # 2. Prune Chroma entries
            try:
                all_data = self.collection.get(include=["metadatas"])
                ids = all_data.get("ids", [])
                metas = all_data.get("metadatas", [])

                for item_id, meta in zip(ids, metas):
                    created_at = float(meta.get("created_at", 0.0))
                    ttl_seconds = int(meta.get("ttl_seconds", self.default_ttl_seconds))
                    if now >= (created_at + ttl_seconds):
                        expired_chroma_ids.add(item_id)

                if expired_chroma_ids:
                    self.collection.delete(ids=list(expired_chroma_ids))
                    pruned_count = len(expired_chroma_ids)
            except Exception as e:
                logger.warning("Error pruning Chroma cache: %s", e)

        return pruned_count

    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear cache entries, optionally constrained to a namespace."""
        with self._lock:
            if namespace:
                self.invalidate(namespace=namespace)
            else:
                self._l1_exact_cache.clear()
                try:
                    self.client.delete_collection(self.collection_name)
                    self.collection = self.client.get_or_create_collection(
                        name=self.collection_name,
                        metadata={
                            "hnsw:space": "cosine",
                            "description": "Agent Engine Semantic Cache",
                        },
                    )
                except Exception as e:
                    logger.warning("Error clearing collection: %s", e)

    def get_stats(self) -> CacheStats:
        """Calculate and return current cache telemetry and hit rate."""
        with self._lock:
            total_entries = self.collection.count()
            hit_rate = (self._hits / self._total_lookups) if self._total_lookups > 0 else 0.0
            return CacheStats(
                total_lookups=self._total_lookups,
                hits=self._hits,
                misses=self._misses,
                hit_rate=hit_rate,
                total_entries=total_entries,
                tokens_saved=self._tokens_saved,
                cost_saved_usd=self._cost_saved_usd,
            )

    def reset_stats(self) -> None:
        """Reset cache lookup telemetry metrics."""
        with self._lock:
            self._total_lookups = 0
            self._hits = 0
            self._misses = 0
            self._tokens_saved = 0
            self._cost_saved_usd = 0.0


# ==============================================================================
# Global Singleton & Decorator
# ==============================================================================

_GLOBAL_CACHE: Optional[SemanticCache] = None
_CACHE_LOCK = threading.Lock()


def get_semantic_cache(
    persist_directory: Optional[str] = None,
    collection_name: str = "semantic_cache",
    in_memory: bool = False,
) -> SemanticCache:
    """Access or initialize the global SemanticCache singleton."""
    global _GLOBAL_CACHE
    with _CACHE_LOCK:
        if _GLOBAL_CACHE is None:
            _GLOBAL_CACHE = SemanticCache(
                persist_directory=persist_directory,
                collection_name=collection_name,
                in_memory=in_memory,
            )
        return _GLOBAL_CACHE


def reset_semantic_cache() -> None:
    """Reset the global SemanticCache singleton (useful for isolated tests)."""
    global _GLOBAL_CACHE
    with _CACHE_LOCK:
        if _GLOBAL_CACHE is not None:
            _GLOBAL_CACHE.clear()
        _GLOBAL_CACHE = None


def cached_step(
    task_type: str = "qa",
    min_similarity: float = 0.95,
    ttl_seconds: Optional[int] = None,
    namespace: str = "default",
    tokens_saved: int = 0,
    cost_saved_usd: float = 0.0,
    cache_instance: Optional[SemanticCache] = None,
) -> Callable:
    """
    Decorator for wrapping an agent pipeline step or function with semantic caching.

    If a query argument matches a cached result with cosine similarity >= min_similarity,
    the cached response is returned immediately (0 model tokens consumed).
    Otherwise, the function executes, and its return value is stored in the cache.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = cache_instance or get_semantic_cache()

            # Determine query text from first positional argument or 'query' / 'prompt' kwarg
            query: Optional[str] = None
            if "query" in kwargs:
                query = str(kwargs["query"])
            elif "prompt" in kwargs:
                query = str(kwargs["prompt"])
            elif args:
                # If first arg is self/cls, check second arg
                if len(args) > 1 and inspect.isclass(type(args[0])):
                    query = str(args[1])
                else:
                    query = str(args[0])

            if not query:
                # If no textual query could be identified, run without caching
                return fn(*args, **kwargs)

            # Check cache
            lookup_res = cache.lookup(
                query=query,
                namespace=namespace,
                task_type=task_type,
                min_similarity=min_similarity,
            )

            if lookup_res.hit and lookup_res.entry is not None:
                logger.info(
                    "Semantic cache HIT for query='%s' (type=%s, sim=%.4f, lat=%.2fms)",
                    query[:50],
                    lookup_res.match_type,
                    lookup_res.similarity,
                    lookup_res.latency_ms,
                )
                return lookup_res.entry.response

            # Cache miss: execute wrapped step
            result = fn(*args, **kwargs)

            # Store result in cache
            try:
                cache.store(
                    query=query,
                    response=result,
                    task_type=task_type,
                    ttl_seconds=ttl_seconds,
                    namespace=namespace,
                    tokens_saved=tokens_saved,
                    cost_saved_usd=cost_saved_usd,
                )
            except Exception as e:
                logger.warning("Failed storing result in semantic cache: %s", e)

            return result

        return wrapper

    return decorator
