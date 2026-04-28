# START HERE — SID Session Resume Instructions

**Read this entire file first. Then read CLAUDE.md. Then read HANDOFF.md.**

---

## What You Are Working On

You are building **SID** (Subjective Intelligence Daemon) — a voice-first, local-first
Personal Cognitive Operating System for Sudheer. It runs 100% locally (no cloud).

**One-line purpose:** Reduce Sudheer's cognitive noise-to-signal ratio.

**Core loop:** Speak → Capture → Process → Store → Reflect → Guide → Repeat

---

## The Technical Stack (already built — do NOT recreate)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Voice | sounddevice + Silero VAD + faster-whisper |
| LLM backend | Ollama on localhost:11434 (OpenAI-compatible) |
| Agent framework | LangGraph |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 (local, not Ollama) |
| Vector DB | LanceDB embedded (~/.sid/vectors/) |
| Structured DB | SQLite via aiosqlite (~/.sid/sid.db, WAL mode) |
| Scheduler | APScheduler AsyncIOScheduler |
| API | FastAPI on localhost:8765 |
| Folder watch | watchdog |
| PDF parsing | PyMuPDF (fitz) |
| TTS | macOS `say` command (non-blocking) |
| Config | pydantic-settings + YAML (config/models.yaml) |

---

## Build Status When You Resume

### ✅ Phase 1 — Complete
Voice capture, SQLite/LanceDB memory, LLM gateway, FastAPI server, processing queue.

### ✅ Phase 2 — Complete
LangGraph 5-node processing pipeline:
`fast_classify → context_loader → deep_extract → assemble → write`

### ✅ Phase 3 — Complete (commit ad1b992)
Full agent brain. Everything below exists and works:

```
services/
├── tts/                        ← macOS say, non-blocking, interruptible
├── agent/
│   ├── fsm.py                  ← 8-state FSM; CAPTURING blocks ALL interrupts
│   ├── scheduler.py            ← APScheduler: 8am, 9pm, 4hr, Sun 8pm
│   ├── chat_agent.py           ← ReAct tool-calling agent, interrogation mode
│   ├── critique.py             ← behavioral profiling, negligence detection
│   └── routines/
│       ├── morning.py          ← top-3 priorities + carry-forward + anchor
│       ├── evening.py          ← journal + done/pending + pattern
│       ├── checkin.py          ← brief status question
│       └── weekly.py           ← behavioral autopsy
└── document_agent/
    ├── extractor.py            ← PDF + text + markdown → text chunks
    └── watcher.py              ← watchdog on ~/Documents/SID/
```

All `/api/agent/*` routes are live (no more 501 stubs).
Scheduler is wired into FastAPI lifespan — starts and stops cleanly.
Document watcher feeds the same processing pipeline as voice.

---

## 10 Critical Rules — Never Violate

1. **Every LLM call goes through `services/llm_gateway/gateway.py`** — `gateway.generate(purpose, prompt, schema)` or `gateway.chat_for(purpose, messages)`. No direct Ollama HTTP calls anywhere else.
2. **Model names live in `config/models.yaml`** — never hardcode in service files.
3. **All data lives in `~/.sid/`** — portable, never scattered.
4. **CAPTURING state blocks ALL interruptions** — scheduler, check-ins, nothing fires while recording.
5. **Voice capture never blocks on LLM processing** — async queue decouples them.
6. **All shared Pydantic models live in `shared/schemas/models.py`** — import from there only.
7. **Voice models (Whisper + VAD) lazy-load** — only on first `start_recording()`, never at import.
8. **TTS is always non-blocking** — speak in background, never blocks event loop.
9. **Document agent feeds same pipeline as voice** — same SQLite table, same LanceDB vectors.
10. **Critique data accumulates forever** — never delete behavioral logs.

---

## Purpose-Based Model Routing (how the LLM gateway works)

All model choices live in `config/models.yaml`. Gateway reads it at init.

```python
# Use these — not gateway.fast() or gateway.deep()
await gateway.generate("morning", prompt, MySchema)    # structured
await gateway.chat_for("checkin", messages)             # free text
model_name = gateway.model_for("critique")              # just the name
```

Current defaults: `qwen2.5:3b` for fast tasks (stage1, checkin), `qwen2.5:14b` for everything else.

---

## Phase 4 — What to Build Next (in this exact priority order)

