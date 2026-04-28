"""Chat agent — conversational memory retrieval with interrogation mode.

Interrogation mode: for broad or ambiguous questions, SID asks 5-20 targeted
clarifying questions BEFORE searching memory and answering. This prevents generic
responses and forces the user to articulate what they actually want.

Architecture: LangGraph ReAct agent with memory tools.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from typing import List, Dict, Any, Optional, Annotated

from pydantic import BaseModel, Field

from services.memory import get_store
from services.llm_gateway import get_gateway

logger = logging.getLogger("sid.agent.chat")


# ── Memory tools (async, called by the agent) ─────────────────────────────────

async def _tool_search_memory(query: str) -> str:
    """Search Sudheer's personal memory for past thoughts and ideas."""
    try:
        results = await get_store().search(query, limit=8)
        if not results:
            return "No relevant memories found."
        lines = []
        for r in results:
            date = r.date[:10] if r.date else "?"
            lines.append(f"[{date}] [{r.type or '?'}] {r.text[:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Memory search failed: {e}"


async def _tool_get_pending_tasks() -> str:
    """Get all pending tasks and action items."""
    try:
        tasks = await get_store().get_pending_tasks()
        if not tasks:
            return "No pending tasks."
        lines = [f"[{t.priority}] {t.content}" + (f" (due: {t.due_date})" if t.due_date else "")
                 for t in tasks[:20]]
        return "\n".join(lines)
    except Exception as e:
        return f"Task retrieval failed: {e}"


async def _tool_get_today() -> str:
    """Get all thoughts from today."""
    try:
        today = datetime.date.today().isoformat()
        thoughts = await get_store().get_timeline(today)
        if not thoughts:
            return "Nothing captured today yet."
        lines = []
        for th in thoughts:
            ts = th.created_at[11:16] if len(th.created_at) >= 16 else ""
            text = th.summary or th.raw_text[:150]
            lines.append(f"{ts} [{th.type or '?'}] {text}")
        return "\n".join(lines)
    except Exception as e:
        return f"Timeline retrieval failed: {e}"


async def _tool_plan_task(task_id: str, context: str = "") -> str:
    """Break a pending parent task into concrete milestones.

    The chat agent uses this when the user says things like "plan the X task"
    or "help me break this down". Returns a human-readable summary of the
    saved milestones; the UI separately renders them via /api/agent/milestones.
    """
    try:
        from services.agent.routines.milestone import plan_and_persist
        store = get_store()
        parent = await store.get_extraction(task_id)
        if parent is None:
            return f"No task found with id {task_id}."
        if parent.status == "done":
            return f"Task {task_id} is already done — nothing to plan."

        saved = await plan_and_persist(parent, user_context=context)
        lines = [f"Planned {len(saved)} milestone(s) for: {parent.content}"]
        for i, m in enumerate(saved, 1):
            est = f" (~{m.time_estimate_hours}h)" if m.time_estimate_hours else ""
            lines.append(f"  {i}. [P{m.priority}] {m.content}{est}")
            if m.next_step:
                lines.append(f"     next: {m.next_step}")
        return "\n".join(lines)
    except Exception as e:
        return f"Milestone planning failed: {e}"


async def _tool_get_date(date: str) -> str:
    """Get thoughts from a specific date (YYYY-MM-DD)."""
    try:
        thoughts = await get_store().get_timeline(date)
        if not thoughts:
            return f"Nothing captured on {date}."
        lines = []
        for th in thoughts:
            ts = th.created_at[11:16] if len(th.created_at) >= 16 else ""
            text = th.summary or th.raw_text[:150]
            lines.append(f"{ts} [{th.type or '?'}] {text}")
        return f"Thoughts on {date}:\n" + "\n".join(lines)
    except Exception as e:
        return f"Timeline retrieval failed: {e}"


# ── Agent system prompt ────────────────────────────────────────────────────────

_SYSTEM = """\
You are SID — Sudheer's personal cognitive companion with access to his complete thought history.

Your character:
- Direct, concise, and honest — Sudheer thinks fast, match his pace
- Challenge ideas when you see contradictions with past thoughts
- Surface patterns across days when they're relevant
- Reference specific past thoughts by date when useful
- Never make up information not in memory

Available tools:
- search_memory(query): semantic search across all thoughts
- get_pending_tasks(): all open tasks
- get_today(): today's timeline
- get_date(date): a specific day's thoughts
- plan_task(task_id, context?): break a parent task into 2-7 concrete milestones
  (use when Sudheer asks to plan, break down, or scope a specific task)

INTERROGATION MODE:
When a question is broad, vague, or could have many interpretations — ask 2-5 sharp
clarifying questions BEFORE searching memory. Format: "Before I search, let me ask:"
followed by numbered questions. Wait for answers, then proceed with targeted search.

Do NOT interrogate for simple factual lookups like "what tasks are pending" or "what
did I capture today".
"""

# ── Tool dispatcher ────────────────────────────────────────────────────────────

_TOOLS = {
    "search_memory": lambda args: _tool_search_memory(args.get("query", "")),
    "get_pending_tasks": lambda args: _tool_get_pending_tasks(),
    "get_today": lambda args: _tool_get_today(),
    "get_date": lambda args: _tool_get_date(args.get("date", datetime.date.today().isoformat())),
    "plan_task": lambda args: _tool_plan_task(args.get("task_id", ""), args.get("context", "")),
}

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Semantic search across all of Sudheer's captured thoughts",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_tasks",
            "description": "Get all pending/open tasks and action items",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today",
            "description": "Get all thoughts captured today",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_date",
            "description": "Get thoughts from a specific date",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "Date in YYYY-MM-DD format"}},
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_task",
            "description": (
                "Break a pending parent task into 2-7 concrete milestones. "
                "Use when the user asks to plan, break down, or scope out a task. "
                "Re-running on the same task adds new steps without duplicating existing ones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": (
                            "The parent extraction id to break down. Get this from "
                            "get_pending_tasks first if you don't have it."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Optional free text from the user about constraints, "
                            "energy level, available time. Pass through verbatim."
                        ),
                    },
                },
                "required": ["task_id"],
            },
        },
    },
]


