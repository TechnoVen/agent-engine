from typing import Any, Dict, List

import numpy  # noqa: F401 - Must be pre-imported before dspy/FastAPI dependencies
import pytest
from fastapi.testclient import TestClient

from core.memory.observational import (
    Observation,
    ObservationalMemory,
    PreferenceExtractor,
    ScoredObservation,
    SessionSummarizer,
)
from services.python.server.api import app


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def temp_memory(tmp_path):
    persist_dir = str(tmp_path / "chroma_obs_test")
    mem = ObservationalMemory(
        persist_directory=persist_dir,
        collection_name="test_observations",
    )
    yield mem
    mem.clear()


class TestPreferenceExtractor:
    """Test deterministic rule-based preference and fact extraction."""

    def test_extract_explicit_preferences(self):
        text = "I prefer dark mode in all UI components instead of light mode."
        extracted = PreferenceExtractor.extract_from_text(text)
        assert len(extracted) >= 1
        pref = extracted[0]
        assert pref["category"] == "preference"
        assert "dark mode" in pref["content"]
        assert pref["importance"] >= 8.0

    def test_extract_mandatory_positive_directive(self):
        text = "Always use TypeScript for new frontend components."
        extracted = PreferenceExtractor.extract_from_text(text)
        assert len(extracted) >= 1
        assert extracted[0]["category"] == "preference"
        assert "TypeScript" in extracted[0]["content"]
        assert extracted[0]["importance"] >= 8.5

    def test_extract_mandatory_negative_directive(self):
        text = "Never use eval in python code."
        extracted = PreferenceExtractor.extract_from_text(text)
        assert len(extracted) >= 1
        assert extracted[0]["category"] == "preference"
        assert "eval" in extracted[0]["content"]
        assert extracted[0]["importance"] >= 9.0

    def test_extract_project_fact(self):
        text = "My project uses FastAPI and ChromaDB."
        extracted = PreferenceExtractor.extract_from_text(text)
        assert len(extracted) >= 1
        assert extracted[0]["category"] == "project_fact"
        assert "FastAPI" in extracted[0]["content"]

    def test_extract_empty_or_neutral_text(self):
        assert PreferenceExtractor.extract_from_text("") == []
        assert PreferenceExtractor.extract_from_text("   ") == []
        assert PreferenceExtractor.extract_from_text("The sky is blue today.") == []


class TestSessionSummarizer:
    """Test session summarization and importance calculation."""

    def test_calculate_importance_high_signal(self):
        text = "This is a critical security architecture decision for production auth."
        importance = SessionSummarizer.calculate_importance(text)
        assert importance >= 7.0

    def test_calculate_importance_casual_greetings(self):
        assert SessionSummarizer.calculate_importance("hello") <= 2.5
        assert SessionSummarizer.calculate_importance("thanks, ok") <= 2.5

    def test_summarize_session_turns(self):
        messages = [
            {"role": "user", "content": "Hello there!"},
            {"role": "assistant", "content": "Hi! How can I assist you?"},
            {
                "role": "user",
                "content": "Please remember that we must always use PyDantic v2 for data models.",
            },
            {"role": "assistant", "content": "Got it, I will remember PyDantic v2."},
        ]
        observations = SessionSummarizer.summarize_session_turns(messages, session_id="sess_test")
        assert len(observations) >= 1
        # The explicit preference should be extracted
        pref_obs = [o for o in observations if "PyDantic" in o["content"]]
        assert len(pref_obs) >= 1
        assert pref_obs[0]["category"] == "preference"
        assert pref_obs[0]["importance"] >= 8.0


class TestObservationDataclass:
    """Test Observation and ScoredObservation serialization."""

    def test_observation_to_dict(self):
        obs = Observation(
            id="obs_123",
            content="User prefers vim keybindings",
            category="preference",
            importance=8.5,
            created_at=1700000000.0,
            session_id="sess_1",
        )
        d = obs.to_dict()
        assert d["id"] == "obs_123"
        assert d["content"] == "User prefers vim keybindings"
        assert d["importance"] == 8.5
        assert d["category"] == "preference"

    def test_scored_observation_to_dict(self):
        obs = Observation(
            id="obs_123",
            content="User prefers vim keybindings",
            category="preference",
            importance=8.5,
            created_at=1700000000.0,
        )
        scored = ScoredObservation(
            observation=obs,
            relevance_score=0.9,
            importance_score=0.85,
            recency_score=0.75,
            final_score=0.84,
        )
        d = scored.to_dict()
        assert d["relevance_score"] == 0.9
        assert d["importance_score"] == 0.85
        assert d["recency_score"] == 0.75
        assert d["final_score"] == 0.84


