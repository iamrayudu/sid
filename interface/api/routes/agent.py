"""Agent routes — chat, status, manual triggers. Phase 3 stubs."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


_NOT_IMPL = "Phase 3 — not yet implemented"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None


class SuppressRequest(BaseModel):
    hours: Optional[int] = 2


class AgentStatus(BaseModel):
    state: str
    suppressed_until: Optional[str] = None
    queue_depth: int


@router.post("/chat")
async def chat(body: ChatRequest):
    raise HTTPException(status_code=501, detail=_NOT_IMPL)


@router.get("/status", response_model=AgentStatus)
async def status() -> AgentStatus:
    return AgentStatus(state="idle", suppressed_until=None, queue_depth=0)


@router.post("/suppress")
async def suppress(body: Optional[SuppressRequest] = None):
    raise HTTPException(status_code=501, detail=_NOT_IMPL)


@router.post("/morning")
async def morning():
    raise HTTPException(status_code=501, detail=_NOT_IMPL)


@router.post("/evening")
async def evening():
    raise HTTPException(status_code=501, detail=_NOT_IMPL)


@router.get("/daily")
async def daily(date: Optional[str] = None):
    raise HTTPException(status_code=501, detail=_NOT_IMPL)
