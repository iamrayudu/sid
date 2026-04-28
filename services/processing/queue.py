"""Persistent processing queue — SQLite-backed, priority-ordered, crash-resilient.

Survives Ollama crashes and process restarts. Voice chunks (priority 1) jump ahead
of document chunks (priority 5). Failed chunks retry with exponential backoff.

States in `processing_queue.status`:
    pending     ready to process (or scheduled retry)
    processing  currently held by worker (orphan-recovered on startup)
    done        successfully processed (kept briefly for observability)
    failed      exceeded MAX_RETRIES
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Optional, Dict, Any

from shared.schemas.models import RawChunk

logger = logging.getLogger("sid.processing.queue")

# Priority constants — lower = higher priority
PRIORITY_VOICE = 1     # user just spoke; surface fast
PRIORITY_DOCUMENT = 5  # background ingestion

MAX_RETRIES = 3
BACKOFF_SECS = [10, 60, 300]  # 10s, 1min, 5min
POLL_INTERVAL_SECS = 2.0
DONE_RETENTION_SECS = 3600  # keep done rows for an hour for observability

_running: bool = False
_worker_task: Optional[asyncio.Task] = None


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# ── Public API ───────────────────────────────────────────────────────────────

async def enqueue(chunk: RawChunk, priority: int = PRIORITY_VOICE) -> None:
    """Persist a chunk to the queue. Idempotent on chunk_id."""
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO processing_queue
              (id, chunk_json, priority, status, enqueued_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (chunk.chunk_id, chunk.model_dump_json(), priority, _utcnow_iso()),
        )
        await db.commit()
    logger.debug("Enqueued chunk %s priority=%d", chunk.chunk_id, priority)


async def queue_depth() -> int:
    """Count of pending items not yet held back by retry_after."""
    from services.memory.db import get_db_manager
    now = _utcnow_iso()
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) AS c FROM processing_queue
            WHERE status = 'pending'
              AND (retry_after IS NULL OR retry_after <= ?)
            """,
            (now,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0


async def list_failed(limit: int = 50) -> list:
    """Return rows that exceeded MAX_RETRIES (status='failed')."""
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            """
            SELECT id, priority, retries, last_error, enqueued_at, processed_at
            FROM processing_queue
            WHERE status = 'failed'
            ORDER BY processed_at DESC NULLS LAST, enqueued_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def retry_chunk(chunk_id: str) -> bool:
    """Reset a failed chunk back to pending for the worker to pick up.
    Returns True if a row was updated, False if no matching failed row."""
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            """
            UPDATE processing_queue
            SET status = 'pending', retries = 0, retry_after = NULL, last_error = NULL
            WHERE id = ? AND status = 'failed'
            """,
            (chunk_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_chunk(chunk_id: str) -> bool:
    """Permanently remove a queue row (typically a failed one the user gave up on)."""
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            "DELETE FROM processing_queue WHERE id = ? AND status IN ('failed', 'done')",
            (chunk_id,),
        )
        await db.commit()
        return cur.rowcount > 0


# ── Internal worker ──────────────────────────────────────────────────────────

async def _recover_orphans() -> None:
    """On worker startup, reset any 'processing' rows back to pending.
    They were claimed by a previous worker that crashed before completing."""
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            "UPDATE processing_queue SET status = 'pending' WHERE status = 'processing'"
        )
        await db.commit()
        if cur.rowcount:
            logger.warning("Recovered %d orphan chunk(s) from previous run", cur.rowcount)


async def _purge_old_done() -> None:
    """Remove old 'done' rows so the table doesn't grow forever."""
    from services.memory.db import get_db_manager
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=DONE_RETENTION_SECS)
    ).isoformat().replace("+00:00", "Z")
    async with get_db_manager().get_connection() as db:
        await db.execute(
            "DELETE FROM processing_queue WHERE status = 'done' AND processed_at < ?",
            (cutoff,),
        )
        await db.commit()


