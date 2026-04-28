# SID — Session Handoff Document

**Last updated:** 2026-04-28
**Current branch:** `claude/review-codebase-REYrk`
**Latest commit:** `f352c48` — Phase 3 complete
**Backup remote:** `/home/user/sid-backup/sid.git` (push works, GitHub origin push fails 403)

---

## Read This First

When you (next Claude session) resume:

1. **Read `CLAUDE.md` in full** — it's the living memory document with all locked design decisions, model strategy, FSM behavior, routine specs.
2. **Read this file (`HANDOFF.md`)** for the precise current state and next steps.
3. **Check git log** — `git log --oneline -10` shows recent commits.
4. **Don't recreate work** — Phases 1, 2, and 3 are complete. Verify with `ls services/` before building.

---

## What Just Got Done (Phase 3)

Single commit: `f352c48` — 26 files, +2207 / -202

### Bug fixes
1. **`context_loader.py`** — was returning `List[str]`, losing `thought_id`. Now returns
   `[{"thought_id", "text", "score"}, ...]` so `deep_extractor` can format context as
   `[<id>]: <text>` and the LLM can produce real relationships.
2. **Session lifecycle** — `/voice/start` now calls `store.create_session()`, `/voice/stop`
   calls `store.touch_session()` to increment `thought_count` and update `end_time`.
3. **VoiceService lazy loading** — `__init__` no longer loads VAD + Whisper. They load
   on first `start_recording()` call. Startup is now fast.

### New services
- `services/tts/` — macOS `say` subprocess, non-blocking, interruptible.
- `services/agent/fsm.py` — 8-state FSM. `CAPTURING` blocks all interrupts. `suppress(hours)` API.
- `services/agent/scheduler.py` — APScheduler with 4 jobs (morning, evening, checkin, weekly).
  Each job checks `fsm.can_interrupt()` before firing.
- `services/agent/routines/{morning,evening,checkin,weekly}.py` — all use real prompts.
- `services/agent/chat_agent.py` — ReAct loop with OpenAI-compatible tool calling.
  Tools: `search_memory`, `get_pending_tasks`, `get_today`, `get_date`. Interrogation mode
  is in the system prompt.
- `services/agent/critique.py` — `BehavioralProfile` Pydantic schema, `build_behavioral_profile()`
  and `get_negligence_report()`.
- `services/document_agent/extractor.py` — PDF (PyMuPDF) + text/markdown chunked at ~3000 chars.
- `services/document_agent/watcher.py` — watchdog observer on `~/Documents/SID/`. Each file
  becomes one or more `RawChunk` objects via the same processing queue as voice.

### Updated services
- **LLM Gateway** — loads `config/models.yaml` at init. New API:
  - `gateway.generate(purpose, prompt, schema)` → structured call routed by purpose
  - `gateway.chat_for(purpose, messages)` → free-text chat routed by purpose
  - `gateway.model_for(purpose)` → returns model name string
  - Old `fast()`, `deep()`, `chat()` still work (they map to stage1/stage2/agent_chat purposes)
- **Memory Store** — added `create_session()` and `touch_session()`.
- **API routes** — all `/api/agent/*` endpoints implemented (was 501 stubs):
  - `POST /api/agent/chat` — ReAct chat with optional history
  - `GET /api/agent/status` — FSM state + suppression + queue depth
  - `POST /api/agent/suppress` — silence check-ins for N hours
  - `POST /api/agent/morning` — manually trigger morning brief
  - `POST /api/agent/evening` — manually trigger evening reflection
  - `POST /api/agent/weekly` — manually trigger weekly review
  - `GET /api/agent/critique` — behavioral autopsy report
  - `GET /api/agent/daily?date=YYYY-MM-DD` — timeline for a day
- **`interface/api/main.py`** — lifespan now starts and shuts down: memory init,
  LLM health check, processing worker, scheduler, document watcher.

---

## What's Next (Phase 4 — in priority order)

### P0 — Schema migration (blocks task lifecycle features)
The task lifecycle columns are documented in `CLAUDE.md` but not yet in `schema.sql`.

