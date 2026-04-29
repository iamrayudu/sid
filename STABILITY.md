# SID — Stability Sprint
## Bug Fixes + Auto-Monitor — Hand-off Contract

**Why this exists:** Sudheer's first end-to-end test surfaced 3 product-blocking bugs
and one critical design gap. We pause Sprint 5 (Mac desktop app) to fix them, because
shipping a menubar over a broken record button is worthless. Brain Sprint A and Sprint
2/3 plumbing all work, but the recording UX and the chat→memory bridge need to be
right before we layer a Mac surface on top.

**Last updated:** 2026-04-28 by main-instance Claude.
**Branch:** `main` (single source of truth).
**HEAD at sprint start:** `6cab2bf` (Sprint 5 plan locked).

---

## Why Stability Comes Before Sprint 5

Sprint 5 is "make SID feel like a Mac app." But:

- The record button is broken (Bug #1).
- Auto-extraction from chat is missing (Bug #2 — Sudheer's "tasks not added" feedback).
- The mic init experience is invisible to the user (Bug #3 — first-press blocks 30s).
- Logging coverage is too thin to debug the above without re-running with print statements.

A menubar app inherits all of these. So fix the substrate first, then layer the
desktop surface on top.

---

## Locked Decisions (Sudheer 2026-04-28)

| # | Decision | Why |
|---|---|---|
| **1** | **Auto-extract by default** from chat user messages and voice replies | Sudheer doesn't use SID for chitchat — every input matters. Day 100 value comes from total context. |
| 2 | Skip Stage 1 type=='random' and (type=='question' AND confidence<0.5) | Pure retrieval queries don't pollute memory. |
| 3 | Eager-load Whisper + Silero VAD at server boot (default ON) | First-press blocking 30s is unacceptable for "feels like an app." Server boot is slower; first record is instant. |
| 4 | Logs go directly to `~/.sid/sid.log` (final home) | No `/tmp/` indirection. Sprint 5 launcher will rotate this file. |
| 5 | F5 ships **all three** chat→memory paths: auto-extract + `save_thought` agent tool + "Save" button | Auto for the common case; tool for agent-driven; button for failsafe override. |
| 6 | New `/voice/cancel` endpoint to force-reset recording state | When the client and server desync, one click escapes the lock. |

---

## The 4 Bugs (Diagnosed)

### Bug #1: Stop recording is broken

Multi-cause:
- No client-side click debounce → multiple concurrent `/voice/start` requests.
- `stopRecording()` no-ops silently when `sessionId` is null (which it is during
  the 30s VAD download).
- `/api/agent/status` doesn't expose the server's `_recording` flag → no way for
  client to reconcile.
- Press-hold mic and main RECORD share the same `_recording` global → state collision
  if either flow's release races against its start.

### Bug #2: "Tasks not added from chat conversation"

By design, chat is conversation-only — only voice and documents save to memory.
But Sudheer's mental model expects chat to also capture. Combined with Bug #1
(can't record), every meaningful input from his test session was lost.

### Bug #3: "Mic has bugs"

- VAD downloads from GitHub on first start (~30s) with no UI feedback.
- No mic permission probe → if macOS denies, error is buried inside sounddevice.
- 60s auto-stop in recorder doesn't notify UI or clear server `_recording`.
- No volume/level feedback in UI → can't tell if voice is being captured.

### Bug #4: Logging coverage is too thin

What's captured today:
- FastAPI access log (HTTP method/path/status)
- `llm_calls` table (every LLM call)
- `sessions`, `processing_queue` tables

What's missing (hard to diagnose Bug #1-#3 without these):
- Voice route state transitions (`_recording`, `_current_session_id`)
- Whisper/VAD initialization timing
- Mic device info on first start
- Document watcher events (file detected, ingested, archived, flagged)
- Pipeline node-by-node progress
- Errors silenced in catch-all `except Exception`

---

## Operating Rules for Agents

1. **One commit per fix (F1 → F5).** Push after each commit.
2. **Pull `origin/main` before starting any task.**
3. **Update this doc** when finishing: tick boxes, paste commit SHA.
4. **If blocked**, append to "Open questions / blockers" and stop.
5. **Run `./run.sh` (after S5.3) or `python main.py` to smoke-test live.** Container
   Claudes can't run mic/audio paths — they verify with static checks (compile, import,
   schema) and document what live verification is needed.

---

## Sprint Task Index

| ID | Title | Status | Commit |
|---|---|---|---|
| F1 | Recording lifecycle fix | pending | — |
| F2 | Eager voice load at server boot | pending | — |
| F3 | Mic device probe + clear errors | pending | — |
| F4 | Structured logging to ~/.sid/sid.log | pending | — |
| F5 | Auto-extract chat + save_thought tool + Save button | pending | — |

---

## F1 — Recording lifecycle fix

### Goal
Recording can ALWAYS be started, stopped, and recovered from a stuck state.
Client and server stay in sync via the existing 3s status poll.

### Files to modify
- `interface/api/routes/voice.py`
  - Add `POST /api/voice/cancel` — force-resets `_recording=False`,
    `_current_session_id=None`, calls `voice_service._recorder.stop()` if loaded.
  - Add to `StatusResponse`: `recording_session_id` (the server's current
    `_current_session_id`, exposed for client reconciliation).
  - Move state into a small `RecordingState` dataclass to make reasoning easier;
    keep the global pattern for now (don't restructure the world).
- `interface/api/routes/agent.py`
  - Extend `/api/agent/status` response to include `voice: {recording, session_id}`
    (mirror what's in `/api/voice/status` so a single poll is enough for the UI).
- `interface/api/templates/index.html`
  - **Click debounce:** `recBtn` becomes a state machine — `idle | starting |
    recording | stopping | error`. Disable button while in `starting`/`stopping`.
  - **Loading overlay** during `starting`: button shows "Loading model…" with
    a spinner. After F2 this should be a no-op for normal use, but keeps a
    fallback for slow first-runs.
  - **Server reconciliation:** the existing `pollStatus()` reads `voice.recording`
    and `voice.session_id` from the response; if server says recording but
    client thinks idle (or vice versa), client adopts server state. Adds a
    "Force reset" link in the UI status pill that hits `/api/voice/cancel`.
  - **Same fixes for press-hold mic** (`replyHolding`): debounce, reconciliation,
    cancel-on-leave.

### Acceptance
- [ ] Click RECORD ten times rapidly → only ONE `/voice/start` fires.
- [ ] Server log shows clear state transitions every start/stop.
- [ ] If server `_recording=True` but client thinks idle, next status poll
      flips client to recording state with the server's session_id.
- [ ] `POST /api/voice/cancel` works any time — empties recorder buffer,
      clears flags, returns 200.
- [ ] "Force reset" link is hidden in steady state, appears as a small
      action when desync is detected.
- [ ] Press-and-hold the chat mic, release IMMEDIATELY (faster than the
      server start can return) → state stays consistent (cancel fires on
      release if start hadn't returned yet).

### Commit message
```
F1: recording lifecycle — debounce, /voice/cancel, server reconciliation

Server:
- New POST /api/voice/cancel: force-resets _recording, _current_session_id,
  empties recorder buffer if loaded. Idempotent — safe to call any time.
- /api/voice/status (and /api/agent/status) now include {recording,
  session_id} so the UI can reconcile against the server's truth.

Client:
- recBtn becomes a state machine (idle | starting | recording | stopping |
  error). Disabled during transitions; no more concurrent /start requests.
- Loading overlay during 'starting' (mostly hidden after F2 makes startup
  eager, but kept as a fallback for slow first-runs).
- pollStatus() reconciles client state from server.voice — if they differ,
  client adopts server truth. "Force reset" link appears on desync; clicks
  /voice/cancel.
- Press-hold mic gets the same treatment (debounce + cancel-on-leave +
  state-machine).

This kills the entire class of "stuck recording" bugs Sudheer hit on first
test (3 sessions opened, 0 closed, 0 thoughts captured).

[Stability Sprint — F1 of 5]
```

---

## F2 — Eager voice load at server boot

### Goal
Whisper and Silero VAD models load during server startup, not on first record click.
Trade-off: server takes ~30-60s longer to come up; first record is instant.

### Files to modify
- `services/voice/__init__.py` — add `async preload()` method that runs
  `_ensure_loaded()` on a thread (it's blocking).
- `interface/api/main.py` — in lifespan, after Ollama health check, call
  `await get_voice_service().preload()` if `settings.eager_voice_load` is True.
- `config/settings.py` — add `eager_voice_load: bool = True` (default ON),
  alias `SID_EAGER_VOICE_LOAD`.

### Behavior
- Server boot adds ~30s the first time (Silero VAD download + Whisper model load).
- Subsequent boots are fast — both models are cached on disk.
- If `SID_EAGER_VOICE_LOAD=false`, fallback to current lazy behavior.
- The lifespan log clearly says "Loading voice models (Silero VAD + Whisper
  base.en)... done in Xs."

### Acceptance
- [ ] First server start: 30-60s slower than before, log shows VAD + Whisper load.
- [ ] First click on RECORD: instant, transcript captured within 2s of stop.
- [ ] `SID_EAGER_VOICE_LOAD=false` restores old lazy behavior (load on first click).
- [ ] If eager load fails (network down for VAD download), server still starts
      and falls back to lazy on first click — eager is best-effort.

### Commit message
```
F2: eager-load voice models at server boot (default ON)

services/voice/__init__.py: VoiceService.preload() runs _ensure_loaded() in
a thread. Idempotent — safe to call multiple times.

interface/api/main.py lifespan: after Ollama health check, runs preload()
if settings.eager_voice_load. Logs "Loading voice models..." and timing.
Failure is non-fatal — falls back to lazy load on first click, the model
gets cached for next boot.

config/settings.py: SID_EAGER_VOICE_LOAD=true by default. Set to false to
revert to lazy behavior (faster boot, slower first record).

Trade-off: server boot is now 30-60s on first run (Silero VAD downloads
1.8MB from GitHub + Whisper base.en loads ~74MB from HF cache). Subsequent
boots are normal speed (both cached on disk). First record is instant.

[Stability Sprint — F2 of 5]
```

---

## F3 — Mic device probe + clear errors

### Goal
On first record start (and on server boot if eager load is on), probe sounddevice
for input devices. Log device name, sample rate, channels. If no input device or
permission denied, surface a clear error to the UI.

### Files to modify
- `services/voice/recorder.py` — add `probe_device()` method that runs
  `sounddevice.query_devices()` and returns the chosen input device dict.
  Log device name + sample rate.
- `services/voice/__init__.py` — `preload()` (from F2) also calls `probe_device()`
  and stores result on the service.
- `interface/api/routes/voice.py` — `/api/voice/start` returns 503 with a clear
  error message if probe found no input device.

### Acceptance
- [ ] First server boot logs: "Audio input device: 'MacBook Air Microphone'
      (16000 Hz, 1 channel)" or similar.
- [ ] Disabling mic permission for Terminal/Python in macOS Settings → first
      record returns 503 with message "No microphone access. Grant permission
      in System Settings → Privacy → Microphone."
- [ ] Headphones plugged in → input device picks up new default automatically.

### Commit message
```
F3: mic device probe + clear permission error path

services/voice/recorder.py: probe_device() runs sounddevice.query_devices()
and identifies the active input device. Returns dict with name, sample_rate,
channels. Logs at INFO on success.

services/voice/__init__.py: preload() now calls probe_device() and caches
the result. Failures during probe are caught and logged; preload doesn't
abort.

interface/api/routes/voice.py: /voice/start returns 503 with a clear error
message if probe fails or returns None ("No microphone access. Grant
permission in System Settings → Privacy → Microphone").

Diagnoses Bug #3: silent mic permission failures. Surfaces audio device
selection so headphones-plugged-in is visible.

[Stability Sprint — F3 of 5]
```

---

## F4 — Structured logging to `~/.sid/sid.log`

### Goal
Every state transition is observable. `tail -f ~/.sid/sid.log` shows:
- HTTP requests (existing)
- Voice route state transitions
- Pipeline node enter/exit with timing
- Watcher events (file detected, ingested, archived, flagged)
- Errors with traceback (currently swallowed)

### Files to modify / create
- `config/settings.py` — `log_path: Path = Path.home() / ".sid" / "sid.log"`
  derived property; `log_level: str = Field(default="INFO", alias="SID_LOG_LEVEL")`.
- `interface/api/main.py` — at the top of lifespan, configure the root logger
  to write to `~/.sid/sid.log` with rotation at 10MB (keep 3 generations).
  Format: `%(asctime)s %(levelname)-5s %(name)-30s %(message)s`. uvicorn
  access log routes to the same file.
- `interface/api/routes/voice.py` — log every state transition: start request,
  start success/failure, stop request, stop success/failure, cancel request,
  reply request. Format: `voice.transition recording=True session=abc123 op=start`.
- `services/processing/pipeline/graph.py` and each pipeline node — log
  entry/exit with chunk_id and duration: `pipeline.node.fast_classify
  chunk=abc123 duration_ms=2300 ok=True`.
- `services/document_agent/watcher.py` — log every file event:
  `watcher.detected path=~/SID/inbox/foo.txt`, `watcher.ingested
  thought_id=abc123 chunks=2`, `watcher.archived from=... to=...`,
  `watcher.flagged path=... reason=...`.

### Acceptance
- [ ] `tail -f ~/.sid/sid.log` shows live entries from all subsystems.
- [ ] `SID_LOG_LEVEL=DEBUG` reveals more granular events.
- [ ] Log file rotates at 10MB; old files renamed `sid.log.1`, `sid.log.2`, `sid.log.3`.
- [ ] `~/.sid/sid.log` exists and is the *primary* log destination (no more `/tmp/sid.log`
      from manual launches; the future S5.3 launcher will respect this path).
- [ ] After a recording session: log shows /voice/start → preload (already done) →
      recorder.start → /voice/stop → recorder.stop → vad.trim → whisper.transcribe →
      memory.save_raw_chunk → queue.enqueue → all 5 pipeline nodes → memory.update_thought.

### Commit message
```
F4: structured logging — every state transition observable in ~/.sid/sid.log

config/settings.py: log_path = ~/.sid/sid.log (derived); SID_LOG_LEVEL
(default INFO).

interface/api/main.py: lifespan configures root logger with rotating file
handler (10MB, 3 generations) writing to ~/.sid/sid.log. uvicorn access
log piggybacks on the same handler. Format includes timestamp, level,
logger name (component), message.

Voice route: explicit log lines for every transition (start req, start ok,
stop req, stop ok, cancel, reply, errors). State variables included so
desyncs are diagnosable from logs alone.

Pipeline nodes: log entry/exit with chunk_id and duration_ms. Failures
log full traceback (was previously swallowed at debug level).

Document watcher: log every file event — detected, ingested, archived,
flagged, with paths and chunk counts.

After this commit, "tail -f ~/.sid/sid.log" is the single observability
pane. Sprint 5 launcher will rotate this file; menubar will surface
log location via "Show logs" menu item.

[Stability Sprint — F4 of 5]
```

---

## F5 — Auto-extract chat + `save_thought` tool + Save button

### Goal
Every meaningful chat user message and voice reply auto-feeds the pipeline.
Chat is no longer a passive retrieval surface — it's a continuous-capture surface.

### Behavior contract
- When `POST /api/agent/chat` receives a user message, BEFORE running the agent:
  1. Run Stage 1 classification on the user's message.
  2. If `type == 'random'` → skip extraction; chat proceeds normally.
  3. If `type == 'question'` AND `confidence < 0.5` → skip (pure retrieval).
  4. Otherwise → save as Thought with `source='chat'`, enqueue with PRIORITY_DOCUMENT
     (lower priority than voice so chat capture doesn't starve real captures).
- Same logic for `POST /api/voice/reply` — the transcribed reply gets the
  same auto-extract treatment, with `source='voice_reply'`.
- The chat agent gets a new tool: `save_thought(content, type)` for
  agent-initiated capture (e.g. user says "I keep procrastinating", agent
  decides this should be remembered as a `reflection`).
- The UI gets a "Save as thought" button on each user chat message bubble.
  Click → forces pipeline run regardless of Stage 1 type. Useful when the
  Stage 1 classifier dropped something the user wanted captured.

### Files to modify
- `services/agent/chat_agent.py`
  - Add `_tool_save_thought(content, thought_type)` — creates a Thought row
    with `source='chat_explicit'`, runs through writer node directly (skipping
    Stage 1, the agent already classified).
  - Add `save_thought` to `_TOOLS` and `_TOOL_SCHEMAS`.
  - Update `_SYSTEM` prompt to mention the tool.
- `interface/api/routes/agent.py`
  - Wrap the existing `/chat` handler: BEFORE calling `agent_chat`, run a
    helper `auto_extract_user_message(message, source='chat')` that performs
    the Stage 1 + skip + save logic. Returns `{thought_id, type, captured}`
    metadata, attached to the chat response.
  - Same wrap on `/voice/reply` (in `interface/api/routes/voice.py`).
  - New endpoint `POST /api/thoughts/from-chat` for the explicit "Save"
    button: takes `{content, source}`, runs the pipeline, returns the
    saved Thought.
- `services/processing/__init__.py` — expose a helper
  `enqueue_text(text, source, priority=PRIORITY_DOCUMENT)` that creates a
  RawChunk with proper IDs and routes through normal flow.
- `shared/schemas/models.py` — `RawChunk` and `Thought` gain `source: str`
  ('voice', 'document', 'chat', 'voice_reply', 'chat_explicit').
- `services/memory/db.py` — migration: ALTER TABLE thoughts ADD COLUMN source TEXT.
- `interface/api/templates/index.html`
  - Each user chat message bubble gets a small "+ Save" button on hover;
    on click, POSTs to `/api/thoughts/from-chat` with the message text.
  - When the chat response includes `auto_captured: {thought_id, type}`,
    a small badge under the user bubble shows "Captured as <type>".

### Acceptance
- [ ] Type "I'm thinking about pivoting SmartPal to focus on B2B" in chat →
      Stage 1 classifies as `idea` → Thought saved → user bubble shows
      "Captured as idea" badge.
- [ ] Type "what tasks are pending" → Stage 1 classifies as `question` with
      low confidence → NO Thought saved → no badge.
- [ ] Press-hold mic, say "remember to email Aaron about the docs" → reply
      captured as task; runs through Stage 2 pipeline normally.
- [ ] Click "+ Save" on a user message that wasn't auto-captured → forces
      pipeline run; badge appears.
- [ ] Chat agent can fire `save_thought("X", "reflection")` mid-conversation
      via tool call. Recorded in `llm_calls` with `purpose=agent_chat` and
      `tools_used` includes `save_thought`.
- [ ] DB has `source` column populated correctly for each capture path.

### Commit message
```
F5: auto-extract chat + save_thought tool + Save button

This is the core "AI monitors every step" capability Sudheer asked for.
SID is no longer a passive retrieval interface — every meaningful chat
turn and voice reply auto-feeds the pipeline.

Behavior:
- POST /api/agent/chat: BEFORE running the agent, runs Stage 1 on the
  user message. If type='random' or (type='question' AND conf<0.5) →
  skip. Else → save as Thought (source='chat'), enqueue for Stage 2.
- POST /api/voice/reply: same auto-extract, source='voice_reply'.
- POST /api/thoughts/from-chat (NEW): explicit override — "+ Save"
  button on each user bubble, source='chat_explicit'.
- Chat agent gets a save_thought(content, type) tool — agent-initiated
  capture when the user says something worth remembering. Bypasses
  Stage 1 (the agent has already classified).

Files:
- services/agent/chat_agent.py: _tool_save_thought, _TOOLS,
  _TOOL_SCHEMAS, system prompt mentions the tool.
- interface/api/routes/agent.py: auto_extract_user_message() helper;
  /chat response now includes auto_captured metadata; new
  /api/thoughts/from-chat endpoint.
- interface/api/routes/voice.py: /voice/reply auto-extracts the
  transcript (source='voice_reply').
- services/processing/__init__.py: enqueue_text() helper for chat-
  origin captures.
- shared/schemas/models.py: RawChunk.source, Thought.source.
- services/memory/db.py: ALTER TABLE thoughts ADD COLUMN source TEXT.
- UI: +Save button on hover of user bubble; "Captured as <type>" badge
  when auto-extract fired.

Locked Critical Design Rule #11 in CLAUDE.md (auto-monitor by default).

[Stability Sprint — F5 of 5 — sprint complete]
```

---

## After Stability — Resume Sprint 5

Sprint 5 (Mac desktop) resumes with all Stability fixes in place. The vault
restructure (S5.1) inherits the new logging and watcher event coverage from F4.
The menubar (S5.2) inherits the auto-extract from F5 — typed messages from the
menubar's quick-chat (future S5.2.5) will also auto-capture.

---

## Open Questions / Blockers

(Append here when you hit something that needs Sudheer's input.)

- *(none currently)*

---

## Quick Sanity Commands

```bash
# Compile + import smoke (all platforms)
.venv/bin/python -m py_compile $(find services interface shared config main.py -name "*.py")

# Live tests (Mac with Ollama)
.venv/bin/python main.py
tail -f ~/.sid/sid.log    # after F4

# Test recording lifecycle (after F1)
curl -X POST http://localhost:8765/api/voice/start
curl -X POST http://localhost:8765/api/voice/cancel
curl http://localhost:8765/api/agent/status | jq .voice

# Test auto-extract (after F5)
curl -X POST http://localhost:8765/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to ship a v2 of the menubar by Friday"}' | jq .auto_captured
# Should show {captured: true, type: "task" or "idea", thought_id: "..."}
```
