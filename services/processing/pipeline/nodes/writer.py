"""Writer — persist MemoryEntry to SQLite and LanceDB."""
import logging
from services.memory import get_store

logger = logging.getLogger("sid.processing.writer")


async def write(state: dict) -> dict:
    entry = state.get("entry")
    if entry is None:
        logger.warning("Writer called with no entry — skipping persistence.")
        return {}

    store = get_store()
    thought = entry.thought

    # Update the existing raw row with all processed fields
    await store.update_thought(thought.id, {
        "clean_text": thought.clean_text,
        "type": thought.type,
        "summary": thought.summary,
        "energy_hint": thought.energy_hint,
        "processing_stage": thought.processing_stage,
        "confidence": thought.confidence,
    })

    # Upsert semantic vector (uses clean_text for better embedding signal)
    text_for_embedding = thought.clean_text or thought.raw_text
    try:
        await store.upsert_vector(
            thought_id=thought.id,
            text=text_for_embedding,
            type=thought.type,
            date=thought.created_at[:10],
            session_id=thought.session_id,
        )
    except Exception as e:
        logger.error("Vector upsert failed for %s: %s", thought.id, e)

    # Save extracted tasks / sub_ideas / entities
    for extraction in entry.extractions:
        try:
            await store.save_extraction(extraction)
        except Exception as e:
            logger.warning("Failed to save extraction %s: %s", extraction.id, e)

    # Save relationships only to thoughts that actually exist
    for rel in entry.relationships:
        try:
            target = await store.get_thought(rel.target_id)
            if target:
                await store.save_relationship(rel)
            else:
                logger.debug(
                    "Skipping relationship to unknown thought %s", rel.target_id
                )
        except Exception as e:
            logger.warning("Failed to save relationship %s: %s", rel.id, e)

    logger.info(
        "Written thought %s: %d extractions, %d relationships",
        thought.id, len(entry.extractions), len(entry.relationships),
    )
    return {}
