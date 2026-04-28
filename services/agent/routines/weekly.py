"""Weekly review — deep behavioral autopsy + negligence detection."""
from __future__ import annotations

import datetime
import logging
from typing import List

from services.memory import get_store
from services.llm_gateway import get_gateway
from shared.schemas.models import Thought, Extraction

logger = logging.getLogger("sid.agent.weekly")


def _last_7_days() -> List[str]:
    today = datetime.date.today()
    return [(today - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]


def _fmt_thoughts_by_day(thoughts_by_day: dict) -> str:
    lines = []
    for date, thoughts in sorted(thoughts_by_day.items()):
        day_name = datetime.date.fromisoformat(date).strftime("%A %-d %b")
        lines.append(f"\n{day_name} ({len(thoughts)} thoughts):")
        for th in thoughts[:10]:
            label = f"[{th.type}]" if th.type else ""
            energy = f"({th.energy_hint})" if th.energy_hint else ""
            text = th.summary or th.raw_text[:100]
            lines.append(f"  {label} {energy} {text}")
        if len(thoughts) > 10:
            lines.append(f"  ... and {len(thoughts) - 10} more")
    return "\n".join(lines) if lines else "  (no thoughts this week)"


def _fmt_stale_tasks(tasks: List[Extraction]) -> str:
    if not tasks:
        return "  (none)"
    return "\n".join(
        f"  [{t.priority}] {t.content} (created: {t.id[:8]}...)"
        for t in tasks[:20]
    )


async def generate_weekly_review() -> str:
    store = get_store()
    gateway = get_gateway()

    days = _last_7_days()
    thoughts_by_day: dict[str, List[Thought]] = {}
    total_count = 0

    for day in days:
        day_thoughts = await store.get_timeline(day)
        if day_thoughts:
            thoughts_by_day[day] = day_thoughts
            total_count += len(day_thoughts)

    pending_tasks = await store.get_pending_tasks()
    # Tasks pending for >3 days are stale
    cutoff = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    stale_tasks = [t for t in pending_tasks if t.due_date and t.due_date < cutoff]
    stale_tasks += [t for t in pending_tasks if not t.due_date][:10]

    week_start = days[0]
    week_end = days[-1]

    prompt = f"""\
You are SID's critique engine. Generate Sudheer's weekly behavioral review for {week_start} → {week_end}.

WEEKLY THOUGHTS ({total_count} total):
{_fmt_thoughts_by_day(thoughts_by_day)}

STALE/PENDING TASKS (open, may be neglected):
{_fmt_stale_tasks(stale_tasks)}

Write a weekly review with these sections:

1. VOLUME & PATTERN
   - How many thoughts per day? Consistent or sporadic?
   - What types dominated (ideas, tasks, reflections)?
   - Energy pattern across the week

2. EXECUTION ANALYSIS
   - Tasks completed vs. created ratio (estimate from what you see)
   - Which domains got action? Which got only words?
   - Any tasks mentioned multiple times but never resolved?

3. BEHAVIORAL AUTOPSY (be honest and direct)
   - What is Sudheer consistently avoiding or procrastinating?
   - Where is there a gap between stated intent and action?
   - What recurring theme keeps surfacing without resolution?

4. NEXT WEEK FOCUS
   - One thing to stop doing
   - One thing to double down on
   - One specific commitment to make (concrete, measurable)

Rules:
- Max 400 words
- Be analytically honest — this is a behavioral mirror, not motivation
- Reference specific thoughts/tasks by content when making observations
- No fluff, no softening. Sudheer asked for this level of honesty.
"""

    try:
        review = await gateway.chat_for("weekly", [{"role": "user", "content": prompt}])
        logger.info("Weekly review generated (%d thoughts across %d days)", total_count, len(thoughts_by_day))
        return review
    except Exception as e:
        logger.error("Weekly review failed: %s", e)
        return f"Weekly review unavailable ({e})."
