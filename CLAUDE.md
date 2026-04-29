# SID — Subjective Intelligence Daemon
## Living Memory Document — Read This Before Touching Any Code

This file is the single source of truth for SID. Every design decision, every locked choice,
every future plan lives here. When resuming in a new Claude session, read this fully before
writing a single line.

---

## The One-Line Product Definition

**SID reduces Sudheer's cognitive noise-to-signal ratio.**

Every feature, every architectural choice maps to this. Capture = collect signal. Processing
pipeline = filter noise. Memory graph = amplify signal over time. Agent critique = surface where
noise is being generated. Weekly reflection = consciously improve the ratio.

---

## What SID Actually Is

Not a note app. Not a chatbot. Not a voice recorder.

A **Personal Cognitive Operating System** — a voice-first, memory-native AI layer that
continuously captures raw thoughts, structures them into evolving knowledge, and actively
participates in Sudheer's daily decision-making and personal accountability.

The system externalizes the thinking *process* — not just the output. It records not just what
was said, but why, when, what triggered it, and how it connects to everything else.

**Core loop (never changes):**
```
Speak → Capture → Segment → Process → Store → Reflect → Guide → Repeat
```

Over time: the more data SID has, the sharper its understanding of Sudheer's behavioral
patterns, failure modes, and cognitive style. After 3 months it should know which contexts
cause drift, which task types get avoided, and which times of day produce real thinking.

---

## Repository Layout

```
sid/
├── services/
│   ├── voice/            # Audio capture + VAD + STT → RawChunk
│   ├── tts/              # Text-to-speech output (macOS say → Piper upgrade path)
│   ├── processing/       # RawChunk → MemoryEntry (LangGraph 2-stage pipeline)
│   ├── memory/           # SQLite + LanceDB storage layer
│   ├── agent/            # FSM + scheduler + chat agent + critique engine
│   │   └── routines/     # morning, evening, checkin, weekly
│   ├── document_agent/   # Folder watcher + PDF/text → same memory pipeline
│   └── llm_gateway/      # ALL Ollama calls go through here. No exceptions.
├── interface/
│   ├── api/              # FastAPI REST on localhost:8765
│   │   └── templates/    # index.html (minimal web UI)
│   └── desktop/          # macOS rumps menubar app
├── shared/
│   └── schemas/          # Pydantic models shared across all services
├── config/
│   ├── settings.py       # pydantic-settings, reads .env
│   └── models.yaml       # PURPOSE-BASED model routing. Change models here only.
├── scripts/              # One-off utilities
├── main.py               # Startup: API + scheduler + document watcher + menubar
├── requirements.txt
├── .env                  # Local secrets (never commit)
└── .env.example          # Template for setup
```

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Voice capture | `sounddevice` | Push-to-talk |
| VAD | `silero-vad` (PyTorch) | Silence trim only, not segmentation |
| STT | `faster-whisper` base.en | Lazy-loaded on first recording |
| TTS | macOS `say` command (V1) | Piper TTS planned for V2/Android |
| LLM backend | **Ollama** on localhost:11434 | OpenAI-compatible API |
| Agent framework | **LangGraph** | Pipeline + chat agent both use it |
| Embeddings | `sentence-transformers` all-MiniLM-L6-v2 | Local, never through Ollama |
| Vector DB | **LanceDB** embedded | `~/.sid/vectors/` |
| Structured DB | **SQLite** via aiosqlite | `~/.sid/sid.db`, WAL mode |
| Scheduler | APScheduler (AsyncIOScheduler) | Wired into FastAPI lifespan |
| API | FastAPI | localhost:8765 |
| Folder watching | `watchdog` | `~/SID/inbox/` (visible vault, see Storage Layout) |
| PDF parsing | `PyMuPDF` (fitz) | Document agent |
| macOS UI | `rumps` | Menubar app (Sprint 5) |
| Config | pydantic-settings + YAML | |

---

## Critical Design Rules — Never Violate

1. **Every LLM call goes through `services/llm_gateway/gateway.py`** — no direct Ollama HTTP
   calls anywhere else. Use `gateway.call_for_purpose(purpose, prompt, schema)`.

