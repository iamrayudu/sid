import asyncio
import datetime
import logging
import os
from typing import List, Optional, Dict, Any

from shared.schemas.models import (
    RawChunk, Thought, Extraction, Relationship, SearchResult, LLMCallRecord, StatsResult,
    TaskClosure, WeeklyRecord
)
from services.memory.db import get_db_manager
from services.memory.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class MemoryStore:
    def __init__(self):
        self.db_manager = get_db_manager()
        self.vector_store = get_vector_store()

    async def init_memory(self):
        await self.db_manager.init_db()

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

        updates["updated_at"] = _utcnow_iso()
        columns = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())
        values.append(thought_id)

        async with self.db_manager.get_connection() as db:
            await db.execute(
                f"UPDATE thoughts SET {columns} WHERE id = ?",
                values
            )
            await db.commit()

    async def update_extraction(self, extraction_id: str, updates: dict) -> None:
        if not updates:
            return

        if updates.get("status") == "done" and "completed_at" not in updates:
            updates["completed_at"] = _utcnow_iso()

        columns = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values())
        values.append(extraction_id)

        async with self.db_manager.get_connection() as db:
            await db.execute(
                f"UPDATE extractions SET {columns} WHERE id = ?",
                values
            )
            await db.commit()

    async def save_extraction(self, extraction: Extraction) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO extractions (
                    id, thought_id, type, content, priority, status, due_date, parent_id,
                    milestone_parent_id, percentage_complete, time_estimate_hours, next_step, closure_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction.id, extraction.thought_id, extraction.type,
                    extraction.content, extraction.priority, extraction.status,
                    extraction.due_date, extraction.parent_id,
                    extraction.milestone_parent_id, extraction.percentage_complete,
                    extraction.time_estimate_hours, extraction.next_step, extraction.closure_note
                )
            )
            await db.commit()
        return extraction.id

    async def save_task_closure(self, closure: TaskClosure) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO task_closures (
                    id, extraction_id, learning, what_went_wrong, would_do_differently,
                    negligence_flagged, energy_reflection, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    closure.id, closure.extraction_id, closure.learning, closure.what_went_wrong,
                    closure.would_do_differently, closure.negligence_flagged,
                    closure.energy_reflection, closure.created_at
                )
            )
            await db.commit()
        return closure.id

    async def save_weekly_record(self, record: WeeklyRecord) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO weekly_records (
                    week_start, week_end, reflection, planned_tasks, completed_tasks,
                    completion_rate, patterns, key_learning, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.week_start, record.week_end, record.reflection, record.planned_tasks,
                    record.completed_tasks, record.completion_rate, record.patterns,
                    record.key_learning, record.created_at
                )
            )
            await db.commit()
        return record.week_start

    async def save_relationship(self, rel: Relationship) -> str:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT INTO relationships (
                    id, source_id, target_id, type, strength, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel.id, rel.source_id, rel.target_id, rel.type,
                    rel.strength, rel.reason, rel.created_at
                )
            )
            await db.commit()
        return rel.id

    async def upsert_vector(
        self,
        thought_id: str,
        text: str,
        type: Optional[str] = None,
        date: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        from services.llm_gateway import get_gateway
        gateway = get_gateway()

        vector = await asyncio.to_thread(gateway.embed, text)

        row = {
            "thought_id": thought_id,
            "text": text,
            "vector": vector,
            "type": type or "unknown",
            "date": date or "",
            "session_id": session_id or "",
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
        from services.llm_gateway import get_gateway
        gateway = get_gateway()

        query_vector = await asyncio.to_thread(gateway.embed, query)
        lance_results = await asyncio.to_thread(self.vector_store.search, query_vector, limit)

        results = []
        async with self.db_manager.get_connection() as db:
            for item in lance_results:
                thought_id = item["thought_id"]
                distance = item.get("_distance", 1.0)
                similarity = max(0.0, 1.0 - float(distance))

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
                        score=similarity,
                    ))

        return results

    async def get_timeline(self, date: str) -> List[Thought]:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute(
                """
                SELECT * FROM thoughts
                WHERE DATE(created_at) = ?
                ORDER BY created_at ASC
                """,
                (date,),
            )
            rows = await cursor.fetchall()
            return [Thought(**dict(r)) for r in rows]

    async def get_pending_tasks(self) -> List[Extraction]:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute(
                """
                SELECT * FROM extractions
                WHERE status = 'pending'
                ORDER BY priority ASC, id ASC
                """
            )
            rows = await cursor.fetchall()
            return [Extraction(**dict(r)) for r in rows]

    async def get_unchecked_count(self, since_iso: str) -> int:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) AS c FROM thoughts WHERE created_at > ?",
                (since_iso,),
            )
            row = await cursor.fetchone()
            return int(row["c"]) if row else 0

    async def get_stats(self) -> StatsResult:
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()

        async with self.db_manager.get_connection() as db:
            cur = await db.execute("SELECT COUNT(*) AS c FROM thoughts")
            row = await cur.fetchone()
            total_thoughts = int(row["c"]) if row else 0

            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM thoughts WHERE DATE(created_at) = ?",
                (today,),
            )
            row = await cur.fetchone()
            thoughts_today = int(row["c"]) if row else 0

            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM extractions WHERE status = 'pending'"
            )
            row = await cur.fetchone()
            pending_tasks = int(row["c"]) if row else 0

            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM llm_calls WHERE DATE(timestamp) = ?",
                (today,),
            )
            row = await cur.fetchone()
            llm_calls_today = int(row["c"]) if row else 0

            cur = await db.execute(
                """
                SELECT model,
                       COALESCE(SUM(prompt_tokens), 0) AS p,
                       COALESCE(SUM(completion_tokens), 0) AS c
                FROM llm_calls
                WHERE DATE(timestamp) = ?
                GROUP BY model
                """,
                (today,),
            )
            model_rows = await cur.fetchall()

            settings = self._get_settings()
            tokens_today_fast = 0
            tokens_today_deep = 0
            for r in model_rows:
                tokens = int(r["p"]) + int(r["c"])
                if r["model"] == settings.fast_model:
                    tokens_today_fast += tokens
                elif r["model"] == settings.deep_model:
                    tokens_today_deep += tokens

            cur = await db.execute(
                "SELECT AVG(latency_ms) AS a FROM llm_calls WHERE purpose = 'stage1'"
            )
            row = await cur.fetchone()
            avg_latency_stage1_ms = float(row["a"]) if row and row["a"] is not None else 0.0

            cur = await db.execute(
                "SELECT AVG(latency_ms) AS a FROM llm_calls WHERE purpose = 'stage2'"
            )
            row = await cur.fetchone()
            avg_latency_stage2_ms = float(row["a"]) if row and row["a"] is not None else 0.0

        try:
            db_size_bytes = os.path.getsize(self.db_manager.db_path)
            db_size_mb = db_size_bytes / (1024 * 1024)
        except OSError:
            db_size_mb = 0.0

        from services.processing import queue as _q  # type: ignore
        try:
            queue_depth = _q.queue_depth()
        except Exception:
            queue_depth = 0

        return StatsResult(
            total_thoughts=total_thoughts,
            thoughts_today=thoughts_today,
            pending_tasks=pending_tasks,
            llm_calls_today=llm_calls_today,
            tokens_today_fast=tokens_today_fast,
            tokens_today_deep=tokens_today_deep,
            avg_latency_stage1_ms=avg_latency_stage1_ms,
            avg_latency_stage2_ms=avg_latency_stage2_ms,
            processing_queue_depth=queue_depth,
            db_size_mb=db_size_mb,
        )

    async def save_daily_reflection(self, date: str, reflection: str) -> None:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute(
                "SELECT date FROM daily_records WHERE date = ?", (date,)
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    "UPDATE daily_records SET evening_reflection = ? WHERE date = ?",
                    (reflection, date),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO daily_records (date, evening_reflection)
                    VALUES (?, ?)
                    """,
                    (date, reflection),
                )
            await db.commit()

    async def create_session(self, session_id: str, start_time: str, date: str, mode: str = "capture") -> None:
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO sessions (id, date, start_time, mode)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, date, start_time, mode),
            )
            await db.commit()

    async def touch_session(self, session_id: str) -> None:
        """Increment thought_count and set end_time to now."""
        now = _utcnow_iso()
        async with self.db_manager.get_connection() as db:
            await db.execute(
                """
                UPDATE sessions
                SET thought_count = thought_count + 1, end_time = ?
                WHERE id = ?
                """,
                (now, session_id),
            )
            await db.commit()

    async def get_unprocessed_thoughts(self, limit: int = 10) -> List[Thought]:
        async with self.db_manager.get_connection() as db:
            cursor = await db.execute(
                """
                SELECT * FROM thoughts
                WHERE processing_stage = 'raw'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [Thought(**dict(r)) for r in rows]

    def _get_settings(self):
        from config.settings import get_settings
        return get_settings()
