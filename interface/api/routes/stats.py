"""Stats route — usage dashboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.memory import get_store
from shared.schemas.models import StatsResult

router = APIRouter()


@router.get("", response_model=StatsResult)
async def stats() -> StatsResult:
    try:
        return await get_store().get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load stats: {e}")
