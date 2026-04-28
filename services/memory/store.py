import asyncio
import datetime
from typing import List, Optional, Dict, Any

from shared.schemas.models import (
    RawChunk, Thought, Extraction, Relationship, SearchResult, LLMCallRecord, StatsResult
)
from services.memory.db import get_db_manager
from services.memory.vector_store import get_vector_store

class MemoryStore:
    def __init__(self):
        self.db_manager = get_db_manager()
        self.vector_store = get_vector_store()
        
    async def init_memory(self):
        await self.db_manager.init_db()
        # vector_store lazy loads on first method call

    async def save_raw_chunk(self, chunk: RawChunk) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO thoughts (
                    id, session_id, timestamp, raw_text, processing_stage, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id, chunk.session_id, chunk.timestamp, 
                    chunk.raw_text, "raw", chunk.timestamp, chunk.timestamp
                )
            )
            await db.commit()
        return chunk.chunk_id

    async def write_llm_call(self, call: LLMCallRecord) -> None:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO llm_calls (
                    id, timestamp, model, purpose, prompt_tokens, 
                    completion_tokens, latency_ms, estimated_cost_usd, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call.id, call.timestamp, call.model, call.purpose,
                    call.prompt_tokens, call.completion_tokens, call.latency_ms,
                    call.estimated_cost_usd, call.success
                )
            )
            await db.commit()

    async def update_thought(self, thought_id: str, updates: dict) -> None:
        if not updates:
            return
            
        columns = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())
        
        updates["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        columns = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())
        
        values.append(thought_id)
        
        async with self.db_manager.get_connection() as db:
            await db.execute(
                f"UPDATE thoughts SET {columns} WHERE id = ?",
                values
            )
            await db.commit()

    async def save_extraction(self, extraction: Extraction) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO extractions (
                    id, thought_id, type, content, priority, status, due_date, parent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction.id, extraction.thought_id, extraction.type,
                    extraction.content, extraction.priority, extraction.status,
                    extraction.due_date, extraction.parent_id
                )
            )
            await db.commit()
        return extraction.id

    async def upsert_vector(self, thought_id: str, text: str, meta: dict) -> None:
        # Offload embedded insertion to native lancedb method
        # This isn't async natively but lancedb operations are highly parallelized in rust (arrow)
        # We can run it in a threadpool if it blocks, but local add/delete is in ms
        row = {
            "thought_id": thought_id,
            "text": text,
            "vector": meta["vector"], # We expect the vector pre-computed
            "type": meta.get("type", "unknown"),
            "date": meta.get("date", ""),
            "session_id": meta.get("session_id", "")
        }
        await asyncio.to_thread(self.vector_store.upsert, [row])

    async def get_thought(self, thought_id: str) -> Optional[Thought]:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute("SELECT * FROM thoughts WHERE id = ?", (thought_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            return Thought(**dict(row))

    async def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        # Avoid circular import by requesting Gateway dynamically
        from services.llm_gateway import get_gateway
        gateway = get_gateway()
        
        query_vector = await asyncio.to_thread(gateway.embed, query)
        lance_results = await asyncio.to_thread(self.vector_store.search, query_vector, limit)
        
        results = []
        async with self.db_manager.get_connection() as db:
            for item in lance_results:
                thought_id = item["thought_id"]
                score = item.get("_distance", 1.0) # distance from query
                
                # Retrieve fully hydrated thought
                cursor = await db.execute("SELECT * FROM thoughts WHERE id = ?", (thought_id,))
                row = await cursor.fetchone()
                if row:
                    results.append(SearchResult(
                        thought_id=thought_id,
                        text=item["text"],
                        summary=row["summary"],
                        type=row["type"],
                        date=row["created_at"],
                        session_id=row["session_id"],
                        score=1.0 / (1.0 + score) # simple cosine similarity mapping
                    ))
        
        return results
