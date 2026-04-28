"""Evening reflection — journal narrative + task completion analysis."""
from __future__ import annotations

import datetime
import logging
from typing import List

from services.memory import get_store
from services.llm_gateway import get_gateway
from shared.schemas.models import Thought, Extraction

logger = logging.getLogger("sid.agent.evening")


def _fmt_thoughts(thoughts: List[Thought]) -> str:
    if not thoughts:
        return "  (nothing captured today)"
    lines = []
    for th in thoughts:
        ts = th.created_at[11:16] if len(th.created_at) >= 16 else ""
        label = f"[{th.type}]" if th.type else ""
        text = th.summary or th.raw_text[:150]
        energy = f" ({th.energy_hint})" if th.energy_hint else ""
        lines.append(f"  {ts} {label} {text}{energy}")
    return "\n".join(lines)


def _fmt_tasks(tasks: List[Extraction]) -> str:
    if not tasks:
        return "  (none pending)"
    return "\n".join(f"  [{t.status}] {t.content}" for t in tasks[:15])


async def generate_evening_reflection() -> str:
    store = get_store()
    gateway = get_gateway()

    today = datetime.date.today().isoformat()
    today_thoughts = await store.get_timeline(today)
    pending = await store.get_pending_tasks()

    # Separate today's tasks from older ones
    today_tasks = [t for t in pending if t.due_date == today or t.due_date is None]

    prompt = f"""\
You are SID. Generate Sudheer's evening reflection for {today}.

TODAY'S THOUGHTS ({len(today_thoughts)} captured):
{_fmt_thoughts(today_thoughts)}

PENDING TASKS (still open):
{_fmt_tasks(today_tasks)}

Write an evening reflection with:
1. JOURNAL — 2-3 sentences, first person, honest summary of the day's mental activity
2. DONE vs PENDING — brief tally of what moved vs. what's still open
3. PATTERN — one behavioral insight you notice (energy shifts, avoidance, focus quality)
4. TOMORROW — 2 specific things to carry forward

Rules:
- Max 250 words
- Be honest, slightly critical if warranted — Sudheer wants signal not comfort
- Reference specific thoughts/tasks by content when relevant
"""

    try:
        reflection = await gateway.chat_for("evening", [{"role": "user", "content": prompt}])
        await store.save_daily_reflection(today, reflection)
        logger.info("Evening reflection saved for %s", today)
        return reflection
    except Exception as e:
        logger.error("Evening reflection failed: %s", e)
        return f"Evening reflection unavailable ({e})."
