"""Thought routes — timeline, search, single fetch, extraction updates."""
from __future__ import annotations

import datetime
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.memory import get_store
from shared.schemas.models import SearchResult, Thought

router = APIRouter()


class TimelineResponse(BaseModel):
    date: str
    thoughts: List[Thought]
    session_count: int


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    took_ms: int


class ExtractionUpdate(BaseModel):
    status: Literal["done", "dropped", "in_progress", "pending"]


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(date: Optional[str] = Query(default=None)) -> TimelineResponse:
    if not date:
        date = datetime.date.today().isoformat()
    try:
        thoughts = await get_store().get_timeline(date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load timeline: {e}")
    session_count = len({t.session_id for t in thoughts})
    return TimelineResponse(date=date, thoughts=thoughts, session_count=session_count)


@router.get("/search", response_model=SearchResponse)
async def search(q: str = Query(..., min_length=1), limit: int = Query(default=10, ge=1, le=100)) -> SearchResponse:
    start = time.perf_counter()
    try:
        results = await get_store().search(q, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")
    took_ms = int((time.perf_counter() - start) * 1000)
    return SearchResponse(query=q, results=results, took_ms=took_ms)


@router.get("/{thought_id}", response_model=Thought)
async def get_thought(thought_id: str) -> Thought:
    try:
        thought = await get_store().get_thought(thought_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch thought: {e}")
    if thought is None:
        raise HTTPException(status_code=404, detail="Thought not found")
    return thought


@router.patch("/{thought_id}/extraction/{extraction_id}")
async def update_extraction(thought_id: str, extraction_id: str, body: ExtractionUpdate):
    store = get_store()
    update_fn = getattr(store, "update_extraction", None)
    if update_fn is None:
        raise HTTPException(
            status_code=501,
            detail="update_extraction not yet implemented (Phase 3)",
        )
    try:
        await update_fn(extraction_id, {"status": body.status})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
    return {"thought_id": thought_id, "extraction_id": extraction_id, "status": body.status}
