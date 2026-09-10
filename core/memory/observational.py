import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import chromadb
from dotenv import load_dotenv

from core.memory.vector import _CHROMA_CLIENTS

load_dotenv()


@dataclass
class Observation:
    """An atomic observation, fact, or extracted preference stored in memory."""

    id: str
    content: str
    category: str = "general"  # preference, project_fact, workflow, general
    importance: float = 5.0  # Scale 1.0 to 10.0
    created_at: float = field(default_factory=time.time)  # Unix timestamp in seconds
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "importance": round(self.importance, 2),
            "created_at": self.created_at,
            "session_id": self.session_id,
            "metadata": self.metadata or {},
        }


@dataclass
class ScoredObservation:
    """An observation scored with relevance, importance, and temporal recency."""

    observation: Observation
    relevance_score: float  # [0.0, 1.0]
    importance_score: float  # [0.0, 1.0]
    recency_score: float  # [0.0, 1.0]
    final_score: float  # Combined weighted score

    def to_dict(self) -> Dict[str, Any]:
        d = self.observation.to_dict()
        d.update(
            {
                "relevance_score": round(self.relevance_score, 4),
                "importance_score": round(self.importance_score, 4),
                "recency_score": round(self.recency_score, 4),
                "final_score": round(self.final_score, 4),
            }
        )
        return d