### P0 — Schema migration (BLOCKS task lifecycle)
Add to `services/memory/schema.sql`:
```sql
ALTER TABLE extractions ADD COLUMN milestone_parent_id TEXT;
ALTER TABLE extractions ADD COLUMN percentage_complete REAL DEFAULT 0;
ALTER TABLE extractions ADD COLUMN time_estimate_hours REAL;
ALTER TABLE extractions ADD COLUMN next_step TEXT;
ALTER TABLE extractions ADD COLUMN closure_note TEXT;

CREATE TABLE IF NOT EXISTS task_closures (
    id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL,
    learning TEXT,
    what_went_wrong TEXT,
    would_do_differently TEXT,
    negligence_flagged INTEGER DEFAULT 0,
    energy_reflection TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(extraction_id) REFERENCES extractions(id)
);

CREATE TABLE IF NOT EXISTS weekly_records (
    week_start TEXT PRIMARY KEY,
    week_end TEXT NOT NULL,
    reflection TEXT,
    planned_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    completion_rate REAL,
    patterns TEXT,
    key_learning TEXT,
    created_at TEXT NOT NULL
);
```
Also: extend `Extraction` in `shared/schemas/models.py` with the new optional fields.
Add `save_task_closure()` and `save_weekly_record()` to `MemoryStore`.
Wire `weekly.py` routine to persist its output into `weekly_records`.

**SQLite migration note:** SQLite doesn't support multiple `ALTER TABLE ADD COLUMN` in a transaction.
Run them one at a time. Use `IF NOT EXISTS` for new tables. Wrap alters in try/except for idempotency.

### P1 — Milestone routine
Build `services/agent/routines/milestone.py`:
- Input: a parent task (Extraction object)
- Use `gateway.chat_for("milestone", ...)` in a conversation loop
- Ask user how to break the task into steps → save as Extractions with `milestone_parent_id = parent.id`
- Add API endpoint: `POST /api/agent/milestone` (body: `{task_id: str}`)

### P2 — Minimal web UI
`interface/api/templates/index.html` — already served at `GET /` by FastAPI.
Vanilla JS or htmx (no build step). Sections needed:
- Today's timeline (cards, oldest at top)
- Pending tasks (checkboxes to mark done)
- Chat box (sends to `/api/agent/chat`)
- Big RECORD button (calls `/api/voice/start` + `/api/voice/stop`)
- Stats bar (pulls from `/api/stats`)

### P3 — macOS menubar
`interface/desktop/` using `rumps` (already in requirements.txt commented out).
- Icon shows FSM state
- Menu: start recording, today's brief, suppress check-ins, quit
- Talks to localhost:8765 via httpx

### P4 — Notifications
Wire into the `_notify()` callback in `interface/api/main.py`:
```python
async def _notify(text: str, event_type: str) -> None:
    # macOS silent notification
    await asyncio.create_subprocess_exec(
        "osascript", "-e",
        f'display notification "{text[:200]}" with title "SID" subtitle "{event_type}"'
    )
    # TTS as well
    await get_tts().speak(text)
```

### P5 — `.env.example`
Document every `Settings` field from `config/settings.py` with defaults.

### P6 — Persist scheduler state
`AgentFSM._last_checkin` resets on restart. Write to `~/.sid/agent_state.json` on change.
Read it at scheduler init.

---

## File Map (quick reference)

```
config/models.yaml              ← ONLY place to change model assignments
config/settings.py              ← env vars, db paths, scheduler times
shared/schemas/models.py        ← ALL Pydantic models — single source of truth
services/llm_gateway/gateway.py ← gateway.generate() / chat_for() / model_for()
services/memory/store.py        ← MemoryStore (SQLite + LanceDB interface)
services/memory/schema.sql      ← DB schema source of truth
services/processing/queue.py    ← async queue: enqueue(), queue_depth()
services/processing/pipeline/   ← LangGraph 5-node pipeline
services/voice/__init__.py      ← VoiceService (lazy-loaded)
services/agent/fsm.py           ← AgentFSM, get_fsm()
services/agent/scheduler.py     ← SIDScheduler, init_scheduler()
services/agent/chat_agent.py    ← chat() function (ReAct loop)
services/agent/critique.py      ← build_behavioral_profile(), get_negligence_report()
services/tts/__init__.py        ← TTSService, get_tts()
services/document_agent/watcher.py ← DocumentWatcher, get_doc_watcher()
interface/api/main.py           ← FastAPI app + full lifespan wiring
interface/api/routes/agent.py   ← /api/agent/* (all live)
main.py                         ← uvicorn entrypoint
```

---

## Git State

- Branch: `claude/review-codebase-REYrk`
- Latest commit: `ad1b992` (docs commit after Phase 3)
- Previous commit: `f352c48` (Phase 3 code)
- Backup remote: `/home/user/sid-backup/sid.git` (local bare repo — origin push 403s)

To push after making changes:
```bash
git push -u backup claude/review-codebase-REYrk
```

---

## How to Run

```bash
# Install
pip install -r requirements.txt

# Ollama must be running with:
ollama pull qwen2.5:3b
ollama pull qwen2.5:14b

# Create data dirs
mkdir -p ~/.sid ~/Documents/SID

# Start
python main.py
# API: http://127.0.0.1:8765
# Docs: http://127.0.0.1:8765/docs
```

---

## One More Thing

Sudheer's philosophy: "SID reduces cognitive noise-to-signal ratio."
Every feature decision maps to this. Capture = collect signal. Pipeline = filter noise.
Agent routines = amplify signal over time. Critique = surface where noise is being generated.
