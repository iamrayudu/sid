"""Agent routes — chat, status, manual triggers, suppression."""
from __future__ import annotations

import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    response: str
    tools_used: List[str]
    took_ms: int


class SuppressRequest(BaseModel):
    hours: Optional[int] = 2


class AgentStatus(BaseModel):
    state: str
    can_interrupt: bool
    suppressed_until: Optional[str] = None
    queue_depth: int


class BriefResponse(BaseModel):
    text: str


class CritiqueResponse(BaseModel):
    report: str


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    from services.agent.chat_agent import chat as agent_chat
    history = [{"role": m.role, "content": m.content} for m in (body.history or [])]
    try:
        result = await agent_chat(body.message, history)
        return ChatResponse(
            response=result["response"],
            tools_used=result["tools_used"],
            took_ms=result["took_ms"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=AgentStatus)
async def status() -> AgentStatus:
    from services.agent.fsm import get_fsm
    from services.processing import queue_depth
    fsm = get_fsm()
    info = fsm.status_dict()
    return AgentStatus(
        state=info["state"],
        can_interrupt=info["can_interrupt"],
        suppressed_until=info["suppressed_until"],
        queue_depth=queue_depth(),
    )


@router.post("/suppress")
async def suppress(body: Optional[SuppressRequest] = None):
    from services.agent.fsm import get_fsm
    hours = (body.hours if body else None) or 2
    get_fsm().suppress(hours=hours)
    return {"suppressed_hours": hours}


@router.post("/morning", response_model=BriefResponse)
async def morning() -> BriefResponse:
    from services.agent.routines.morning import generate_morning_brief
    try:
        brief = await generate_morning_brief()
        return BriefResponse(text=brief)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evening", response_model=BriefResponse)
async def evening() -> BriefResponse:
    from services.agent.routines.evening import generate_evening_reflection
    try:
        reflection = await generate_evening_reflection()
        return BriefResponse(text=reflection)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weekly", response_model=BriefResponse)
async def weekly() -> BriefResponse:
    from services.agent.routines.weekly import generate_weekly_review
    try:
        review = await generate_weekly_review()
        return BriefResponse(text=review)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/critique", response_model=CritiqueResponse)
async def critique() -> CritiqueResponse:
    from services.agent.critique import get_negligence_report
    try:
        report = await get_negligence_report()
        return CritiqueResponse(report=report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily")
async def daily(date: Optional[str] = None):
    from services.memory import get_store
    target = date or datetime.date.today().isoformat()
    thoughts = await get_store().get_timeline(target)
    return {
        "date": target,
        "thought_count": len(thoughts),
        "thoughts": [
            {
                "id": t.id,
                "time": t.created_at[11:16] if len(t.created_at) >= 16 else "",
                "type": t.type,
                "summary": t.summary or t.raw_text[:120],
                "energy": t.energy_hint,
            }
            for t in thoughts
        ],
    }
