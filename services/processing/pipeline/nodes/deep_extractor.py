"""Stage 2 — deep extraction of tasks, entities, relationships, and intent."""
import logging
from shared.schemas.models import Stage2Output
from services.llm_gateway import get_gateway

logger = logging.getLogger("sid.processing.deep_extractor")

_PROMPT = """\
You are a cognitive assistant helping to deeply analyze a spoken thought.

Original text: {raw_text}
Cleaned text: {clean_text}
Type: {thought_type}
Summary: {summary}

Related past thoughts (ID: text) — use these IDs when extracting relationships:
{context}

Extract the following:
- tasks: concrete actionable items with priority (1=urgent, 5=low) and when they're due
- entities: named people, projects, places, concepts, tools, companies mentioned
- sub_ideas: distinct ideas nested within this thought (if any)
- intent: why did the user say this? what problem are they solving?
- relationships: links to past thoughts — set related_thought_id to the ID shown above
- emotional_tone: overall emotional quality of this thought

Respond with JSON matching the schema exactly."""


async def deep_extract(state: dict) -> dict:
    chunk = state["chunk"]
    stage1 = state.get("stage1")
    context_items = state.get("context_items", [])

    if not stage1:
        return {"stage2": Stage2Output()}

    if context_items:
        context_str = "\n".join(
            f"[{item['thought_id']}]: {item['text']}" for item in context_items
        )
    else:
        context_str = "No related past thoughts found."

    prompt = _PROMPT.format(
        raw_text=chunk.raw_text,
        clean_text=stage1.clean_text,
        thought_type=stage1.thought_type,
        summary=stage1.summary,
        context=context_str,
    )

    try:
        result: Stage2Output = await get_gateway().deep(prompt, Stage2Output)
        logger.debug(
            "Stage 2 done: %d tasks, %d entities, %d relationships",
            len(result.tasks), len(result.entities), len(result.relationships),
        )
        return {"stage2": result}
    except Exception as e:
        logger.error("Stage 2 failed for chunk %s: %s", chunk.chunk_id, e)
        return {"stage2": Stage2Output()}
