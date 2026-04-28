"""4-hour check-in — brief status question based on recent thoughts."""
from __future__ import annotations

import logging
from typing import List

from services.memory import get_store
from services.llm_gateway import get_gateway
from shared.schemas.models import Thought

logger = logging.getLogger("sid.agent.checkin")


def _fmt_recent(thoughts: List[Thought]) -> str:
    lines = []
    for th in thoughts[-8:]:
        ts = th.created_at[11:16] if len(th.created_at) >= 16 else ""
        text = th.summary or th.raw_text[:100]
        label = f"[{th.type}]" if th.type else ""
        lines.append(f"  {ts} {label} {text}")
    return "\n".join(lines) if lines else "  (nothing recent)"


async def generate_checkin(since_iso: str) -> str:
    store = get_store()
    gateway = get_gateway()

    # Get recent thoughts since last check-in
    all_recent = await store.get_timeline(since_iso[:10])
    # Filter to only thoughts after since_iso
    recent = [t for t in all_recent if t.created_at >= since_iso]
    count = len(recent)

    if count == 0:
        return ""

    prompt = f"""\
You are SID. Sudheer has added {count} new thoughts since the last check-in.

RECENT THOUGHTS:
{_fmt_recent(recent)}

Write a brief check-in message (max 60 words):
- Acknowledge what was captured (one specific callout)
- Ask ONE short status question about the most recent task or idea
- Keep it conversational, not formal

Do NOT say "I notice" or "it seems". Be direct.
"""

    try:
        msg = await gateway.chat_for("checkin", [{"role": "user", "content": prompt}])
        logger.info("Check-in generated for %d new thoughts", count)
        return msg.strip()
    except Exception as e:
        logger.error("Check-in generation failed: %s", e)
        return f"You've added {count} new thoughts. How's it going?"
