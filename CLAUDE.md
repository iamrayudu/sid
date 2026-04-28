# SID — Subjective Intelligence Daemon

## What This Is

SID is a voice-first, local-first personal cognitive OS. It captures speech, structures it into memory, and actively participates in Sudheer's daily decision-making. Think Jarvis, but offline and owned.

**Core loop**: Speak → Capture → Segment → Process → Store → Reflect → Guide → Repeat

## Repository Layout

```
sid/
├── services/
│   ├── voice/          # Audio capture + VAD + STT → RawChunk
│   ├── processing/     # RawChunk → MemoryEntry (LangGraph 2-stage pipeline)
│   ├── memory/         # SQLite + LanceDB storage layer
│   ├── agent/          # Behavior FSM + scheduler + chat agent
│   └── llm_gateway/    # ALL Ollama calls go through here (no exceptions)
├── interface/
│   ├── api/            # FastAPI REST API on localhost:8765
│   └── desktop/        # macOS rumps menubar app
├── shared/
│   └── schemas/        # Pydantic models shared across all services
├── config/             # Settings + model config YAML
├── scripts/            # One-off utilities
├── main.py             # Startup entrypoint (starts API + scheduler + menubar)
├── requirements.txt
└── .env                # Local secrets (never commit)
```

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Voice capture | `sounddevice` |
| VAD | `silero-vad` (PyTorch) |
| STT | `faster-whisper` (base.en model) |
| LLM backend | **Ollama** on localhost:11434 |
| Fast model | qwen2.5:3b (Stage 1 classification) |
| Deep model | qwen2.5:14b or 16GB local model (Stage 2 extraction) |
| Agent framework | **LangGraph** |
| Embeddings | `sentence-transformers` all-MiniLM-L6-v2 (local, int8) |
| Vector DB | **LanceDB** (embedded, no server) |
| Structured DB | **SQLite** via aiosqlite |
| Scheduler | APScheduler |
| API | FastAPI |
| macOS UI | rumps (menubar) |
| Config | pydantic-settings + YAML |

## Critical Design Rules (Never Violate)

1. **Every LLM call goes through `services/llm_gateway/gateway.py`** — no direct Ollama HTTP calls anywhere else
2. **Model names live in `config/models.yaml`** — never hardcoded in service files
3. **LanceDB and SQLite live in `~/.sid/`** — all user data in one portable directory
4. **Agent FSM state CAPTURING blocks all interruptions** — never disrupt mid-capture
5. **Voice capture must never block on LLM processing** — async queue decouples them
6. **All shared Pydantic models live in `shared/schemas/models.py`** — import from there

## Service Dependencies (Build Order Matters)

```
shared/schemas/models.py     ← No dependencies, build first
config/settings.py           ← No dependencies
services/llm_gateway/        ← Depends on: config, shared/schemas
services/memory/             ← Depends on: config, shared/schemas, llm_gateway (for embeddings)
services/voice/              ← Depends on: config, shared/schemas
services/processing/         ← Depends on: llm_gateway, memory, shared/schemas
services/agent/              ← Depends on: memory, llm_gateway, processing
interface/api/               ← Depends on: all services
interface/desktop/           ← Depends on: interface/api (HTTP calls to localhost:8765)
main.py                      ← Imports and starts everything
```

## Data Flow

```
[User presses record] → voice/recorder.py
    → voice/vad.py (Silero VAD trims silence)
    → voice/transcriber.py (faster-whisper)
    → RawChunk (shared/schemas/models.py)
    → processing/queue.py (async queue)
    → processing/pipeline/graph.py (LangGraph)
        → nodes/fast_classifier.py  (Ollama via llm_gateway, Stage 1)
        → nodes/context_loader.py   (LanceDB vector search)
        → nodes/deep_extractor.py   (Ollama via llm_gateway, Stage 2)
        → nodes/assembler.py        (pure Python merge)
        → nodes/writer.py           (SQLite + LanceDB write)
    → MemoryEntry stored

[Every hour, if ≥3 new thoughts] → agent/scheduler.py triggers check-in
[8am daily] → agent/routines/morning.py generates morning brief
[9pm daily] → agent/routines/evening.py generates journal
[User says "let's look back"] → agent/chat_agent.py queries memory
```

## Build Phases

- **Phase 1** (Week 1-2): Voice + raw storage — press button, speak, see transcript saved
- **Phase 2** (Week 3-4): Processing pipeline + memory — structured extractions + embeddings
- **Phase 3** (Week 5-6): Agent brain + daily loop — proactive check-ins, morning/evening routines
- **Phase 4** (Week 7-8): Polish + UI — menubar app, timeline view, search UI

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Set up config (copy and edit)
cp .env.example .env

# Start SID
python main.py
```

## Reference

- `friday/` project at `../friday/` has reusable LangGraph + FastAPI patterns
- Copy patterns (TypedDict state, lazy cache, upsert) but NOT ChromaDB or Gemini
- All Ollama calls: use OpenAI-compatible API format via `httpx` or `openai` client
