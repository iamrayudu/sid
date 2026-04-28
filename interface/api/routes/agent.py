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


class OllamaHealth(BaseModel):
    healthy: bool
    stuck: bool
    last_ok_seconds_ago: Optional[int] = None
    last_fail_seconds_ago: Optional[int] = None
    last_error: Optional[str] = None
    base_url: str


class AgentStatus(BaseModel):
    state: str
    can_interrupt: bool
    suppressed_until: Optional[str] = None
    queue_depth: int
    ollama: OllamaHealth


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
    from services.llm_gateway import get_gateway
    fsm = get_fsm()
    info = fsm.status_dict()
    return AgentStatus(
        state=info["state"],
        can_interrupt=info["can_interrupt"],
        suppressed_until=info["suppressed_until"],
        queue_depth=await queue_depth(),
        ollama=OllamaHealth(**get_gateway().health_status()),
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


@router.get("/tasks")
async def tasks():
    """Return all pending extractions for the task panel."""
    from services.memory import get_store
    pending = await get_store().get_pending_tasks()
    return {
        "tasks": [
            {
                "id": t.id,
                "thought_id": t.thought_id,
                "content": t.content,
                "priority": t.priority,
                "status": t.status,
                "due_date": t.due_date,
                "milestone_parent_id": t.milestone_parent_id,
                "percentage_complete": t.percentage_complete,
                "next_step": t.next_step,
            }
            for t in pending
        ]
    }


@router.get("/recap")
async def recap(hours: int = 4):
    """LLM summary of the last N hours of thoughts."""
    from services.memory import get_store
    from services.llm_gateway import get_gateway
    store = get_store()
    gateway = get_gateway()

    since = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()

    # Fetch thoughts since cutoff (reuse timeline across recent days)
    thoughts = []
    for i in range(min(hours // 24 + 1, 2)):
        d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        day_thoughts = await store.get_timeline(d)
        thoughts.extend([t for t in day_thoughts if t.created_at >= since])

    if not thoughts:
        return {"recap": "Nothing captured in the last {} hours.".format(hours), "thought_count": 0}

    lines = []
    for t in thoughts[-30:]:
        ts = t.created_at[11:16] if len(t.created_at) >= 16 else ""
        text = t.summary or t.raw_text[:120]
        lines.append(f"[{ts}] [{t.type or '?'}] {text}")

    prompt = (
        f"Summarise the following {len(thoughts)} thoughts captured in the last {hours} hours. "
        "Be concise (3-5 sentences). Highlight any urgent tasks or important ideas.\n\n"
        + "\n".join(lines)
    )

    try:
        summary = await gateway.chat_for("checkin", [{"role": "user", "content": prompt}])
    except Exception as e:
        summary = f"Recap unavailable: {e}"

    return {"recap": summary, "thought_count": len(thoughts)}
