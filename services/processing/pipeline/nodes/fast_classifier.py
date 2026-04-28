"""Stage 1 — classify and clean the raw transcript using the fast model."""
import logging
from shared.schemas.models import Stage1Output
from services.llm_gateway import get_gateway

logger = logging.getLogger("sid.processing.fast_classifier")

_PROMPT = """\
You are a cognitive assistant classifying spoken thoughts captured by voice.

Classify this spoken text and clean it up:

TEXT: {text}

Rules:
- thought_type: one of idea / task / reflection / question / random
- summary: 10-20 words, what this is about
- clean_text: remove filler words (um, uh, like, you know), fix grammar; keep meaning exact
- energy_hint: infer from tone/content: excited / tired / focused / distracted / neutral
- confidence: 0.0-1.0, how certain you are about the classification

Respond with JSON matching the schema exactly."""


async def fast_classify(state: dict) -> dict:
    chunk = state["chunk"]
    prompt = _PROMPT.format(text=chunk.raw_text)

    try:
        result: Stage1Output = await get_gateway().fast(prompt, Stage1Output)
        logger.debug("Stage 1 done: type=%s confidence=%.2f", result.thought_type, result.confidence)
        return {"stage1": result}
    except Exception as e:
        logger.error("Stage 1 failed for chunk %s: %s", chunk.chunk_id, e)
        return {
            "stage1": Stage1Output(
                thought_type="random",
                summary=chunk.raw_text[:80],
                clean_text=chunk.raw_text,
                energy_hint="neutral",
                confidence=0.0,
            )
        }
