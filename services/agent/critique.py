"""Critique engine — behavioral profiling and negligence detection.

Runs on demand or as part of the weekly review.
Identifies patterns of avoidance, repeated unresolved ideas, and execution gaps.
"""
from __future__ import annotations

import datetime
import logging
from collections import Counter
from typing import List

from pydantic import BaseModel, Field

from services.memory import get_store
from services.llm_gateway import get_gateway
from shared.schemas.models import Thought, Extraction

logger = logging.getLogger("sid.agent.critique")


class BehavioralProfile(BaseModel):
    avoidance_patterns: List[str] = Field(default_factory=list, description="Topics/tasks consistently avoided")
    recurring_unresolved: List[str] = Field(default_factory=list, description="Ideas mentioned 3+ times with no action")
    execution_gap_score: float = Field(default=0.0, ge=0.0, le=1.0, description="0=all talk, 1=all action")
    dominant_thought_types: List[str] = Field(default_factory=list)
    energy_pattern: str = Field(default="", description="Energy arc across the period")
    top_themes: List[str] = Field(default_factory=list, description="Top 5 recurring themes")
    negligence_flags: List[str] = Field(default_factory=list, description="Specific items needing attention")
    critique_summary: str = Field(default="", description="2-sentence honest behavioral summary")


async def build_behavioral_profile(days: int = 14) -> BehavioralProfile:
    """Analyze the last N days and return a structured behavioral profile."""
    store = get_store()
    gateway = get_gateway()

    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    # Get all thoughts in period
    all_thoughts: List[Thought] = []
    for i in range(days):
        day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        day_thoughts = await store.get_timeline(day)
        all_thoughts.extend(day_thoughts)

    pending = await store.get_pending_tasks()
    old_pending = [t for t in pending if t.due_date and t.due_date < cutoff]
    old_pending += [t for t in pending if not t.due_date]

    if not all_thoughts:
        return BehavioralProfile(critique_summary="No thoughts captured in this period.")

    # Simple stats for the prompt
    type_counts = Counter(th.type for th in all_thoughts if th.type)
    energy_counts = Counter(th.energy_hint for th in all_thoughts if th.energy_hint)

    thought_summaries = "\n".join(
        f"- [{th.type or '?'}] {th.summary or th.raw_text[:80]}"
        for th in all_thoughts[-50:]  # last 50 for token budget
    )
    stale_task_list = "\n".join(
        f"- [{t.priority}] {t.content}"
        for t in old_pending[:20]
    )

    prompt = f"""\
You are SID's critique engine. Analyze Sudheer's behavioral patterns over the last {days} days.

THOUGHT TYPE DISTRIBUTION: {dict(type_counts)}
ENERGY DISTRIBUTION: {dict(energy_counts)}
TOTAL THOUGHTS: {len(all_thoughts)}

RECENT THOUGHTS (sample):
{thought_summaries}

STALE PENDING TASKS (open {days}+ days):
{stale_task_list or '  (none)'}

Return a JSON behavioral profile. Be analytically harsh — this is a diagnostic tool.

Fields:
- avoidance_patterns: list of topic/domain Sudheer consistently captures but never acts on
- recurring_unresolved: specific ideas/tasks mentioned 3+ times without resolution
- execution_gap_score: float 0-1 (0 = all ideation, 1 = all execution)
- dominant_thought_types: top 3 thought types
- energy_pattern: one sentence describing energy arc (e.g., "High morning energy, afternoon crash")
- top_themes: top 5 recurring themes (1-3 words each)
- negligence_flags: specific items that have been sitting longest without action
- critique_summary: 2 honest sentences summarizing behavioral pattern
"""

    try:
        profile = await gateway.generate("critique", prompt, BehavioralProfile)
        logger.info("Behavioral profile built: gap_score=%.2f, %d avoidance patterns",
                    profile.execution_gap_score, len(profile.avoidance_patterns))
        return profile
    except Exception as e:
        logger.error("Critique engine failed: %s", e)
        return BehavioralProfile(
            critique_summary=f"Critique unavailable: {e}",
            dominant_thought_types=[k for k, _ in type_counts.most_common(3)],
        )


async def get_negligence_report() -> str:
    """Human-readable negligence report for the API."""
    profile = await build_behavioral_profile(days=14)

    lines = [
        "BEHAVIORAL PROFILE (last 14 days)",
        "=" * 40,
        f"\nExecution gap: {profile.execution_gap_score:.0%} action vs ideation",
        f"\nSummary: {profile.critique_summary}",
    ]

    if profile.avoidance_patterns:
        lines.append("\nAVOIDANCE PATTERNS:")
        lines.extend(f"  • {p}" for p in profile.avoidance_patterns)

    if profile.recurring_unresolved:
        lines.append("\nRECURRING UNRESOLVED:")
        lines.extend(f"  • {r}" for r in profile.recurring_unresolved)

    if profile.negligence_flags:
        lines.append("\nNEGLECTED ITEMS:")
        lines.extend(f"  • {f}" for f in profile.negligence_flags)

    if profile.top_themes:
        lines.append(f"\nTop themes: {', '.join(profile.top_themes)}")

    return "\n".join(lines)
