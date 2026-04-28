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
| Folder watching | `watchdog` | `~/.sid/inbox/` for documents |
| PDF parsing | `PyMuPDF` (fitz) | Document agent |
| macOS UI | `rumps` | Menubar app (Phase 4) |
| Config | pydantic-settings + YAML | |

---

## Critical Design Rules — Never Violate

1. **Every LLM call goes through `services/llm_gateway/gateway.py`** — no direct Ollama HTTP
   calls anywhere else. Use `gateway.call_for_purpose(purpose, prompt, schema)`.

2. **Model names live in `config/models.yaml`** — never hardcoded in service files. The gateway
   reads this file. Swapping Gemma for Qwen = one line in YAML.

3. **LanceDB and SQLite live in `~/.sid/`** — all user data in one portable directory.

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
- **Push-to-talk** for voice capture (V1). Continuous listening is Phase 5.
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

### Phase 3 🔨 In Progress
- [ ] config/models.yaml (purpose-based routing)
- [ ] Schema migration (task lifecycle, milestones, closures, weekly_records)
- [ ] services/tts/ (macOS say, non-blocking)
- [ ] LLM Gateway: purpose-based routing from models.yaml
- [ ] services/agent/fsm.py
- [ ] services/agent/scheduler.py
- [ ] services/agent/routines/morning.py
- [ ] services/agent/routines/evening.py
- [ ] services/agent/routines/checkin.py
- [ ] services/agent/routines/weekly.py
- [ ] services/agent/chat_agent.py (interrogation mode)
- [ ] services/agent/critique.py (behavioral profiling)
- [ ] /api/agent/* routes (all real implementations)
- [ ] macOS notifications

### Phase 4 📋 Planned
- [ ] services/document_agent/ (watchdog + PyMuPDF)
- [ ] interface/desktop/ (rumps menubar)
- [ ] interface/api/templates/index.html (web UI)
- [ ] .env.example

### Phase 5+ 🔭 Future Vision
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