2. **Model names live in `config/models.yaml`** — never hardcoded in service files. The gateway
   reads this file. Swapping Gemma for Qwen = one line in YAML.

3. **Storage layout is split** (locked Sprint 5): `~/SID/` is the **visible vault** the user
   browses in Finder; `~/.sid/` is **internal data** (DB, vectors, FSM state) the user never
   touches. See "Storage Layout" section below.

4. **Agent FSM state CAPTURING blocks ALL interruptions** — scheduler, check-ins, notifications
   — nothing fires while the user is recording. Voice is sacred.

5. **Voice capture must never block on LLM processing** — async queue decouples them completely.

6. **All shared Pydantic models live in `shared/schemas/models.py`** — import from there only.

7. **Voice models (Whisper + VAD) lazy-load** — only on first `start_recording()` call, never
   at import time. Startup must be fast.

8. **TTS is always non-blocking** — agent speaks in background, never blocks the event loop.

9. **Document agent feeds the same pipeline as voice** — a PDF thought and a spoken thought
   are identical in memory. Same SQLite table, same LanceDB vectors, same processing.

10. **Critique data accumulates forever** — never delete behavioral logs. They become more
    valuable the longer SID runs.

11. **Auto-monitor by default** (locked Stability Sprint, 2026-04-28). SID is not a passive
    retrieval interface. Every meaningful user input — voice capture, dropped document,
    typed chat message, voice reply — passes through Stage 1 classification and, unless
    classified as `random`, is persisted as a Thought and run through the full pipeline.
    Sudheer's intent: *"On day 100 this has more value. We use AI to build, so AI monitors
    every step."* Skip rules: `type=='random'` is dropped; `type=='question'` with
    `confidence<0.5` is dropped (pure retrieval); everything else is captured. The user
    can always force-save with an explicit button if Stage 1 misclassified.

---

## Storage Layout (Locked Sprint 5)

Two directories. The split is intentional and **non-negotiable** for new agents:

```
~/SID/                          ← VISIBLE vault. User-facing. Browsable in Finder.
├── README.txt                  ← explains the layout
├── inbox/                      ← single drop point. Anything here gets ingested.
├── notes/                      ← persistent text/markdown notes (re-watched on edit)
├── processed/<YYYY-MM-DD>/     ← auto-archive after successful ingest
├── flagged/                    ← parse failures (with .reason file alongside)
└── exports/                    ← daily journal exports, weekly review files

~/.sid/                         ← HIDDEN internal data. User never touches.
├── sid.db                      ← SQLite (WAL)
├── vectors/                    ← LanceDB
├── agent_state.json            ← FSM persistence (last_checkin, etc.)
├── sid.log                     ← Server log (rolled by launcher)
└── audio_cache/                ← (future) raw audio backups
```

### Rules

- **`~/SID/` is the user's vault.** They open it in Finder. Files there are theirs.
- **`~/.sid/` is the daemon's data.** Treat it like a database directory.
- **Inbox is single-drop.** Don't make users learn folder taxonomy. SID infers type.
- **Notes folder is re-watched on edit** (Obsidian-style). Editing a note re-ingests
  it, replacing the previous Thought row (same `thought_id` keyed by file path hash).
- **Processed files are auto-archived** to `processed/YYYY-MM-DD/<original-name>` — keeps
  inbox clean, archive is recoverable by date.
