"""Context loader — semantic search for related past thoughts to inform Stage 2."""
import logging
from services.memory import get_store

logger = logging.getLogger("sid.processing.context_loader")

_MIN_SCORE = 0.4
_CONTEXT_LIMIT = 5


async def load_context(state: dict) -> dict:
    chunk = state["chunk"]
    stage1 = state.get("stage1")

    # Prefer cleaned text for a better embedding signal
    query = (stage1.clean_text if stage1 else None) or chunk.raw_text

    try:
        results = await get_store().search(query, limit=_CONTEXT_LIMIT)
        # Filter low-relevance results and skip the thought itself (shouldn't exist yet, but safe)
        context_texts = [
            r.text for r in results
            if r.score >= _MIN_SCORE and r.thought_id != chunk.chunk_id
        ]
        logger.debug("Context loaded: %d relevant past thoughts", len(context_texts))
    except Exception as e:
        logger.warning("Context load failed, continuing without context: %s", e)
        context_texts = []

    return {"context_texts": context_texts}
