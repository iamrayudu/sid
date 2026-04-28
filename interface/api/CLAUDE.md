# Interface: FastAPI REST API

## Purpose

HTTP backend on `localhost:8765`. The single interface between all clients (menubar app, browser UI, future mobile app) and SID's services.

## Files to Build

```
interface/api/
├── main.py              # FastAPI app setup + lifespan (starts services)
└── routes/
    ├── voice.py         # /api/voice/* — recording control
    ├── thoughts.py      # /api/thoughts/* — timeline + search
    ├── agent.py         # /api/agent/* — chat + status + manual triggers
    └── stats.py         # /api/stats — LLM usage dashboard
```

## Endpoints (Full Spec)

### Voice Routes (`/api/voice/`)

```
POST /api/voice/start
  Body: { session_id?: string }
  Response: { session_id: string, started_at: string }
  Action: Creates session, starts recording

POST /api/voice/stop
  Body: { session_id: string }
  Response: { chunk_id: string, raw_text: string, duration_sec: float }
  Action: Stops recording, transcribes, adds to processing queue

GET /api/voice/status
  Response: { recording: bool, session_id?: string, queue_depth: int }
```

### Thought Routes (`/api/thoughts/`)

```
GET /api/thoughts/timeline?date=YYYY-MM-DD
  Response: { date: string, thoughts: Thought[], session_count: int }
  Default date: today

GET /api/thoughts/search?q=query&limit=10
  Response: { query: string, results: SearchResult[], took_ms: int }

GET /api/thoughts/{thought_id}
  Response: Thought with extractions and relationships

PATCH /api/thoughts/{thought_id}/extraction/{extraction_id}
  Body: { status: "done" | "dropped" | "in_progress" }
  Action: Update task status
```

### Agent Routes (`/api/agent/`)

```
POST /api/agent/chat
  Body: { message: string, history?: [{ role, content }] }
  Response: { response: string, tools_used: string[], took_ms: int }

GET /api/agent/status
  Response: { state: string, suppressed_until?: string, queue_depth: int }

POST /api/agent/suppress
  Body: { hours?: int }   (default: 2)
  Action: Suppress check-ins (user said "not now")

POST /api/agent/morning
  Response: { brief: string }
  Action: Trigger morning brief manually (no schedule wait)

POST /api/agent/evening
  Response: { reflection: string }
  Action: Trigger evening reflection manually

GET /api/agent/daily?date=YYYY-MM-DD
  Response: DailyRecord for the given date
```

### Stats Routes (`/api/stats`)

```
GET /api/stats
  Response: {
    total_thoughts: int,
    thoughts_today: int,
    pending_tasks: int,
    llm_calls_today: int,
    tokens_today: { fast_model: int, deep_model: int },
    avg_latency_ms: { stage1: float, stage2: float },
    processing_queue_depth: int,
    db_size_mb: float
  }
```

## main.py Pattern

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from services.memory.db import init_db
from services.agent.scheduler import SIDScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()                  # Create tables if not exist
    scheduler = get_scheduler()
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(title="SID API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],             # localhost only in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from interface.api.routes import voice, thoughts, agent, stats
app.include_router(voice.router, prefix="/api/voice", tags=["voice"])
app.include_router(thoughts.router, prefix="/api/thoughts", tags=["thoughts"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

# Serve simple HTML UI at root
@app.get("/")
async def root():
    return FileResponse("interface/api/templates/index.html")

if __name__ == "__main__":
    uvicorn.run("interface.api.main:app", host="127.0.0.1", port=8765, reload=False)
```

## Reuse from Friday

Copy `../friday/main.py` structure:
- lifespan context manager pattern
- CORSMiddleware setup
- Router organization
- FileResponse for HTML serving

## Dependencies (Internal)

- All services via their `get_*()` singleton getters
- `shared/schemas/models.py` → response models

## Dependencies (External)

```
fastapi>=0.110.0
uvicorn>=0.29.0
python-multipart>=0.0.9  # for form uploads
```

## Testing

```python
# Use httpx.AsyncClient with app for testing (no server needed)
# Test 1: GET /api/thoughts/timeline → 200, empty list on fresh DB
# Test 2: POST /api/voice/start → 200, returns session_id
# Test 3: GET /api/stats → 200, all numeric fields present
# Test 4: POST /api/agent/chat {"message": "what did I think about today?"} → 200
# Test 5: PATCH /api/thoughts/{id}/extraction/{id} → task status updated in DB
```
