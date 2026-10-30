"""services/python/server/routers/memory.py

Memory API router for Agent Engine Sidecar Server.
Part of Task R1.14 (Split Monolithic API by Domain).
"""

from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Query

# Core domain imports

# Services container, schemas, errors, transport, dependencies
from services.python.server.container import (
    memory_instance,
    observational_memory_instance,
)
from services.python.server.schemas import *

logger = logging.getLogger("agent_engine.api.memory")
router = APIRouter(tags=["memory"])


@router.get("/memory", response_model=MemoryQueryResponse)
async def query_memory(
    query: str = Query(..., description="Semantic search query"),
    top_k: int = Query(5, ge=1, le=50, description="Max passages to retrieve"),
):
    """Retrieve passages from the ChromaDB vector database."""
    passages = memory_instance.retrieve_passages(query, n_results=top_k)
    return MemoryQueryResponse(query=query, passages=passages)


@router.post("/memory", response_model=IngestMemoryResponse)
@router.post("/memory/ingest", response_model=IngestMemoryResponse)
async def ingest_memory(req: IngestMemoryRequest):
    """Index text content into ChromaDB vector memory."""
    now_iso = datetime.datetime.now().isoformat()
    ids = memory_instance.add_documents(
        documents=[req.content],
        metadatas=[{"source": req.source, "timestamp": now_iso}],
    )
    return IngestMemoryResponse(document_id=ids[0], count=memory_instance.count())


@router.post("/memory/observe", response_model=ObservationRecordResponse)
async def record_observation(req: ObservationRecordRequest):
    """Record an atomic observation, user preference, or project fact into observational memory."""
    obs = observational_memory_instance.record_observation(
        content=req.content,
        category=req.category,
        importance=req.importance,
        session_id=req.session_id,
        metadata=req.metadata,
    )
    return ObservationRecordResponse(
        id=obs.id,
        content=obs.content,
        category=obs.category,
        importance=obs.importance,
        created_at=obs.created_at,
        session_id=obs.session_id,
    )


@router.get("/memory/observations", response_model=ObservationQueryResponse)
async def query_observations(
    query: str = Query(..., description="Query to search observational memory"),
    top_k: int = Query(5, ge=1, le=50, description="Max observations to retrieve"),
    alpha: float = Query(0.5, ge=0.0, le=1.0, description="Weight for semantic relevance"),
    beta: float = Query(0.3, ge=0.0, le=1.0, description="Weight for importance score"),
    gamma: float = Query(0.2, ge=0.0, le=1.0, description="Weight for recency/temporal decay"),
    decay_lambda: float = Query(0.05, ge=0.0, description="Temporal decay rate per day"),
):
    """Retrieve observations scored by semantic relevance, importance, and temporal decay."""
    scored = observational_memory_instance.query_observations(
        query=query,
        n_results=top_k,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        decay_lambda=decay_lambda,
    )
    items = [
        ScoredObservationItem(
            id=s.observation.id,
            content=s.observation.content,
            category=s.observation.category,
            importance=s.observation.importance,
            created_at=s.observation.created_at,
            session_id=s.observation.session_id,
            relevance_score=s.relevance_score,
            importance_score=s.importance_score,
            recency_score=s.recency_score,
            final_score=s.final_score,
        )
        for s in scored
    ]
    return ObservationQueryResponse(query=query, observations=items)
