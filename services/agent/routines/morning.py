"""Morning brief — structured day plan from pending tasks + yesterday's thoughts."""
from __future__ import annotations

import datetime
import logging
from typing import List

from services.memory import get_store
from services.llm_gateway import get_gateway
from shared.schemas.models import Thought, Extraction

logger = logging.getLogger("sid.agent.morning")


def _fmt_tasks(tasks: List[Extraction]) -> str:
    if not tasks:
        return "  (none)"
    lines = []
    for t in tasks[:20]:
        due = f" [due: {t.due_date}]" if t.due_date else ""
        lines.append(f"  [{t.priority}] {t.content}{due}")
    return "\n".join(lines)


def _fmt_thoughts(thoughts: List[Thought]) -> str:
    if not thoughts:
        return "  (nothing captured)"
    lines = []
    for th in thoughts[:30]:
        label = f"[{th.type or '?'}]" if th.type else ""
        text = th.summary or th.raw_text[:120]
        lines.append(f"  {label} {text}")
    return "\n".join(lines)


async def generate_morning_brief() -> str:
    store = get_store()
    gateway = get_gateway()

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    today = datetime.date.today().isoformat()

    pending = await store.get_pending_tasks()
    yesterday_thoughts = await store.get_timeline(yesterday)

    prompt = f"""\
You are SID, Sudheer's cognitive companion. Generate his morning brief for {today}.

PENDING TASKS (ordered by priority, 1=urgent):
{_fmt_tasks(pending)}

YESTERDAY'S THOUGHTS:
{_fmt_thoughts(yesterday_thoughts)}

Write a morning brief with these sections:
1. TOP 3 PRIORITIES TODAY — pick the highest-leverage items, add a time estimate each
2. CARRY-FORWARD IDEA — one idea from yesterday worth thinking about today
3. DAILY ANCHOR — one focused question or intention to guide the day

Rules:
- Max 200 words total
- Direct and actionable — no fluff, no preamble
- If pending tasks are empty, focus on creative or strategic work based on recent thoughts
- Speak in second person ("You have...", "Your top priority...")
"""

    try:
        brief = await gateway.chat_for("morning", [{"role": "user", "content": prompt}])
        logger.info("Morning brief generated (%d chars)", len(brief))
        return brief
    except Exception as e:
        logger.error("Morning brief generation failed: %s", e)
        return f"Morning brief unavailable ({e}). Check pending tasks manually."
