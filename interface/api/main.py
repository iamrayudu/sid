"""SID FastAPI application — entrypoint wired up by `python main.py`."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config.settings import get_settings
from services.memory import get_store
from services.llm_gateway import get_gateway

from interface.api.routes import voice, thoughts, agent, stats

logger = logging.getLogger("sid.api")

TEMPLATES_DIR = Path(__file__).parent / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"


async def _notify(text: str, event_type: str) -> None:
    """Deliver a scheduled event to the user via TTS."""
    logger.info("Agent event [%s]: %s", event_type, text[:80])
    try:
        from services.tts import get_tts
        await get_tts().speak(text)
    except Exception as e:
        logger.warning("TTS notify failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_data_dir()

    # ── Memory init ───────────────────────────────────────────────────────────
    try:
        await get_store().init_memory()
        logger.info("Memory initialised at %s", settings.db_path)
    except Exception as e:
        logger.error("Memory init failed: %s", e)

    # ── LLM health check (best-effort) ────────────────────────────────────────
    gateway = get_gateway()
    try:
        await gateway.health_check()
    except Exception as e:
        logger.warning("LLM health check failed (Ollama may be down): %s", e)

    # ── Ollama health monitor (background polling) ────────────────────────────
    try:
        gateway.start_health_monitor()
        logger.info("Ollama health monitor started.")
    except Exception as e:
        logger.warning("Ollama health monitor not started: %s", e)

    # ── Processing queue worker ───────────────────────────────────────────────
    try:
        from services.processing.queue import start_worker
        await start_worker()
        logger.info("Processing worker started.")
    except Exception as e:
        logger.warning("Processing worker not started: %s", e)

    # ── Scheduler (morning, evening, check-in, weekly) ────────────────────────
    scheduler = None
    try:
        from services.agent.scheduler import init_scheduler
        scheduler = init_scheduler(notify=_notify)
        scheduler.start()
        logger.info("Agent scheduler started.")
    except Exception as e:
        logger.warning("Agent scheduler not started: %s", e)

    # ── Document watcher ──────────────────────────────────────────────────────
    doc_watcher = None
    try:
        from services.document_agent import get_doc_watcher
        doc_watcher = get_doc_watcher()
        doc_watcher.start(asyncio.get_event_loop())
        logger.info("Document watcher started.")
    except Exception as e:
        logger.warning("Document watcher not started: %s", e)

    yield

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    if doc_watcher:
        try:
            doc_watcher.stop()
        except Exception:
            pass

    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    try:
        from services.processing.queue import stop_worker
        await stop_worker()
    except Exception:
        pass

    try:
        await gateway.stop_health_monitor()
    except Exception:
        pass


app = FastAPI(title="SID API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice.router, prefix="/api/voice", tags=["voice"])
app.include_router(thoughts.router, prefix="/api/thoughts", tags=["thoughts"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])


@app.get("/", include_in_schema=False)
async def root():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return JSONResponse({"error": "index.html not found"}, status_code=404)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