Add to `services/memory/schema.sql`:
```sql
-- Add to extractions:
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

SQLite gotcha: `ALTER TABLE ADD COLUMN` is idempotent only if you check first. Either:
- Build a small migration runner (track version in a `schema_version` table), OR
- Use `CREATE TABLE IF NOT EXISTS` for new tables and wrap ALTER in try/except for fresh DBs.

After schema change: extend `Extraction` Pydantic model in `shared/schemas/models.py`,
add `save_task_closure()` and `save_weekly_record()` to `MemoryStore`, and wire
`weekly.py` to persist its output.

### P1 — Milestone routine (task breakdown via conversation)
Build `services/agent/routines/milestone.py`:
- Input: a parent task (Extraction)
- Calls `gateway.chat_for("milestone", ...)` to ask user how to break it down
- Saves resulting milestones as Extractions with `milestone_parent_id = parent.id`
- Used from chat agent ("plan the X task") and via API endpoint

### P2 — Web UI
Build `interface/api/templates/index.html`:
- Single-page minimal UI (vanilla JS or htmx — no build step)
- Sections: today's timeline, pending tasks, chat box, big record button
- Uses `/api/voice/*`, `/api/thoughts/*`, `/api/agent/chat`, `/api/stats`
- Already wired to be served at `GET /` in `interface/api/main.py`

### P3 — macOS menubar
Build `interface/desktop/` with `rumps`:
- Menubar icon shows FSM state (●●○ idle / ●●● recording / ●○● processing)
- Click → quick menu: start recording, today's timeline, chat input, suppress, quit
- Talks to FastAPI backend over HTTP

### P4 — macOS notifications
- `osascript -e 'display notification "..." with title "SID"'` for silent
- For escalating alarm: `afplay /System/Library/Sounds/Glass.aiff` repeated
- Wire into the `_notify` callback in `interface/api/main.py`

### P5 — `.env.example`
Document every environment variable from `config/settings.py`:
```
SID_DATA_DIR=~/.sid
SID_MORNING_HOUR=8
SID_EVENING_HOUR=21
SID_CHECKIN_INTERVAL_HOURS=4
SID_CHECKIN_THRESHOLD=1
SID_WHISPER_MODEL=base.en
SID_SAMPLE_RATE=16000
SID_MAX_RECORDING_SECONDS=60
SID_VAD_THRESHOLD=0.5
SID_API_HOST=127.0.0.1
SID_API_PORT=8765
OLLAMA_BASE_URL=http://localhost:11434
```

### P6 — Scheduler persistence
Currently `AgentFSM._last_checkin` is in-memory and resets on restart. Move to a
`agent_state` table or simple JSON file at `~/.sid/agent_state.json`.

---

## Known Limitations / Tech Debt

1. **`config/settings.py` still references `fast_model` and `deep_model`** as `Field()`s.
   They're only used by `store.get_stats()` for token aggregation. Either remove and
   update stats to aggregate by model from `models.yaml`, or leave as legacy alias.

2. **No tests written.** All code is hand-validated. Once on macOS with Ollama running,
   smoke-test by:
   - `python main.py` → API starts at :8765
   - `curl -X POST localhost:8765/api/agent/morning` → should return brief
   - `curl localhost:8765/api/agent/status` → should return idle FSM state
   - Drop a PDF in `~/Documents/SID/` → should appear in `/api/thoughts/timeline`

3. **Scheduler triggers in development environment** — if you run `python main.py` at 8am,
   it will fire the morning brief. Use `SID_MORNING_HOUR=99` (invalid hour silently skips)
   or set hours far away during development.

4. **TTS voice is hardcoded** to "Samantha" in `services/tts/__init__.py`. Move to
   `models.yaml` or `.env` if Sudheer prefers a different voice.

5. **chat_agent uses `tool_choice="auto"`** — Ollama's tool calling support varies by
   model. `qwen2.5:14b` works; smaller models may not. If problematic, switch to
   ReAct-via-prompting instead of native tool calls.

6. **PyMuPDF on Linux/Windows** — works fine. On macOS Apple Silicon, prefer wheels
   to avoid building from source: `pip install --upgrade pymupdf`.

7. **GitHub origin push fails 403** — proxy permission. We push only to `backup` remote.
   To configure backup remote on the next machine:
   ```bash
   git init --bare /path/to/sid-backup/sid.git
   git remote add backup /path/to/sid-backup/sid.git
   git push -u backup claude/review-codebase-REYrk
   ```

---

## Where Things Live

```
sid/
├── CLAUDE.md                      ← living memory (read first)
├── HANDOFF.md                     ← this file
├── config/
│   ├── models.yaml                ← purpose → model map (change here only)
│   └── settings.py                ← env vars, paths, scheduler hours
├── services/
│   ├── voice/                     ← lazy-loaded; recorder + VAD + Whisper
│   ├── memory/                    ← SQLite + LanceDB; schema.sql
│   ├── llm_gateway/               ← purpose-based routing; gateway.generate(purpose, ...)
│   ├── processing/                ← async queue + 5-node LangGraph pipeline
│   ├── agent/
│   │   ├── fsm.py                 ← 8 states; CAPTURING blocks interrupts
│   │   ├── scheduler.py           ← 4 APScheduler jobs
│   │   ├── chat_agent.py          ← ReAct + interrogation mode
│   │   ├── critique.py            ← behavioral profile
│   │   └── routines/              ← morning, evening, checkin, weekly
│   ├── tts/                       ← macOS say, non-blocking
│   └── document_agent/            ← watchdog + PyMuPDF + text/markdown
├── interface/api/
│   ├── main.py                    ← FastAPI app + lifespan (starts everything)
│   └── routes/                    ← voice, thoughts, agent, stats
├── shared/schemas/models.py       ← all Pydantic models (single source)
└── main.py                        ← uvicorn entrypoint
```

---

## Run It

```bash
# Install deps
pip install -r requirements.txt

# Make sure Ollama is up with models in models.yaml
ollama pull qwen2.5:3b
ollama pull qwen2.5:14b

# Create folders
mkdir -p ~/.sid ~/Documents/SID

# Start everything
python main.py
# → API at http://127.0.0.1:8765
# → Docs at http://127.0.0.1:8765/docs
# → Document watcher on ~/Documents/SID/
# → Scheduler running (morning 8am, evening 9pm, checkin every 4h, weekly Sun 8pm)
```

---

## Quick Sanity Checks for the Next Session

```bash
# Confirm nothing was lost
git log --oneline -5
git status                          # should be clean
git remote -v                       # should show backup remote
ls services/agent/                  # fsm.py, scheduler.py, chat_agent.py, critique.py, routines/
ls services/document_agent/         # extractor.py, watcher.py
ls services/tts/                    # __init__.py
cat config/models.yaml | head -20   # purpose-based routing intact
```

If any of those are missing, restore from `/home/user/sid-backup/sid.git`:
```bash
git fetch backup
git reset --hard backup/claude/review-codebase-REYrk
```
