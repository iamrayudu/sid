"""Milestone routine — break a parent task into 2–7 concrete sub-steps via LLM.

Used both from chat ("plan the X task") and the UI's "Plan" button on each
pending task. Steps are persisted as Extractions linked back to the parent
via milestone_parent_id (column added in the Phase 4 schema migration).

Re-running on the same parent does not duplicate steps — the prompt is
shown the existing milestones so the LLM extends the plan rather than
restarting.

Rule #1: every LLM call goes through the gateway. Routed via the
"milestone" purpose in config/models.yaml.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from shared.schemas.models import Extraction
from services.memory import get_store
from services.llm_gateway import get_gateway

logger = logging.getLogger("sid.agent.milestone")


# ── Local schemas (not in shared/schemas/models.py — only used here) ──────────

class MilestoneStep(BaseModel):
    content: str = Field(description="One concrete action sentence")
    priority: int = Field(ge=1, le=5, default=3)
    time_estimate_hours: Optional[float] = Field(
        default=None,
        description="Rough hours estimate, optional"
    )
    next_step: Optional[str] = Field(
        default=None,
        description="The very first action that starts this step"
    )


class MilestoneBreakdown(BaseModel):
    steps: List[MilestoneStep] = Field(min_length=2, max_length=7)
    rationale: str = Field(description="One paragraph: how these steps cover the task")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _format_existing(existing: List[Extraction]) -> str:
    if not existing:
        return "(none yet — this is the first breakdown)"
    return "\n".join(
        f"  {i+1}. [P{m.priority}] {m.content}"
        + (f" (next: {m.next_step})" if m.next_step else "")
        for i, m in enumerate(existing)
    )


def _build_prompt(
    parent: Extraction,
    existing_milestones: List[Extraction],
    user_context: str,
) -> str:
    return f"""\
You are SID's task-planning routine. Break Sudheer's parent task into 2-7 concrete milestones.

PARENT TASK:
  Content: {parent.content}
  Priority: {parent.priority} (1=highest, 5=lowest)
  Due date: {parent.due_date or "not set"}

EXISTING MILESTONES (do NOT duplicate; extend or refine if helpful):
{_format_existing(existing_milestones)}

USER CONTEXT (constraints, energy, available time):
  {user_context.strip() or "(none provided)"}

Rules:
- Output 2 to 7 steps. Fewer is better — concise is honest.
- Each step is one concrete action sentence (verb-first).
- Priority of each step inherits parent priority unless one is clearly more urgent.
- time_estimate_hours: rough hour estimate. Omit if you don't know.
- next_step: the literal first action to start this milestone (e.g. "Open the
  research doc and skim the methodology section").
- rationale: one paragraph (3-4 sentences) explaining how these steps cover the
  parent task end-to-end.

Return ONLY valid JSON matching the MilestoneBreakdown schema.
"""


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_breakdown(
    parent_task: Extraction,
    user_context: str = "",
) -> MilestoneBreakdown:
    """
    Ask the milestone-purpose LLM to break a parent task into 2-7 concrete steps.

    Caller is responsible for persisting the steps. Use `plan_and_persist()`
    if you want one-call save behavior.
    """
    store = get_store()
    gateway = get_gateway()

    existing = await store.get_milestones_for(parent_task.id)
    prompt = _build_prompt(parent_task, existing, user_context)

    breakdown = await gateway.generate("milestone", prompt, MilestoneBreakdown)
    logger.info(
        "Milestone breakdown for %s: %d steps (%d existing)",
        parent_task.id[:8], len(breakdown.steps), len(existing),
    )
    return breakdown


async def plan_and_persist(
    parent_task: Extraction,
    user_context: str = "",
) -> List[Extraction]:
    """
    Generate a breakdown and persist each step as a new Extraction with
    milestone_parent_id = parent_task.id.

    Returns the list of newly-saved Extractions in the order the LLM produced.
    Existing milestones on the parent are left intact (the prompt sees them
    so the LLM extends rather than duplicates).
    """
    breakdown = await generate_breakdown(parent_task, user_context)
    store = get_store()
    saved: List[Extraction] = []

    for step in breakdown.steps:
        ext = Extraction(
            id=str(uuid.uuid4()),
            thought_id=parent_task.thought_id,
            type="task",
            content=step.content,
            priority=step.priority,
            status="pending",
            milestone_parent_id=parent_task.id,
            time_estimate_hours=step.time_estimate_hours,
            next_step=step.next_step,
        )
        await store.save_extraction(ext)
        saved.append(ext)

    logger.info(
        "Persisted %d milestones under parent %s",
        len(saved), parent_task.id[:8],
    )
    return saved