async def _claim_next() -> Optional[Dict[str, Any]]:
    """Atomically claim the next eligible chunk: status='pending' AND retry_after <= now,
    ordered by priority then enqueue time."""
    from services.memory.db import get_db_manager
    now = _utcnow_iso()
    async with get_db_manager().get_connection() as db:
        cur = await db.execute(
            """
            SELECT * FROM processing_queue
            WHERE status = 'pending'
              AND (retry_after IS NULL OR retry_after <= ?)
            ORDER BY priority ASC, enqueued_at ASC
            LIMIT 1
            """,
            (now,),
        )
        row = await cur.fetchone()
        if not row:
            return None

        # Claim it
        cur = await db.execute(
            "UPDATE processing_queue SET status = 'processing' WHERE id = ? AND status = 'pending'",
            (row["id"],),
        )
        await db.commit()
        if cur.rowcount == 0:
            return None  # someone else claimed it
        return dict(row)


async def _mark_done(chunk_id: str) -> None:
    from services.memory.db import get_db_manager
    async with get_db_manager().get_connection() as db:
        await db.execute(
            "UPDATE processing_queue SET status = 'done', processed_at = ? WHERE id = ?",
            (_utcnow_iso(), chunk_id),
        )
        await db.commit()


async def _mark_failed_or_retry(chunk_id: str, retries: int, error: str) -> None:
    """Increment retry count. Schedule retry if under cap; else mark failed."""
    from services.memory.db import get_db_manager
    new_retries = retries + 1
    if new_retries > MAX_RETRIES:
        async with get_db_manager().get_connection() as db:
            await db.execute(
                """
                UPDATE processing_queue
                SET status = 'failed', retries = ?, last_error = ?, processed_at = ?
                WHERE id = ?
                """,
                (new_retries, error[:500], _utcnow_iso(), chunk_id),
            )
            await db.commit()
        logger.error("Chunk %s permanently failed after %d retries: %s", chunk_id, new_retries, error[:200])
        return

    backoff = BACKOFF_SECS[min(new_retries - 1, len(BACKOFF_SECS) - 1)]
    retry_after = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=backoff)
    ).isoformat().replace("+00:00", "Z")

    async with get_db_manager().get_connection() as db:
        await db.execute(
            """
            UPDATE processing_queue
            SET status = 'pending', retries = ?, last_error = ?, retry_after = ?
            WHERE id = ?
            """,
            (new_retries, error[:500], retry_after, chunk_id),
        )
        await db.commit()
    logger.warning("Chunk %s retry %d/%d in %ds: %s", chunk_id, new_retries, MAX_RETRIES, backoff, error[:200])


async def _process_row(row: Dict[str, Any]) -> None:
    """Run the pipeline on a claimed row; update status accordingly."""
    chunk_id = row["id"]
    try:
        chunk = RawChunk.model_validate_json(row["chunk_json"])
    except Exception as e:
        logger.error("Bad chunk_json for %s: %s", chunk_id, e)
        await _mark_failed_or_retry(chunk_id, MAX_RETRIES, f"bad chunk: {e}")  # don't retry malformed rows
        return

    try:
        from services.processing.pipeline.graph import run_pipeline
        await run_pipeline(chunk)
        await _mark_done(chunk_id)
        logger.debug("Processed chunk %s", chunk_id)
    except Exception as e:
        await _mark_failed_or_retry(chunk_id, int(row.get("retries", 0)), str(e))


async def _worker() -> None:
    logger.info("Processing worker started.")
    try:
        await _recover_orphans()
    except Exception as e:
        logger.warning("Orphan recovery failed: %s", e)

    last_purge = datetime.datetime.now()

    while _running:
        try:
            row = await _claim_next()
            if row:
                await _process_row(row)
                continue

            # Periodic cleanup of old done rows
            if (datetime.datetime.now() - last_purge).total_seconds() > 600:
                try:
                    await _purge_old_done()
                except Exception as e:
                    logger.debug("Purge failed: %s", e)
                last_purge = datetime.datetime.now()

            await asyncio.sleep(POLL_INTERVAL_SECS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Worker loop error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECS)

    logger.info("Processing worker stopped.")


# ── Lifecycle ────────────────────────────────────────────────────────────────

async def start_worker() -> None:
    global _worker_task, _running
    _running = True
    _worker_task = asyncio.create_task(_worker())
    logger.info("Processing worker task created.")


async def stop_worker() -> None:
    global _running, _worker_task
    _running = False
    if _worker_task and not _worker_task.done():
        try:
            await asyncio.wait_for(_worker_task, timeout=5.0)
        except asyncio.TimeoutError:
            _worker_task.cancel()
    _worker_task = None
