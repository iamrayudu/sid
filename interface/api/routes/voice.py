"""Voice routes — recording control with bulletproof state management.

F1 (Stability Sprint) — recording lifecycle hardened:
- An asyncio.Lock around all mutations so concurrent /start requests can't race.
- POST /voice/cancel — force-resets state (idempotent escape hatch).
- /voice/status now exposes session_id so the client can reconcile.
- Every state transition is logged at INFO so desyncs are diagnosable from logs.
- start_recording() is treated as the authoritative state set: success → state
  goes to RECORDING; any failure → state stays IDLE and exception bubbles.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from services.voice import get_voice_service
from services.memory import get_store

logger = logging.getLogger("sid.api.voice")
router = APIRouter()


# ── Single source of truth for recording state ────────────────────────────────
# A small struct + asyncio.Lock instead of bare globals. Every mutation goes
# through `_state_lock` so concurrent /start requests can't race past the
# "is recording?" check.

class _RecordingState:
    __slots__ = ("recording", "session_id", "started_at", "mode")

    def __init__(self):
        self.recording: bool = False
        self.session_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self.mode: Optional[str] = None  # "capture" | "reply"


_state = _RecordingState()
_state_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _log_transition(op: str, **fields) -> None:
    """Single helper so every state transition log line has the same shape."""
    bits = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("voice.%s %s", op, bits)


# ── Schemas ───────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    session_id: Optional[str] = None
    mode: Optional[str] = "capture"  # "capture" | "reply" — affects /stop vs /reply path


class StartResponse(BaseModel):
    session_id: str
    started_at: str
    mode: str


class StopRequest(BaseModel):
    session_id: str


class StopResponse(BaseModel):
    chunk_id: str
    raw_text: str
    duration_sec: float


class StatusResponse(BaseModel):
    recording: bool
    session_id: Optional[str] = None
    started_at: Optional[str] = None
    mode: Optional[str] = None
    queue_depth: int


class CancelResponse(BaseModel):
    was_recording: bool
    cleared_session_id: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _queue_depth() -> int:
    try:
        from services.processing import queue_depth
        return await queue_depth()
    except Exception:
        return 0


def _hard_reset_recorder() -> None:
    """Force the underlying recorder to a clean stopped state. Used by cancel."""
    try:
        svc = get_voice_service()
        if svc._recorder is not None and svc._recorder.is_recording:
            svc._recorder.stop()
    except Exception as e:
        logger.warning("voice.cancel hard_reset_recorder failed: %s", e)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartResponse)
async def start_recording(body: Optional[StartRequest] = None) -> StartResponse:
    """Start a recording session. Atomic — concurrent calls won't race."""
    async with _state_lock:
        if _state.recording:
            _log_transition(
                "start.rejected",
                reason="already_recording",
                current_session=_state.session_id,
            )
            raise HTTPException(
                status_code=409,
                detail=f"Already recording (session={_state.session_id}). Call /voice/cancel to force-reset.",
            )

        session_id = (body.session_id if body else None) or str(uuid.uuid4())
        mode = (body.mode if body else None) or "capture"
        started_at = _now_iso()

        _log_transition("start.requested", session=session_id, mode=mode)

        # Try to start the recorder. Failure → state stays IDLE.
        try:
            get_voice_service().start_recording()
        except Exception as e:
            _log_transition("start.failed", session=session_id, error=str(e)[:200])
            raise HTTPException(status_code=500, detail=f"Failed to start recording: {e}")

        # Recorder is running — commit state.
        _state.recording = True
        _state.session_id = session_id
        _state.started_at = started_at
        _state.mode = mode

        _log_transition("start.ok", session=session_id, mode=mode)

    # Persist session row OUTSIDE the lock (DB I/O shouldn't block other endpoints).
    try:
        date = started_at[:10]
        await get_store().create_session(session_id, started_at, date, mode=mode)
    except Exception as e:
        logger.warning("voice.start session_row_failed session=%s err=%s", session_id, e)

    return StartResponse(session_id=session_id, started_at=started_at, mode=mode)