# ── ReAct loop ─────────────────────────────────────────────────────────────────

async def chat(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    max_tool_rounds: int = 6,
) -> Dict[str, Any]:
    """
    Process a chat message. Returns {response, tools_used, took_ms}.
    Handles tool calls in a ReAct loop (think → act → observe → repeat).
    """
    import time
    start = time.perf_counter()
    tools_used: List[str] = []

    gateway = get_gateway()
    # config_for() honours per-purpose route overrides (e.g. agent_chat → anthropic).
    model, _provider, client = gateway.config_for("agent_chat")

    messages: List[Dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    if history:
        messages.extend(history[-20:])  # keep last 20 turns for context
    messages.append({"role": "user", "content": message})

    # ReAct loop
    for _ in range(max_tool_rounds):
        call_start = time.perf_counter()
        response = None
        success = True
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except Exception:
            success = False
            raise
        finally:
            call_ms = int((time.perf_counter() - call_start) * 1000)
            pt = response.usage.prompt_tokens if response and response.usage else 0
            ct = response.usage.completion_tokens if response and response.usage else 0
            await gateway._record_call(model, "agent_chat", pt, ct, call_ms, success)

        msg = response.choices[0].message

        # No tool calls — final answer
        if not msg.tool_calls:
            final_text = msg.content or ""
            took_ms = int((time.perf_counter() - start) * 1000)
            logger.info("Chat completed in %dms, tools: %s", took_ms, tools_used)
            return {
                "response": final_text,
                "tools_used": tools_used,
                "took_ms": took_ms,
            }

        # Execute all tool calls in this round
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tools_used.append(tool_name)

            import json
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}

            tool_fn = _TOOLS.get(tool_name)
            if tool_fn:
                try:
                    result = await tool_fn(args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {tool_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Exceeded max rounds — return whatever we have
    took_ms = int((time.perf_counter() - start) * 1000)
    return {
        "response": "I hit the reasoning limit. Try a more specific question.",
        "tools_used": tools_used,
        "took_ms": took_ms,
    }
