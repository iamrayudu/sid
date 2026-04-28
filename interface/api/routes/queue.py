"""Queue inspection routes — surface failed items so the user can retry or drop them."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/failed")
async def failed_items(limit: int = 50):
    from services.processing.queue import list_failed
    items = await list_failed(limit=limit)
    return {"failed": items, "count": len(items)}


@router.post("/retry/{chunk_id}")
async def retry_failed(chunk_id: str):
    from services.processing.queue import retry_chunk
    if not await retry_chunk(chunk_id):
        raise HTTPException(status_code=404, detail="No failed chunk with that id")
    return {"retried": chunk_id}


@router.delete("/{chunk_id}")
async def delete_chunk_route(chunk_id: str):
    from services.processing.queue import delete_chunk
    if not await delete_chunk(chunk_id):
        raise HTTPException(status_code=404, detail="No failed/done chunk with that id")
    return {"deleted": chunk_id}