@router.post("/stop")
async def stop_recording(body: StopRequest):
    """Stop recording and run the full capture path (transcribe → save → enqueue)."""
    async with _state_lock:
        if not _state.recording:
            _log_transition("stop.rejected", reason="not_recording")
            raise HTTPException(status_code=409, detail="Not currently recording")

        if body.session_id != _state.session_id:
            # Stale stop request — UI's session id doesn't match server's. Don't crash;
            # log and proceed using the server's actual session.
            logger.warning(
                "voice.stop session_mismatch client=%s server=%s; using server session",
                body.session_id, _state.session_id,
            )
            session_id = _state.session_id
        else:
            session_id = body.session_id

        _log_transition("stop.requested", session=session_id)

        voice = get_voice_service()
        try:
            chunk = await voice.stop_recording_and_process(session_id)
        except Exception as e:
            _state.recording = False
            _state.session_id = None
            _state.started_at = None
            _state.mode = None
            _log_transition("stop.failed", session=session_id, error=str(e)[:200])
            raise HTTPException(status_code=500, detail=f"Failed to process recording: {e}")

        _state.recording = False
        _state.session_id = None
        _state.started_at = None
        _state.mode = None
        _log_transition(
            "stop.ok",
            session=session_id,
            chunk_id=(chunk.chunk_id if chunk else None),
            duration_sec=(chunk.audio_duration_sec if chunk else 0.0),
        )

    if chunk is None:
        return Response(status_code=204)

    try:
        await get_store().save_raw_chunk(chunk)
    except Exception as e:
        logger.error("voice.stop save_chunk_failed chunk=%s err=%s", chunk.chunk_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to save chunk: {e}")

    try:
        await get_store().touch_session(session_id)
    except Exception as e:
        logger.warning("voice.stop session_touch_failed session=%s err=%s", session_id, e)

    # Fire-and-forget: enqueue for async processing (Stage 1 + Stage 2 pipeline)
    try:
        from services.processing import enqueue
        await enqueue(chunk)
        _log_transition("stop.enqueued", chunk_id=chunk.chunk_id)
    except Exception as e:
        logger.warning("voice.stop enqueue_failed chunk=%s err=%s", chunk.chunk_id, e)

    return StopResponse(
        chunk_id=chunk.chunk_id,
        raw_text=chunk.raw_text,
        duration_sec=chunk.audio_duration_sec,
    )


@router.post("/cancel", response_model=CancelResponse)
async def cancel_recording() -> CancelResponse:
    """Force-reset recording state. Idempotent escape hatch.

    Use when the client and server have desynced (e.g. user clicked Stop but
    sessionId was null on the client side). Always succeeds, even if the
    server thinks it isn't recording.
    """
    async with _state_lock:
        was_recording = _state.recording
        cleared_session = _state.session_id

        _hard_reset_recorder()
        _state.recording = False
        _state.session_id = None
        _state.started_at = None
        _state.mode = None

        _log_transition(
            "cancel",
            was_recording=was_recording,
            cleared_session=cleared_session,
        )

    return CancelResponse(
        was_recording=was_recording,
        cleared_session_id=cleared_session,
    )


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    """Voice subsystem state. Polled by the UI for client/server reconciliation."""
    return StatusResponse(
        recording=_state.recording,
        session_id=_state.session_id,
        started_at=_state.started_at,
        mode=_state.mode,
        queue_depth=await _queue_depth(),
    )


# ── B5: press-hold reply routing ──────────────────────────────────────────────
#
# Tap on the main RECORD button creates a fresh RawChunk via /voice/start +
# /voice/stop. Press-and-hold on the chat input is a REPLY: the audio is
# transcribed but NOT saved to thoughts. Instead the transcript is fed to the
# chat agent.
#
# F1: /reply also goes through the state lock + transition logging, and now
# tolerates a stale session_id (uses server's session if mismatch).


class ReplyRequest(BaseModel):
    session_id: str
    history: Optional[list] = None  # list[{"role","content"}] from the client's chat history


class ReplyResponse(BaseModel):
    transcript: str
    duration_sec: float
    chat_response: str
    tools_used: list
    took_ms: int
    question_count: int = 0
    mode: str = "answering"
    min_questions: int = 0
    bypassed: bool = False


@router.post("/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest) -> ReplyResponse:
    """Stop recording, transcribe, route through chat agent. NOT saved to thoughts."""
    async with _state_lock:
        if not _state.recording:
            _log_transition("reply.rejected", reason="not_recording")
            raise HTTPException(status_code=409, detail="Not currently recording")

        session_id = _state.session_id  # always use server truth
        _log_transition("reply.requested", session=session_id)

        voice = get_voice_service()
        try:
            chunk = await voice.stop_recording_and_process(session_id)
        except Exception as e:
            _state.recording = False
            _state.session_id = None
            _state.started_at = None
            _state.mode = None
            _log_transition("reply.failed", session=session_id, error=str(e)[:200])
            raise HTTPException(status_code=500, detail=f"Failed to process reply audio: {e}")

        _state.recording = False
        _state.session_id = None
        _state.started_at = None
        _state.mode = None

    if chunk is None or not chunk.raw_text.strip():
        _log_transition("reply.empty", session=session_id)
        raise HTTPException(status_code=204, detail="Empty audio (silence trimmed away)")

    transcript = chunk.raw_text.strip()
    duration = chunk.audio_duration_sec
    _log_transition(
        "reply.transcribed",
        session=session_id,
        duration_sec=duration,
        text_len=len(transcript),
    )

    from services.agent.chat_agent import chat as agent_chat
    history_msgs = []
    for m in body.history or []:
        if isinstance(m, dict) and "role" in m and "content" in m:
            history_msgs.append({"role": m["role"], "content": m["content"]})

    try:
        result = await agent_chat(transcript, history_msgs)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcribed '{transcript}' but chat failed: {e}",
        )

    return ReplyResponse(
        transcript=transcript,
        duration_sec=duration,
        chat_response=result.get("response", ""),
        tools_used=result.get("tools_used", []),
        took_ms=result.get("took_ms", 0),
        question_count=result.get("question_count", 0),
        mode=result.get("mode", "answering"),
        min_questions=result.get("min_questions", 0),
        bypassed=result.get("bypassed", False),
    )