class PreferenceExtractor:
    """
    Deterministic rule-based extractor for user preferences and project facts.
    Implements the 90% Cost Optimization rule (ADR-015) using zero-token regex heuristics.
    """

    # Compiled regex rules for preference detection
    PREFERENCE_RULES = [
        # Explicit preferences: "I prefer X", "I prefer X over Y"
        (
            re.compile(
                r"\b(?:i\s+prefer(?:\s+to\s+use)?)\s+([^\n.,;!?]+?)(?:\s+(?:over|instead\s+of)\s+([^\n.,;!?]+))?(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            8.5,
            "User prefers: {0}{1}",
        ),
        # Mandatory positive directives: "Always use X", "Always do X"
        (
            re.compile(
                r"\b(?:always\s+(?:use|follow|apply|ensure|do|keep|write))\s+([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            9.0,
            "Constraint: Always use/do {0}",
        ),
        # Mandatory negative directives: "Never use X", "Never allow X", "Do not use X"
        (
            re.compile(
                r"\b(?:never\s+(?:use|do|allow|call|import|write|deploy))\s+([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            9.5,
            "Constraint: Never use/do {0}",
        ),
        (
            re.compile(
                r"\b(?:do\s+not(?:\s+ever)?\s+(?:use|do|allow|modify|overwrite))\s+([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            9.0,
            "Constraint: Do not use/do {0}",
        ),
        # Explicit favorites or likes
        (
            re.compile(
                r"\bmy\s+(?:favorite|preferred)\s+([a-zA-Z0-9_\-\s]+?)\s+is\s+([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            8.0,
            "User preferred {0} is {1}",
        ),
        (
            re.compile(
                r"\bi\s+(?:like|love)\s+(?:to\s+use\s+)?([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            7.5,
            "User likes {0}",
        ),
        (
            re.compile(
                r"\bi\s+(?:dislike|hate|avoid)\s+(?:using\s+)?([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            8.0,
            "User avoids {0}",
        ),
        # Explicit memory requests: "Please remember that X", "Remember that X"
        (
            re.compile(
                r"\b(?:please\s+)?remember(?:\s+that)?\s+([^\n;!?]+)(?:[;!?]|$)",
                re.IGNORECASE,
            ),
            "preference",
            9.0,
            "Remember: {0}",
        ),
        # Project facts: "My project uses X", "The repository is built with X"
        (
            re.compile(
                r"\b(?:my\s+project|this\s+project|the\s+repository|the\s+codebase|we)\s+(?:uses|is\s+built\s+with|is\s+written\s+in|targets|requires)\s+([^\n.,;!?]+)(?:[.,;!?]|$)",
                re.IGNORECASE,
            ),
            "project_fact",
            8.5,
            "Project stack fact: {0}",
        ),
        (
            re.compile(
                r"\bnote\s+that\s+([^\n;!?]+)(?:[;!?]|$)",
                re.IGNORECASE,
            ),
            "project_fact",
            7.5,
            "Note: {0}",
        ),
    ]

    @classmethod
    def extract_from_text(cls, text: str) -> List[Dict[str, Any]]:
        """
        Scan text and return detected preferences/facts with category and importance.
        """
        extracted = []
        if not text or not text.strip():
            return extracted

        for pattern, category, importance, fmt in cls.PREFERENCE_RULES:
            for match in pattern.finditer(text):
                groups = [g.strip() for g in match.groups() if g is not None]
                if not groups:
                    continue

                if "{1}" in fmt:
                    alt = f" (instead of {groups[1]})" if len(groups) > 1 and groups[1] else ""
                    content = fmt.format(groups[0], alt)
                else:
                    content = fmt.format(*groups)

                # Clean up any trailing periods or excess whitespace
                content = content.strip().rstrip(".")
                extracted.append(
                    {
                        "content": content,
                        "raw_match": match.group(0).strip(),
                        "category": category,
                        "importance": importance,
                    }
                )

        return extracted


class SessionSummarizer:
    """
    Summarizes conversation sessions into atomic observations with importance scoring.
    """

    HIGH_IMPORTANCE_KEYWORDS = {
        "critical",
        "never",
        "always",
        "breaking",
        "security",
        "secret",
        "api_key",
        "apikey",
        "password",
        "auth",
        "architecture",
        "database",
        "production",
        "error",
        "bug",
        "failure",
        "rule",
        "forbid",
        "prohibit",
    }

    LOW_IMPORTANCE_GREETINGS = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "cool",
        "sounds good",
        "yes",
        "no",
        "sure",
        "good morning",
        "good evening",
    }

    @classmethod
    def calculate_importance(cls, text: str, base_importance: float = 5.0) -> float:
        """
        Heuristic importance scoring based on lexical signals.
        Returns value clamped between 1.0 and 10.0.
        """
        text_lower = text.lower().strip()

        # Low importance chatter
        if text_lower in cls.LOW_IMPORTANCE_GREETINGS or len(text_lower.split()) <= 2:
            return 2.0

        score = base_importance
        words = set(re.findall(r"\b[a-z_]+\b", text_lower))

        # Check for high importance signals
        high_matches = words.intersection(cls.HIGH_IMPORTANCE_KEYWORDS)
        if high_matches:
            score += min(3.0, len(high_matches) * 1.5)

        # Longer detailed technical statements receive minor boost
        if len(text.split()) > 15:
            score += 0.5

        return max(1.0, min(10.0, score))

    @classmethod
    def summarize_session_turns(
        cls, messages: List[Dict[str, Any]], session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Process user and assistant turns into observations with importance scores.
        """
        observations: List[Dict[str, Any]] = []

        for msg in messages:
            content = msg.get("content", "").strip()
            role = msg.get("role", "user")
            if not content:
                continue

            # First, check for explicit preferences
            prefs = PreferenceExtractor.extract_from_text(content)
            for p in prefs:
                observations.append(
                    {
                        "content": p["content"],
                        "category": p["category"],
                        "importance": p["importance"],
                        "session_id": session_id,
                        "metadata": {"role": role, "raw": p.get("raw_match")},
                    }
                )

            # If no explicit preference detected, capture user turns with sufficient substance
            if not prefs and role == "user":
                importance = cls.calculate_importance(content, base_importance=4.5)
                if importance >= 4.0:
                    cat = "general"
                    observations.append(
                        {
                            "content": content,
                            "category": cat,
                            "importance": importance,
                            "session_id": session_id,
                            "metadata": {"role": role},
                        }
                    )

        return observations


class ObservationalMemory:
    """
    Observational Memory layer on top of ChromaDB.
    Supports session summarization, preference extraction, importance scoring,
    and Stanford Generative Agents temporal decay:
    Score = alpha * Relevance + beta * Importance + gamma * e^(-lambda * Delta_t)
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: str = "agent_observations",
    ):
        self.persist_directory = persist_directory or os.getenv(
            "CHROMA_PERSIST_DIR", "/home/nadir/agent_engine/data/chroma"
        )
        os.makedirs(self.persist_directory, exist_ok=True)

        if self.persist_directory not in _CHROMA_CLIENTS:
            _CHROMA_CLIENTS[self.persist_directory] = chromadb.PersistentClient(
                path=self.persist_directory
            )

        self.client = _CHROMA_CLIENTS[self.persist_directory]
        self.collection_name = collection_name
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "description": "Agent Engine Observational Memory & Preferences",
                "hnsw:space": "cosine",
            },
        )

    def record_observation(
        self,
        content: str,
        category: str = "general",
        importance: float = 5.0,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[float] = None,
        obs_id: Optional[str] = None,
    ) -> Observation:
        """
        Record a single atomic observation with importance score and timestamp.
        """
        content_clean = content.strip()
        if not content_clean:
            raise ValueError("Observation content cannot be empty.")

        importance_clamped = max(1.0, min(10.0, float(importance)))
        timestamp = created_at if created_at is not None else time.time()
        observation_id = obs_id or f"obs_{uuid.uuid4().hex[:12]}"

        obs = Observation(
            id=observation_id,
            content=content_clean,
            category=category,
            importance=importance_clamped,
            created_at=timestamp,
            session_id=session_id,
            metadata=metadata or {},
        )

        chroma_metadata: Dict[str, Any] = {
            "category": category,
            "importance": float(importance_clamped),
            "created_at": float(timestamp),
            "session_id": session_id or "",
        }

        self.collection.add(
            ids=[observation_id],
            documents=[content_clean],
            metadatas=[chroma_metadata],
        )

        return obs

    def record_session(self, session_id: str, messages: List[Dict[str, Any]]) -> List[Observation]:
        """
        Summarize session messages, extract preferences, and record observations.
        """
        summarized = SessionSummarizer.summarize_session_turns(messages, session_id=session_id)
        recorded: List[Observation] = []

        for item in summarized:
            obs = self.record_observation(
                content=item["content"],
                category=item["category"],
                importance=item["importance"],
                session_id=session_id,
                metadata=item.get("metadata"),
            )
            recorded.append(obs)

        return recorded

    def query_observations(
        self,
        query: str,
        n_results: int = 5,
        alpha: float = 0.5,
        beta: float = 0.3,
        gamma: float = 0.2,
        decay_lambda: float = 0.05,
        min_score: float = 0.0,
        current_time: Optional[float] = None,
    ) -> List[ScoredObservation]:
        """
        Query observational memory using Stanford Generative Agents scoring:
        Score = alpha * Relevance + beta * Importance + gamma * e^(-lambda * Delta_t)

        Delta_t is the time difference in days.
        Default decay_lambda = 0.05 yields a half-life of ~13.8 days.
        """
        total_count = self.count()
        if total_count == 0:
            return []

        # Fetch a generous candidate pool so reranking by importance & recency works properly
        fetch_limit = min(total_count, max(n_results * 4, 20))
        results = self.collection.query(
            query_texts=[query],
            n_results=fetch_limit,
            include=["documents", "metadatas", "distances"],
        )

        now = current_time if current_time is not None else time.time()
        scored_list: List[ScoredObservation] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, obs_id in enumerate(ids):
            content = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if (distances and i < len(distances)) else 1.0

            # 1. Relevance: cosine distance d in [0, 2].
            # Cosine similarity is 1.0 - d. Clamped to [0.0, 1.0].
            relevance = max(0.0, min(1.0, 1.0 - float(dist)))

            # 2. Importance: scale [1.0, 10.0] normalized to [0.1, 1.0]
            importance_raw = float(meta.get("importance", 5.0))
            importance_norm = max(0.1, min(1.0, importance_raw / 10.0))

            # 3. Recency: e^(-lambda * delta_days)
            created_at = float(meta.get("created_at", now))
            delta_seconds = max(0.0, now - created_at)
            delta_days = delta_seconds / 86400.0
            recency = math.exp(-decay_lambda * delta_days)

            # Combined weighted score
            final_score = (alpha * relevance) + (beta * importance_norm) + (gamma * recency)

            if final_score >= min_score:
                obs = Observation(
                    id=obs_id,
                    content=content,
                    category=meta.get("category", "general"),
                    importance=importance_raw,
                    created_at=created_at,
                    session_id=meta.get("session_id") or None,
                )
                scored_list.append(
                    ScoredObservation(
                        observation=obs,
                        relevance_score=relevance,
                        importance_score=importance_norm,
                        recency_score=recency,
                        final_score=final_score,
                    )
                )

        # Sort descending by final score
        scored_list.sort(key=lambda x: x.final_score, reverse=True)
        return scored_list[:n_results]

    def get_observation(self, obs_id: str) -> Optional[Observation]:
        """Fetch a specific observation by ID."""
        res = self.collection.get(ids=[obs_id], include=["documents", "metadatas"])
        ids = res.get("ids", [])
        if not ids:
            return None
        content = res["documents"][0]
        meta = res["metadatas"][0] if res.get("metadatas") else {}
        return Observation(
            id=obs_id,
            content=content,
            category=meta.get("category", "general"),
            importance=float(meta.get("importance", 5.0)),
            created_at=float(meta.get("created_at", time.time())),
            session_id=meta.get("session_id") or None,
        )

    def delete_observation(self, obs_id: str) -> bool:
        """Delete an observation by ID."""
        try:
            self.collection.delete(ids=[obs_id])
            return True
        except Exception:
            return False

    def count(self) -> int:
        """Count total observations stored."""
        return self.collection.count()

    def clear(self) -> None:
        """Reset the observational memory collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "description": "Agent Engine Observational Memory & Preferences",
                "hnsw:space": "cosine",
            },
        )
