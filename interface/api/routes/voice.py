"""Voice routes — recording control."""
from __future__ import annotations

import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from services.voice import get_voice_service
from services.memory import get_store

router = APIRouter()


_recording: bool = False
_current_session_id: Optional[str] = None


class StartRequest(BaseModel):
    session_id: Optional[str] = None


class StartResponse(BaseModel):
    session_id: str
    started_at: str


class StopRequest(BaseModel):
    session_id: str


class StopResponse(BaseModel):
    chunk_id: str
    raw_text: str
    duration_sec: float


class StatusResponse(BaseModel):
    recording: bool
    session_id: Optional[str] = None
    queue_depth: int


async def _queue_depth() -> int:
    try:
        from services.processing import queue_depth
        return await queue_depth()
    except Exception:
        return 0


@router.post("/start", response_model=StartResponse)
async def start_recording(body: Optional[StartRequest] = None) -> StartResponse:
    global _recording, _current_session_id

    if _recording:
        raise HTTPException(status_code=409, detail="Already recording")

    session_id = (body.session_id if body else None) or str(uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        get_voice_service().start_recording()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start recording: {e}")

    _recording = True
    _current_session_id = session_id

    try:
        date = started_at[:10]
        await get_store().create_session(session_id, started_at, date)
    except Exception as e:
        import logging
        logging.getLogger("sid.api.voice").warning("Failed to create session %s: %s", session_id, e)

    return StartResponse(session_id=session_id, started_at=started_at)


@router.post("/stop")
async def stop_recording(body: StopRequest):
    global _recording, _current_session_id

    if not _recording:
        raise HTTPException(status_code=409, detail="Not currently recording")

    voice = get_voice_service()
    try:
        chunk = await voice.stop_recording_and_process(body.session_id)
    except Exception as e:
        _recording = False
        _current_session_id = None
        raise HTTPException(status_code=500, detail=f"Failed to process recording: {e}")

    _recording = False
    _current_session_id = None

    if chunk is None:
        return Response(status_code=204)

    try:
        await get_store().save_raw_chunk(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save chunk: {e}")

    try:
        await get_store().touch_session(body.session_id)
    except Exception as e:
        import logging
        logging.getLogger("sid.api.voice").warning("Failed to update session %s: %s", body.session_id, e)

    # Fire-and-forget: enqueue for async processing (Stage 1 + Stage 2 pipeline)
    try:
        from services.processing import enqueue
        await enqueue(chunk)
    except Exception as e:
        # Non-fatal: chunk is saved in DB, processing can be retried
        import logging
        logging.getLogger("sid.api.voice").warning("Failed to enqueue chunk %s: %s", chunk.chunk_id, e)

    return StopResponse(
        chunk_id=chunk.chunk_id,
        raw_text=chunk.raw_text,
        duration_sec=chunk.audio_duration_sec,
    )


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(
        recording=_recording,
        session_id=_current_session_id,
        queue_depth=await _queue_depth(),
    )
