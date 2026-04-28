"""SID FastAPI application — entrypoint wired up by `python main.py`."""
from __future__ import annotations

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_data_dir()

    # Initialise memory (creates tables if needed)
    try:
        store = get_store()
        init_fn = getattr(store, "init_memory", None)
        if init_fn is not None:
            res = init_fn()
            if hasattr(res, "__await__"):
                await res
        else:
            logger.warning("MemoryStore has no init_memory(); skipping init.")
    except Exception as e:
        logger.error("Memory init failed: %s", e)

    # Best-effort LLM health check — don't crash if Ollama isn't running.
    try:
        gw = get_gateway()
        hc = getattr(gw, "health_check", None)
        if hc is not None:
            res = hc()
            if hasattr(res, "__await__"):
                await res
    except Exception as e:
        logger.warning("LLM gateway health check failed (Ollama may be down): %s", e)

    # Optional processing worker startup.
    worker_task = None
    try:
        from services.processing import queue as _q  # type: ignore
        start_fn = (
            getattr(_q, "start_worker", None)
            or getattr(_q, "start", None)
        )
        if callable(start_fn):
            res = start_fn()
            if hasattr(res, "__await__"):
                worker_task = await res
            else:
                worker_task = res
            logger.info("Processing worker started.")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Processing worker not started: %s", e)

    yield

    # Shutdown — best effort
    try:
        from services.processing import queue as _q  # type: ignore
        stop_fn = getattr(_q, "stop_worker", None) or getattr(_q, "stop", None)
        if callable(stop_fn):
            res = stop_fn()
            if hasattr(res, "__await__"):
                await res
    except Exception:
        pass


app = FastAPI(title="SID API", version="1.0.0", lifespan=lifespan)

# CORS — localhost only.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
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
