"""Watchdog-based folder watcher. Detects new/modified files and feeds them to the pipeline."""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from pathlib import Path
from typing import Optional, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

from services.document_agent.extractor import extract_text
from shared.schemas.models import RawChunk

logger = logging.getLogger("sid.document_agent.watcher")

_SUPPORTED = {".pdf", ".txt", ".md", ".markdown"}
_DOCS_SESSION_ID = "document-agent"  # all doc chunks share a logical session prefix


class _Handler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._seen: Set[str] = set()

    def _handle(self, path_str: str):
        path = Path(path_str)
        if path.suffix.lower() not in _SUPPORTED:
            return
        key = f"{path}:{path.stat().st_mtime if path.exists() else 0}"
        if key in self._seen:
            return
        self._seen.add(key)
        asyncio.run_coroutine_threadsafe(self._queue.put(path), self._loop)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)


class DocumentWatcher:
    def __init__(self, watch_dir: Optional[Path] = None):
        self._watch_dir = watch_dir or (Path.home() / "Documents" / "SID")
        self._watch_dir.mkdir(parents=True, exist_ok=True)
        self._observer: Optional[Observer] = None
        self._queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._queue = asyncio.Queue()
        self._observer = Observer()
        handler = _Handler(loop, self._queue)
        self._observer.schedule(handler, str(self._watch_dir), recursive=True)
        self._observer.start()
        self._worker_task = loop.create_task(self._process_loop())
        logger.info("Document watcher started on %s", self._watch_dir)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
        if self._worker_task:
            self._worker_task.cancel()

    async def ingest_file(self, path: Path) -> int:
        """Manually ingest a file. Returns number of chunks created."""
        return await self._process_file(path)

    async def _process_loop(self):
        while True:
            try:
                path: Path = await self._queue.get()
                await self._process_file(path)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Document processing error: %s", e)

    async def _process_file(self, path: Path) -> int:
        logger.info("Processing document: %s", path.name)
        chunks_text = await asyncio.to_thread(extract_text, path)

        if not chunks_text:
            logger.warning("No content extracted from %s", path.name)
            return 0

        from services.processing import enqueue
        from services.memory import get_store

        session_id = f"{_DOCS_SESSION_ID}-{path.stem[:20]}"
        count = 0

        for i, text in enumerate(chunks_text):
            chunk = RawChunk(
                chunk_id=str(uuid.uuid4()),
                session_id=session_id,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                raw_text=f"[Document: {path.name}, part {i+1}/{len(chunks_text)}]\n\n{text}",
                audio_duration_sec=0.0,
                silence_ratio=0.0,
            )

            try:
                await get_store().save_raw_chunk(chunk)
                await enqueue(chunk)
                count += 1
            except Exception as e:
                logger.error("Failed to enqueue chunk %d of %s: %s", i + 1, path.name, e)

        logger.info("Ingested %s: %d chunks queued", path.name, count)
        return count


_watcher: Optional[DocumentWatcher] = None


def get_doc_watcher(watch_dir: Optional[Path] = None) -> DocumentWatcher:
    global _watcher
    if _watcher is None:
        _watcher = DocumentWatcher(watch_dir=watch_dir)
    return _watcher