class TestTemporalDecayAndRetrieval:
    """Test Stanford Generative Agents temporal decay and observational memory retrieval."""

    def test_temporal_decay_math(self, temp_memory):
        now = 1700000000.0  # reference time point

        # Add 3 observations:
        # 1. 0 days old (today), moderate importance (5.0)
        # 2. 7 days old, high importance (9.5) - explicit preference
        # 3. 30 days old, low importance (3.0)
        now_ts = now
        seven_days_ago = now - (7 * 86400.0)
        thirty_days_ago = now - (30 * 86400.0)

        temp_memory.record_observation(
            obs_id="obs_today",
            content="General python scripting notes and updates",
            category="general",
            importance=5.0,
            created_at=now_ts,
        )

        temp_memory.record_observation(
            obs_id="obs_7d_pref",
            content="Always use PostgreSQL instead of MySQL for relational data",
            category="preference",
            importance=9.5,
            created_at=seven_days_ago,
        )

        temp_memory.record_observation(
            obs_id="obs_30d_old",
            content="Casual meeting discussion about weather and lunch",
            category="general",
            importance=2.0,
            created_at=thirty_days_ago,
        )

        # Query specifically for database preference
        results = temp_memory.query_observations(
            query="Which database should I use for storing relational data?",
            n_results=3,
            current_time=now,
            alpha=0.5,
            beta=0.3,
            gamma=0.2,
            decay_lambda=0.05,
        )

        assert len(results) > 0
        top = results[0]
        # Even though obs_7d_pref is 7 days old, its high relevance and high importance
        # must cause it to outrank recent unrelated chatter!
        assert top.observation.id == "obs_7d_pref"
        assert top.recency_score < 1.0  # Decayed from 1.0
        assert top.recency_score > 0.65  # e^(-0.05 * 7) ~= 0.7047
        assert top.importance_score >= 0.9

    def test_record_session_and_retrieve(self, temp_memory):
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": "I prefer dark mode in the editor."},
            {"role": "assistant", "content": "I will make note of that."},
            {"role": "user", "content": "Also note that the backend is built with FastAPI."},
        ]

        recorded = temp_memory.record_session(session_id="sess_unit_test", messages=messages)
        assert len(recorded) >= 2

        results = temp_memory.query_observations(
            query="What theme does the user prefer?",
            n_results=1,
        )
        assert len(results) == 1
        assert "dark mode" in results[0].observation.content.lower()

    def test_crud_lifecycle(self, temp_memory):
        obs = temp_memory.record_observation(
            content="User prefers 4-space indentation",
            category="preference",
            importance=8.0,
        )
        assert temp_memory.count() == 1

        fetched = temp_memory.get_observation(obs.id)
        assert fetched is not None
        assert fetched.content == "User prefers 4-space indentation"

        deleted = temp_memory.delete_observation(obs.id)
        assert deleted is True
        assert temp_memory.count() == 0


class TestObservationalMemoryAPI:
    """Test sidecar FastAPI endpoints for Observational Memory."""

    def test_api_observe_and_query_flow(self, test_client):
        # 1. Record an observation via POST /v1/memory/observe
        obs_payload = {
            "content": "I prefer to use Tailwind CSS for UI styling instead of styled-components.",
            "category": "preference",
            "importance": 9.0,
            "session_id": "sess_api_test",
        }
        resp = test_client.post("/v1/memory/observe", json=obs_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("obs_")
        assert "Tailwind CSS" in data["content"]
        assert data["importance"] == 9.0

        # 2. Query observations via GET /v1/memory/observations
        query_resp = test_client.get(
            "/v1/memory/observations",
            params={
                "query": "Which CSS framework do I prefer?",
                "top_k": 3,
                "alpha": 0.5,
                "beta": 0.3,
                "gamma": 0.2,
            },
        )
        assert query_resp.status_code == 200
        q_data = query_resp.json()
        assert q_data["query"] == "Which CSS framework do I prefer?"
        assert len(q_data["observations"]) >= 1

        top_obs = q_data["observations"][0]
        assert "Tailwind CSS" in top_obs["content"]
        assert "final_score" in top_obs
        assert "recency_score" in top_obs
        assert "relevance_score" in top_obs
        assert "importance_score" in top_obs
        assert top_obs["final_score"] > 0.0
