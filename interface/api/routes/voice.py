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


# ---- Module-level recording state ---------------------------------------
_recording: bool = False
_current_session_id: Optional[str] = None


def _queue_depth() -> int:
    try:
        from services.processing import queue as _q  # type: ignore
        # Try a few common attribute names
        for attr in ("queue_depth", "depth", "size"):
            fn = getattr(_q, attr, None)
            if callable(fn):
                try:
                    return int(fn())
                except Exception:
                    pass
        q = getattr(_q, "_queue", None) or getattr(_q, "queue", None)
        if q is not None and hasattr(q, "qsize"):
            return int(q.qsize())
    except ImportError:
        pass
    except Exception:
        pass
    return 0


# ---- Request/response models --------------------------------------------
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


# ---- Endpoints ----------------------------------------------------------
@router.post("/start", response_model=StartResponse)
async def start_recording(body: Optional[StartRequest] = None) -> StartResponse:
    global _recording, _current_session_id

    if _recording:
        raise HTTPException(status_code=409, detail="Already recording")

    session_id = (body.session_id if body else None) or str(uuid.uuid4())
    started_at = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        get_voice_service().start_recording()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start recording: {e}")

    _recording = True
    _current_session_id = session_id
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
        queue_depth=_queue_depth(),
    )
