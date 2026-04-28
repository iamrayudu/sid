"""Assembler — merge Stage 1 + Stage 2 outputs into a MemoryEntry (pure Python, no I/O)."""
import uuid
import datetime
from shared.schemas.models import MemoryEntry, Thought, Extraction, Relationship


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


async def assemble(state: dict) -> dict:
    chunk = state["chunk"]
    stage1 = state.get("stage1")
    stage2 = state.get("stage2")

    thought = Thought(
        id=chunk.chunk_id,
        session_id=chunk.session_id,
        timestamp=chunk.timestamp,
        raw_text=chunk.raw_text,
        clean_text=stage1.clean_text if stage1 else None,
        type=stage1.thought_type if stage1 else None,
        summary=stage1.summary if stage1 else None,
        energy_hint=stage1.energy_hint if stage1 else None,
        processing_stage="processed",
        confidence=stage1.confidence if stage1 else None,
        created_at=chunk.timestamp,
        updated_at=_now(),
    )

    extractions: list[Extraction] = []
    if stage2:
        for task in stage2.tasks:
            extractions.append(Extraction(
                id=str(uuid.uuid4()),
                thought_id=chunk.chunk_id,
                type="task",
                content=task.content,
                priority=task.priority,
                status="pending",
                due_date=task.due_hint,
            ))
        for sub_idea in stage2.sub_ideas:
            extractions.append(Extraction(
                id=str(uuid.uuid4()),
                thought_id=chunk.chunk_id,
                type="sub_idea",
                content=sub_idea,
                priority=3,
                status="pending",
            ))
        for entity in stage2.entities:
            extractions.append(Extraction(
                id=str(uuid.uuid4()),
                thought_id=chunk.chunk_id,
                type="entity",
                content=f"{entity.name} ({entity.entity_type})",
                priority=3,
                status="pending",
            ))

    relationships: list[Relationship] = []
    if stage2:
        for rel in stage2.relationships:
            relationships.append(Relationship(
                id=str(uuid.uuid4()),
                source_id=chunk.chunk_id,
                target_id=rel.related_thought_id,
                type=rel.relationship_type,
                strength=rel.strength,
                reason=rel.reason,
                created_at=_now(),
            ))

    return {
        "entry": MemoryEntry(
            thought=thought,
            extractions=extractions,
            relationships=relationships,
        )
    }
