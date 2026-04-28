"""Async processing queue — receives RawChunk, feeds the 2-stage pipeline."""
import asyncio
import logging
from typing import Optional

from shared.schemas.models import RawChunk

logger = logging.getLogger("sid.processing.queue")

_queue: Optional[asyncio.Queue] = None
_worker_task: Optional[asyncio.Task] = None
_running: bool = False


def _get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def _process(chunk: RawChunk) -> None:
    from services.processing.pipeline.graph import run_pipeline
    try:
        await run_pipeline(chunk)
    except Exception as e:
        logger.error("Pipeline failed for chunk %s: %s", chunk.chunk_id, e)


async def _worker() -> None:
    logger.info("Processing worker started.")
    q = _get_queue()
    while _running:
        try:
            chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            await _process(chunk)
            q.task_done()
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error("Worker loop error: %s", e)
    logger.info("Processing worker stopped.")


async def enqueue(chunk: RawChunk) -> None:
    await _get_queue().put(chunk)
    logger.debug("Enqueued chunk %s (queue depth: %d)", chunk.chunk_id, queue_depth())


def queue_depth() -> int:
    q = _get_queue()
    return q.qsize()


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