- **Flagged files stay in flagged/** with a sibling `<name>.reason` text file explaining
  what went wrong (parse error, unsupported format, etc.).
- **Migration from `~/Documents/SID/`**: setup script moves any existing files at first run.

### Why split visible / hidden

Users need to *see* what SID has. They also need to *not see* the SQLite WAL files,
LanceDB internal index, FSM state JSON. Splitting visible-vault from internal-data is
the simplest mental model that satisfies both. `~/SID/` is browsable; `~/.sid/` is
treated as opaque (back it up, don't peek).

---

## Model Strategy — Purpose-Based Routing

All model routing is in `config/models.yaml`. The gateway maps each purpose to a model.
Sudheer plans to run multiple local models (Qwen, Gemma, Phi-4) and swap them freely.

### Purpose → Model Map

| Purpose | Default | Why |
|---|---|---|
| `stage1` | `qwen2.5:3b` | Fast classification, speed > quality |
| `stage2` | `qwen2.5:14b` | Deep extraction, needs reasoning |
| `agent_chat` | `qwen2.5:14b` | Conversational reasoning |
| `morning` | `qwen2.5:14b` | Narrative generation + planning |
| `evening` | `qwen2.5:14b` | Journal narrative, emotional tone |
| `checkin` | `qwen2.5:3b` | Brief questions, fast |
| `weekly` | `qwen2.5:14b` | Deep behavioral analysis |
| `critique` | `qwen2.5:14b` | Analytical, direct, honest |
| `document` | `qwen2.5:14b` | Reading comprehension + extraction |
| `embedding` | `all-MiniLM-L6-v2` | sentence-transformers, NOT Ollama |

### Local Model Reference (for choosing what to download)

```
qwen2.5:3b    ~2GB RAM   ~1-2s    Best for: Stage 1, check-ins, quick ops
qwen2.5:7b    ~4GB RAM   ~3-4s    Best for: balanced quality/speed
qwen2.5:14b   ~8GB RAM   ~8-12s   Best for: Stage 2, chat, routines (default deep)
qwen2.5:32b   ~18GB RAM  ~25s     Best for: near GPT-4 quality locally
gemma3:4b     ~2.5GB RAM ~2s      Best for: Stage 1 alt, excellent instruction follow
gemma3:12b    ~7GB RAM   ~6-8s    Best for: Stage 2 alt, document extraction
gemma3:27b    ~15GB RAM  ~20s     Best for: weekly/critique if hardware allows
phi4:14b      ~8GB RAM   ~8-12s   Best for: critique, reasoning, behavioral analysis
llama3.2:3b   ~2GB RAM   ~1-2s    Best for: Stage 1 alt, very reliable
llama3.1:8b   ~5GB RAM   ~4-5s    Best for: general purpose alternative
```

**Recommended hardware profile for MacBook:**
- 16GB RAM: qwen2.5:3b (stage1) + qwen2.5:14b (all deep tasks)
- 32GB RAM: add gemma3:12b or phi4:14b for critique/weekly
- 64GB RAM: qwen2.5:32b becomes viable for best quality

---

## All Locked Design Decisions

Recorded from original planning conversations. These are final.

### Input
- **Push-to-talk** for voice capture (V1). Continuous listening is later.
- **Tap** = start/stop new thought capture (new RawChunk → pipeline)
- **Press-hold** = reply to agent's question (same voice flow, different routing)
- Auto-stop at **60 seconds** per chunk — enforced in recorder callback
- VAD trims leading/trailing silence only — mid-sentence pauses preserved
- **Aggressive segmentation**: one thought per chunk, short bursts (5-25 seconds ideal)
- System adapts to natural speech over time. Will eventually give speaking quality feedback.

### Memory
- **Deep extraction (Level C)**: ideas, sub-ideas, tasks, entities, relationships, intent,
  emotional tone, energy hint, why it was said
- Hybrid storage: SQLite (structured) + LanceDB (semantic vectors). No human-readable obsession.
- Raw logs always kept — they become training signal for behavior analysis
- Embeddings: sentence-transformers local, batched async, never through Ollama

### Agent Behavior
- **Check-ins every 4 hours** (NOT 1 hour) — only if ≥1 pending item exists
- **Morning brief at 8am** — pending tasks + yesterday summary + suggested day plan
- **Evening reflection at 9pm** — journal + completion rate + what carries over
- **Weekly review Sunday 8pm** — deep behavioral autopsy, patterns, key learning
- Agent is mostly silent. Speaks when it has something worth saying.
- **Chat agent interrogates first**: 5-6 clarifying questions minimum, up to 20 max,
  before giving any conclusive answer. Builds context before responding.

### Task Lifecycle (Full)
Every task goes through a complete lifecycle:
1. **Extracted** from speech/document by Stage 2
2. **Planned**: agent asks how to break it down → milestones created via conversation
3. **In Progress**: milestone tracking (% complete, next step, time estimate)
4. **Closed**: requires closure note — what was learned, what went wrong,
   what would be done differently. Negligence flagged if applicable.
- Milestones in V1: agent asks user how to break down → user talks → milestones created
- Milestones in V2+: agent suggests based on patterns from past similar tasks
- Always editable via conversation

### Output
- **TTS**: SID speaks back everything — briefs, check-ins, responses, alerts
- macOS `say` command (V1) → Piper TTS upgrade path for V2/Android
- Non-blocking audio: speaks in background, never blocks capture
- **Notifications**: silent for first 15 min → escalating alarm based on priority
  (macOS `osascript` + `afplay` for alarm sound)

### Infrastructure
- Local-first. No cloud dependency ever (optional AWS later)
- `~/.sid/inbox/` — document agent watches this folder continuously
- `~/.sid/flagged/` — documents that couldn't be parsed
- All data portable: pack `~/.sid/`, move anywhere
- macOS `launchd` planned for background scheduling (Phase 4+)

---

## Data Flow (Complete)

```
INPUT LAYER
  Voice (tap)          → recorder.py → vad.py → transcriber.py → RawChunk
  Voice (hold-reply)   → same hardware path → different API route (reply context)
  Document (auto)      → document_agent/watcher.py → extractor.py → RawChunk-equivalent

PROCESSING LAYER (same for all inputs)
  RawChunk → processing/queue.py (async, decoupled)
           → pipeline/graph.py (LangGraph)
               → fast_classifier.py  (Stage 1: type, summary, clean_text, energy)
               → context_loader.py   (vector search: returns {thought_id, text} pairs)
               → deep_extractor.py   (Stage 2: tasks, entities, relationships, intent)
               → assembler.py        (pure Python merge → MemoryEntry)
               → writer.py           (SQLite update + LanceDB upsert)

MEMORY LAYER
  SQLite: thoughts, extractions (with lifecycle), task_milestones, task_closures,
          relationships, sessions, daily_records, weekly_records, llm_calls
  LanceDB: semantic vectors for every thought (thought_id, text, vector, type, date)

AGENT BRAIN
  FSM states: IDLE → CAPTURING → PROCESSING → CHECK_IN → MORNING_BRIEF
                                             → EVENING_REFLECT → WEEKLY_REVIEW → CHAT
  Scheduler (APScheduler):
    08:00 daily    → morning_brief routine
    21:00 daily    → evening_reflect routine
    Every 4 hours  → checkin (only if pending items exist)
    Sunday 20:00   → weekly_review routine
  Chat agent: LangGraph ReAct, interrogates first, answers second
  Critique engine: builds behavioral profile from DB patterns

OUTPUT LAYER
  TTS    → macOS say (non-blocking subprocess)
  Notify → osascript (silent) → afplay alarm (escalating)
  API    → FastAPI responses (for UI clients)

INTERFACE
  FastAPI :8765  → all clients (web UI, menubar, future Android)
  Web UI         → interface/api/templates/index.html (timeline, tasks, chat)
  Menubar        → interface/desktop/ (rumps, Phase 4)
```

---

## Build Status

### Phase 1 ✅ Complete
- Voice: push-to-talk, 60s auto-stop, Silero VAD, faster-whisper (lazy-load fixed)
- Memory: SQLite schema (6 tables), LanceDB vector store, MemoryStore full interface
- LLM Gateway: fast/deep/chat/embed, health_check, JSON retry, async metrics
- FastAPI: voice routes, thoughts routes (timeline/search), stats
- Processing queue: async worker, start/stop/enqueue

### Phase 2 ✅ Complete (3 bugs fixed in same commit)
- LangGraph 5-node pipeline: fast_classify → context_loader → deep_extract → assemble → write
- Bug fixed: context_loader now passes {thought_id, text} pairs (relationships work)
- Bug fixed: session lifecycle at /voice/start and /voice/stop
- Bug fixed: voice models lazy-load on first recording

### Phase 3 ✅ Complete (commit f352c48)
- [x] config/models.yaml — purpose-based routing (11 purposes mapped)
- [x] services/tts/ — macOS `say` non-blocking with interruption + Piper upgrade path
- [x] LLM Gateway — `gateway.generate(purpose, ...)`, `chat_for(purpose, ...)`, lazy embedder
- [x] services/agent/fsm.py — 8-state FSM, CAPTURING blocks all interrupts, suppress() API
- [x] services/agent/scheduler.py — APScheduler: morning 8am, evening 9pm, checkin 4hr, weekly Sun 8pm
- [x] services/agent/routines/morning.py — top-3 priorities + carry-forward + daily anchor
- [x] services/agent/routines/evening.py — journal + done/pending tally + pattern + tomorrow prep
- [x] services/agent/routines/checkin.py — brief status question on recent thoughts
- [x] services/agent/routines/weekly.py — behavioral autopsy with execution gap analysis
- [x] services/agent/chat_agent.py — ReAct tool-calling agent + interrogation mode
- [x] services/agent/critique.py — behavioral profiling, negligence detection, gap score
- [x] /api/agent/* routes — chat, status, suppress, morning, evening, weekly, critique, daily
- [x] services/document_agent/ — watchdog folder watcher + PyMuPDF + text/markdown extractor
- [x] main.py + interface/api/main.py — full lifespan wiring (worker, scheduler, doc watcher, TTS)
- [x] requirements.txt — added watchdog + pymupdf

### Phase 3 bug fixes (same commit)
- [x] context_loader returns {thought_id, text, score} dicts → relationships now extracted
- [x] /voice/start writes session row, /voice/stop increments thought_count + end_time
- [x] VoiceService lazy-loads VAD + Whisper on first start_recording() (was eager in __init__)

### Phase 4 ✅ Complete (commit 91cb8f7)
- [x] Schema migration: task lifecycle columns + task_closures + weekly_records tables
- [x] FSM persistence: ~/.sid/agent_state.json (last_checkin survives restarts)
- [x] Web UI rebuild: tasks panel, chat box, type-coloured timeline, sticky header
- [x] /api/agent/tasks + /api/agent/recap endpoints
- [x] chat_agent metrics: every agent_chat call records to llm_calls

### Sprint 2 ✅ Complete (commit 63f9c26) — Resilience
- [x] Persistent SQLite-backed processing_queue (replaces in-memory asyncio.Queue)
- [x] Crash-safe: orphaned 'processing' rows reset to 'pending' on startup
- [x] Priority lanes: voice=1, document=5; voice always cuts the document line
- [x] Confidence-skip: Stage 1 conf < 0.4 routes straight to assemble (no Stage 2)
- [x] Ollama health monitor: healthy / unhealthy / stuck classification, UI pills

### Sprint 3 ✅ Complete (commit 8e53ce5) — Multi-provider gateway
- [x] config/models.yaml restructured with providers block (ollama / openai / anthropic)
- [x] gateway.config_for(purpose) → (model, provider, client) honours route overrides
- [x] Anthropic native_json_schema=false path: prompt-based JSON extraction
- [x] Cloud fallback when Ollama is "stuck"; cost recorded per-call
- [x] Failed-queue UI panel with retry/drop buttons

### Brain Sprint A ✅ Complete (commits 751d096 → d77d300) — Agent intelligence
- [x] B1 — Milestone routine: POST /api/agent/milestone + Plan button + chat tool
- [x] B2 — Task closure flow: POST /api/agent/closure + closure modal in UI
- [x] B3 — Interrogation enforcement: stateless gate, mode pill, "just answer" bypass
- [x] B5 — Press-hold reply routing: POST /api/voice/reply (chat, not memory)

### Stability Sprint 🔨 Active — Bug fixes + auto-monitor (paused Sprint 5)
**Plan: see `STABILITY.md` for full hand-off contract.**
First end-to-end test on 2026-04-28 surfaced 4 issues: stop-recording broken,
"tasks not captured from chat" (auto-extract missing), mic UX bugs, logging
too thin. Fixing the substrate before layering the Mac desktop surface.

Tasks:
- [ ] F1 — Recording lifecycle: debounce, /voice/cancel, server reconciliation
- [ ] F2 — Eager-load voice models at server boot (default ON)
- [ ] F3 — Mic device probe + clear permission error
- [ ] F4 — Structured logging to ~/.sid/sid.log (rotated)
- [ ] F5 — Auto-extract chat + save_thought tool + Save button

### Sprint 5 ⏸ Paused — Mac Desktop App + File Vault
**Plan: see `SPRINT_5.md` for full hand-off contract.**
Locked decisions (2026-04-28):
- Vault at `~/SID/` (visible) + `~/.sid/` (internal data)
- Single-drop `inbox/`, auto-archive to `processed/YYYY-MM-DD/`
- `notes/` re-watched on edit (Obsidian-style)
- rumps menubar + browser UI (no PyWebView yet)
- Manual launch only (no launchd / auto-start at login until trusted)

Tasks:
- [ ] S5.1 — Vault restructure: ~/SID/ tree, watcher handles inbox + notes,
            auto-archive, flag failures with .reason file, migrate from
            ~/Documents/SID/
- [ ] S5.2 — rumps menubar app: status, Open SID, quick record, Open vault,
            suppress, trigger morning/evening, quit
- [ ] S5.3 — Launcher: run.sh + run.command, server lifecycle managed by menubar
- [ ] S5.4 — setup.sh wizard: idempotent first-run check + bootstrap
- [ ] S5.5 — SETUP.md + final CLAUDE.md polish

### Brain Sprint B 🔭 Deferred (needs ~2 weeks of real captures)
- [ ] B4 — Proactive surfacing in chat ("you've mentioned X 7 times, no progress")
- [ ] B6 — Critique → check-in coupling (negligence flags seed check-in questions)
- [ ] B7 — Memory consolidation (re-relink old thoughts as new ones arrive)

### Sprint 4 🔭 Deferred — Tests + dev mode
- [ ] pytest harness with in-memory SQLite + temp LanceDB + MockGateway
- [ ] SID_DEV_MODE=true → MockGateway → iterate UI without Ollama

### Future Vision
- Android (Nothing 2a): same backend, new interface layer
- macOS launchd: OS-level scheduling, zero battery when idle
- Camera/vision module: photo → extract → same memory pipeline
- Behavioral prediction: after 60 days, SID predicts patterns
- Speaking quality feedback: SID coaches Sudheer to speak more signal-dense
- Multi-model performance metrics: track which model gives better insights per purpose

---

## Database Schema (Current + Planned Additions)

### Core Tables (exist)
```sql
thoughts          -- every captured thought (raw + processed)
extractions       -- tasks, sub_ideas, entities extracted from thoughts
relationships     -- semantic links between thoughts
sessions          -- recording sessions (voice start → stop)
daily_records     -- morning_plan, actual_log, evening_reflection per day
llm_calls         -- every LLM call for observability/cost tracking
```

### Schema Additions (Phase 3)
```sql
-- Extended task lifecycle columns on extractions:
milestone_parent_id   TEXT         -- points to parent task id (for milestones)
percentage_complete   REAL DEFAULT 0
time_estimate_hours   REAL
next_step             TEXT
closure_note          TEXT         -- what was learned at task close

-- New tables:
task_closures         -- full closure record when task completes
  (id, extraction_id, learning, what_went_wrong, would_do_differently,
   negligence_flagged INTEGER, energy_reflection, created_at)

weekly_records        -- weekly review output
  (week_start TEXT PK, week_end, reflection, planned_tasks INTEGER,
   completed_tasks INTEGER, completion_rate REAL, patterns TEXT,
   key_learning TEXT, created_at)
```

---

## Agent Behavior Specification

### FSM States
```
IDLE             → resting, listening for scheduler triggers
CAPTURING        → user is recording. ALL interruptions blocked.
PROCESSING       → pipeline running on last chunk (non-blocking, background)
CHECK_IN         → 4-hour check-in conversation active
MORNING_BRIEF    → 8am morning routine active
EVENING_REFLECT  → 9pm evening routine active
WEEKLY_REVIEW    → Sunday weekly deep review active
CHAT             → user-initiated memory conversation
```

### Morning Brief (8am)
1. Query pending tasks ordered by priority
2. Query yesterday's thoughts (timeline)
3. Query daily_record for yesterday (completion rate)
4. Generate: what's pending, what you said yesterday, suggested focus for today
5. Write structured plan to daily_records.morning_plan
6. Speak via TTS
7. Send macOS notification

### Evening Reflection (9pm)
1. Query today's thoughts (full timeline)
2. Query today's tasks (completed + still pending)
3. Calculate completion rate
4. Generate journal narrative + what carries over
5. Write to daily_records.evening_reflection + completion_rate
6. Speak via TTS

### 4-Hour Check-in (only if ≥1 pending task)
1. Check FSM state — abort if CAPTURING
2. Count pending tasks
3. If ≥1 pending: pick most important pending item
4. Ask one focused question about it
5. Wait for voice reply (press-hold) or skip
6. Record response, update task notes

### Weekly Review (Sunday 8pm)
1. Query full week's thoughts, tasks, completions
2. Calculate week completion rate
3. Identify: what was planned vs done, recurring drops, energy patterns
4. Generate critique (direct, honest, not gentle)
5. Write to weekly_records
6. Speak full review via TTS
7. Store behavioral patterns in critique log for future comparison

### Chat Agent (user-initiated)
- LangGraph ReAct agent
- Tools: search_memory, get_timeline, get_pending_tasks, get_daily_record,
         get_related_thoughts, get_weekly_record
- **INTERROGATION MODE**: always asks 5-6 clarifying questions minimum, up to 20 max
  before giving any conclusive answer. Never jumps to conclusions.
- Proactively surfaces patterns: "You've mentioned SmartPal 7 times but no tasks closed"
- Press-hold button sends voice reply into ongoing chat context

### Critique Engine
- Runs during weekly review and on demand
- Analyzes: task completion rate by type, tasks dropped > 2 times, energy level patterns,
  time-of-day productivity patterns, negligence flags, commitment-to-action ratio
- Output: direct behavioral assessment, specific patterns with evidence from data
- All critique logs stored permanently — they are the meta-learning dataset

---

## Service Dependencies (Build Order)

```
shared/schemas/models.py     ← build first
config/settings.py           ← build second
config/models.yaml           ← build third (gateway reads this)
services/llm_gateway/        ← depends on: config, shared/schemas
services/memory/             ← depends on: config, shared/schemas, llm_gateway
services/tts/                ← depends on: config only
services/voice/              ← depends on: config, shared/schemas
services/processing/         ← depends on: llm_gateway, memory, shared/schemas
services/agent/              ← depends on: memory, llm_gateway, processing, tts
services/document_agent/     ← depends on: processing, memory
interface/api/               ← depends on: all services
interface/desktop/           ← depends on: interface/api (HTTP)
main.py                      ← starts everything
```

---

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Set up config
cp .env.example .env
# Edit .env with your settings

# Ensure Ollama is running with at least one model:
ollama pull qwen2.5:3b
ollama pull qwen2.5:14b

# Create inbox folder for document agent
mkdir -p ~/.sid/inbox ~/.sid/flagged

# Start SID
python main.py
# API available at http://localhost:8765
# Docs at http://localhost:8765/docs
```

---

## What Makes This Different

Most AI tools: `input → output`

SID: `input → memory → evolution → behavioral influence`

The system stores the *thinking process* — why something was said, how it evolved, what
influenced it, how it connects across days and weeks. After enough data:
- Sudheer never loses an idea again
- Patterns in thinking become visible
- Accountability becomes automatic
- Execution alignment improves without conscious effort
- The ratio of signal to noise in his life measurably improves

---

## Reference

- All Ollama calls: OpenAI-compatible format via `openai` Python client
- LangGraph patterns: TypedDict state, lazy graph compilation, ainvoke for async
- Context loader MUST pass {thought_id, text} dicts — plain text strings break relationships
- Sessions MUST be created at /voice/start and closed at /voice/stop
- Voice models MUST be lazy-loaded — never in __init__
