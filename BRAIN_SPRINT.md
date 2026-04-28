# SID — Brain Sprint A
## Hand-off Contract for Multi-Agent Continuation

**Purpose of this doc:** Any agent (Claude session, Gemini, future me) can pick up
Brain Sprint A from any task boundary without losing context. Each task below is
self-contained: stated goal, exact files to touch, schema changes if any, contract
for the API, acceptance check, and the commit message template.

**Last updated:** 2026-04-28 by main-instance Claude on Sudheer's MacBook.
**Branch in use:** `main` (single source of truth — stale branches deleted).
**Repo HEAD at start of Brain Sprint A:** `8e53ce5` (Sprint 3 complete).

---

## Operating Rules for Agents

1. **One commit per task (B1, B2, B3, B5).** Push after each commit.
2. **Pull `origin/main` before starting any task.** Never branch off stale state.
3. **Update this doc** when finishing a task: tick the checkbox, write the commit
   SHA next to it, note any deviations from the plan.
4. **If blocked**, write the blocker into the "Open questions / blockers" section
   at the bottom and stop. Do not invent answers.
5. **Container-side agents** (other Claudes) should treat this file as the
   source of truth — they cannot see the local Mac state. Use the HEAD SHA
   listed in commit history as the synchronization point.
6. **Do not break Rule #1 of the project**: every LLM call goes through
   `services/llm_gateway/gateway.py`. New routines must use
   `gateway.generate(purpose, ...)` or `gateway.chat_for(purpose, ...)`.
7. **Do not modify** `shared/schemas/models.py` without also updating the SQLite
   migration runner in `services/memory/db.py` if the change touches a DB-mirroring
   model. Schema and Pydantic are co-versioned.

---

## Sprint 3 Acceptance — Verify Before Each Task

These items can only be checked on Sudheer's Mac with Ollama running. The current
agent (main instance) has done static verification. The first time `python main.py`
is run, walk this checklist:

- [ ] `python main.py` boots without import errors
- [ ] `GET http://127.0.0.1:8765/api/agent/status` returns 200 with `ollama: {healthy: true, ...}`
- [ ] `GET /api/stats` returns valid `StatsResult`
- [ ] Drop a `.txt` file in `~/Documents/SID/` → appears in `/api/thoughts/timeline?date=YYYY-MM-DD` within ~30s
- [ ] Hit RECORD button in UI → 5s of speech → transcript appears in timeline
- [ ] Mark a task done from UI → `extractions.status` flips to `done`, `completed_at` set
- [ ] Send a chat message → response visible; `llm_calls` table has a new `agent_chat` row
- [ ] Stop Ollama (`ollama stop`) → wait 60s → header pill flips to `down` then `stuck`
- [ ] (Cloud fallback only — requires `ANTHROPIC_API_KEY` and editing models.yaml fallback.enabled to true) Repeat above with cloud fallback wired

---

## Brain Sprint A — Task Index

| ID | Title | Status | Commit |
|---|---|---|---|
| B1 | Milestone routine + endpoint + UI | pending | — |
| B2 | Task closure flow + closure prompt UI | pending | — |
| B3 | Interrogation enforcement in chat_agent | pending | — |
| B5 | Press-hold reply routing | pending | — |

When a task is complete, change `pending` to the commit SHA and tick the relevant
checkboxes inside that task.

---

## B1 — Milestone routine

### Goal
Turn a vague extracted task into 2–7 concrete milestones via conversation.
Milestones are stored as `Extractions` linked back to the parent via
`milestone_parent_id`. Used both from chat ("plan the X task") and from a
"Plan task" button on each pending task in the UI.

### Files to create
- `services/agent/routines/milestone.py`

### Files to modify
- `interface/api/routes/agent.py` — add `POST /api/agent/milestone`
- `services/memory/store.py` — add `get_milestones_for(parent_id)` query
- `interface/api/templates/index.html` — add "Plan" button next to each pending
  task; on click open a modal that streams the conversation; submit posts the
  user's reply and renders new milestones.
- `services/agent/chat_agent.py` — add `plan_task` tool that wraps
  `routines.milestone.generate_breakdown()` (so chat can trigger it too)

### Pydantic schema (in milestone.py — not a global model)
```python
class MilestoneStep(BaseModel):
    content: str
    priority: int = Field(ge=1, le=5, default=3)
    time_estimate_hours: Optional[float] = None
    next_step: Optional[str] = None  # the very first action

class MilestoneBreakdown(BaseModel):
    steps: List[MilestoneStep] = Field(min_length=2, max_length=7)
    rationale: str = Field(description="One paragraph: how these steps cover the task")
```

### Routine contract
```python
async def generate_breakdown(parent_task: Extraction, user_context: str = "") -> MilestoneBreakdown:
    """
    parent_task: the existing Extraction with status='pending'
    user_context: optional free-text from user describing constraints / energy
                  (e.g. "I have 2 hours after work, I'm tired")
    Returns: MilestoneBreakdown — caller persists each step as a new
             Extraction with milestone_parent_id = parent_task.id.

    Uses gateway.generate("milestone", prompt, MilestoneBreakdown).
    Prompt includes parent task content, parent priority, any existing
    milestones on the same parent (so re-running adds without duplicating),
    plus user_context.
    """
```

### Endpoint contract
```
POST /api/agent/milestone
Body: { "task_id": "<extraction_id>", "context": "<optional user text>" }
Response: {
  "parent_id": str,
  "breakdown": <MilestoneBreakdown>,
  "saved_milestones": [<Extraction>, ...]   // already persisted with milestone_parent_id
}
Errors: 404 if task_id not in extractions; 409 if task already 'done'
```

### Acceptance
- [ ] `POST /api/agent/milestone` with a valid pending task id returns 2–7 saved
      milestones; each new row has `milestone_parent_id = parent_id` and
      `thought_id = parent.thought_id`.
- [ ] Re-calling for the same task does NOT duplicate steps (prompt sees existing
      ones in context).
- [ ] UI "Plan" button on a pending task opens modal, sends request, renders
      child milestones indented under the parent.
- [ ] `gateway.generate("milestone", ...)` route resolves to the
      `models.yaml.models.milestone` value (currently `qwen2.5:14b`).
- [ ] No new entries in `shared/schemas/models.py` (milestone schemas are local
      to the routine).

### Commit message
```
B1: milestone routine + endpoint + UI plan button

services/agent/routines/milestone.py — generate_breakdown() returns
MilestoneBreakdown via gateway.generate("milestone", ...). Prompt includes
parent task content, priority, existing milestones (no duplication on re-run),
optional user context.

POST /api/agent/milestone {task_id, context?} — fetches parent, calls
generate_breakdown, persists each step as Extraction with
milestone_parent_id=parent.id, thought_id=parent.thought_id.

UI: each pending task gains a "Plan" button → modal → renders saved
milestones indented under parent on success.

chat_agent: new plan_task tool wraps the routine for chat-driven planning.

store: get_milestones_for(parent_id) for UI rendering.

[Brain Sprint A — B1 of 4]
```

---

## B2 — Task closure flow

### Goal
When a task moves to `status='done'`, capture the *learning* signal: what was
learned, what went wrong, what would be done differently, was negligence
involved. Persist to `task_closures` table (already exists per Phase 4).

### Files to modify
- `interface/api/templates/index.html` — when checkbox toggles a task to done,
  open a closure modal (textarea fields + checkbox for negligence). Submit
  posts to a new endpoint.
- `interface/api/routes/agent.py` — add `POST /api/agent/closure`
- `services/memory/store.py` — confirm `save_task_closure()` exists and
  matches the contract below; add `get_closure_for(extraction_id)`.

### Endpoint contract
```
POST /api/agent/closure
Body: {
  "extraction_id": "<id>",
  "learning": "<text>",
  "what_went_wrong": "<text>",
  "would_do_differently": "<text>",
  "negligence_flagged": false,
  "energy_reflection": "<text, optional>"
}
Response: { "closure": <TaskClosure> }
Side effect:
  1. Writes a row to task_closures
  2. Sets extractions.closure_note to a short summary (first sentence of learning)
  3. Sets extractions.status = 'done' if not already
Errors: 404 if extraction_id missing; 400 if status already has a closure
```

### Acceptance
- [ ] Marking a task done in UI opens closure modal; cancelling reverts the
      checkbox.
- [ ] Submitting writes a row to `task_closures` AND updates `extractions`
      with `status='done'`, `completed_at` set, `closure_note` populated.
- [ ] `GET /api/agent/closure?extraction_id=<id>` returns the closure (helper
      for future review screens).
- [ ] Re-submitting a closure for an already-closed task returns 400.

### Commit message
```
B2: task closure flow — capture learning signal at task done

POST /api/agent/closure {extraction_id, learning, what_went_wrong,
would_do_differently, negligence_flagged, energy_reflection?} — writes
task_closures row, updates extractions (status=done, completed_at,
closure_note=first sentence of learning).

UI: marking a task done opens closure modal (5 fields). Cancel reverts
the checkbox; submit calls /api/agent/closure and re-renders task list.

store: get_closure_for(extraction_id) helper for review screens.

This is the core behavioral data input for the critique engine — every
closure adds a learning row that weekly review and critique can mine
for patterns.

[Brain Sprint A — B2 of 4]
```

---

## B3 — Interrogation enforcement in chat_agent

### Goal
The chat agent's system prompt today *says* "ask 5–6 clarifying questions before
answering" but there's no enforcement. Make it structural: track question count
per session, refuse to answer conclusively before threshold, soft-cap at 20.

### Files to modify
- `services/agent/chat_agent.py`
  - Add `_question_count: int` to the conversation state
  - Detect agent message type via a small classifier prompt (or simple
    heuristic: ends with `?` and is short → "question"; longer / no ? → "answer")
  - If `_question_count < SID_INTERROGATION_MIN_QUESTIONS` and message is
    "answer", inject a system reminder forcing another question
  - At `SID_INTERROGATION_MAX_QUESTIONS` (default 20), allow answer regardless
- `config/settings.py` — add `interrogation_min_questions: int = 5`,
  `interrogation_max_questions: int = 20`
- `interface/api/routes/agent.py` — `POST /api/agent/chat` response now
  includes `question_count` and `mode` (`"interrogating"` | `"answering"`)
- `interface/api/templates/index.html` — chat header shows
  `Questions asked: 3/5` while in interrogating mode; transitions to
  `Answering` once threshold met.

### Implementation note
The simplest enforcement: after each LLM turn, check the response text. If it
ends with `?` and word count < 40 → it's a question, increment counter. If
counter < min and the response isn't a question → add a system message
saying "Ask one more clarifying question before answering. You've asked
{n}/{min}. Sudheer asked you to interrogate first." and re-call.

### Acceptance
- [ ] First 5 exchanges with a fresh chat are all questions (no answers).
- [ ] Counter visible in UI; updates live.
- [ ] User can override with magic phrase "just answer" (caught in handler;
      sets counter to min) — this is intentional escape hatch.
- [ ] Counter resets when chat session ends (frontend clears history).
- [ ] No infinite loops: hard cap at min+3 forced re-prompts; if model still
      won't ask a question, accept its answer.

### Commit message
```
B3: chat_agent interrogation enforcement (5–20 questions before answering)

services/agent/chat_agent.py: tracks _question_count per session. After each
LLM turn classifies response as question vs answer (ends with ?, < 40 words).
If under SID_INTERROGATION_MIN_QUESTIONS (default 5), forces another
clarifying question via a re-prompt (capped at min+3 retries to avoid loops).
At SID_INTERROGATION_MAX_QUESTIONS (default 20) the gate opens regardless.

Magic phrase "just answer" overrides the gate intentionally.

POST /api/agent/chat response: { reply, question_count, mode }.

UI: chat header shows "Questions asked: N/min" when interrogating, "Answering"
once threshold met.

config/settings.py: interrogation_min_questions, interrogation_max_questions.

[Brain Sprint A — B3 of 4]
```

---

## B5 — Press-hold reply routing

### Goal
Today every recording becomes a new RawChunk. The locked spec says:
- **Tap** = new thought (current behavior)
- **Press-hold** = reply to active agent question (continues chat context,
  does NOT create a RawChunk in `thoughts`)

### Files to modify
- `interface/api/routes/voice.py`
  - New endpoint `POST /api/voice/reply` accepts the same audio payload as
    `/voice/stop` but routes the transcript into the active chat session
    instead of the processing queue.
- `services/agent/chat_agent.py`
  - Add `current_session_id: Optional[str]` global (or store-backed) so
    the reply endpoint knows where to inject.
  - `inject_user_reply(session_id, text)` appends to that session's history
    and triggers the next assistant turn.
- `services/agent/fsm.py`
  - New transition: `CHECK_IN → CAPTURING` is fine for the existing route;
    add `CHAT → CAPTURING(reply_mode=True)` semantically. Doesn't have to be
    a new state — a flag on the FSM is enough.
- `interface/api/templates/index.html`
  - Press-hold handler on the chat input area: while held, records audio,
    on release POSTs to `/api/voice/reply` with the active chat session id.
  - Visual: chat input shows "Recording reply..." while held.

### Endpoint contract
```
POST /api/voice/reply
Body: multipart audio + form field session_id (str)
Response: { "transcript": str, "chat_response": str }
Side effects:
  - Audio transcribed via VoiceService.transcribe_audio()
  - Transcript NOT saved to thoughts table (this is conversation, not memory)
  - Transcript appended to chat history for session_id
  - chat_agent runs one turn; response returned in same response body
Errors: 404 if no active chat session for that id; 503 if voice service busy
```

### Acceptance
- [ ] Press-hold on chat input records audio; release transcribes via
      Whisper.
- [ ] Transcript routes to chat_agent, NOT to `thoughts` table.
- [ ] Chat_agent response renders in the chat panel within 1–2 seconds of
      release.
- [ ] Tap on the main RECORD button still creates a new RawChunk (existing
      behavior unchanged).
- [ ] FSM never enters CAPTURING for a reply that's already in CHAT (no
      double-blocking).

### Commit message
```
B5: press-hold voice reply routes to chat, not memory

POST /api/voice/reply (multipart audio + session_id) — transcribes audio
via VoiceService.transcribe_audio() but routes the transcript into the
active chat session instead of saving to thoughts table. Returns
{ transcript, chat_response } so the UI can render both.

services/agent/chat_agent.py: tracks current_session_id (in-memory map);
inject_user_reply(session_id, text) appends to history and runs one turn.

services/agent/fsm.py: reply_mode flag on CAPTURING — doesn't block CHAT
state; ensures press-hold during agent question doesn't spawn new RawChunk.

UI: press-and-hold on chat input records (red "Recording reply..." pill);
release POSTs to /api/voice/reply with active session id; transcript and
agent response render in chat panel.

Tap on main RECORD button is unchanged — still creates a fresh RawChunk
via /voice/start + /voice/stop.

[Brain Sprint A — B5 of 4]
```

---

## After Brain Sprint A — Next Up

**Brain Sprint B** (needs ~2 weeks of real captures before tuning makes sense):

- B4 — Proactive surfacing in chat ("you've mentioned X 7 times, no progress")
- B6 — Critique → check-in coupling (negligence flags seed check-in questions)
- B7 — Memory consolidation (periodic re-relink as new thoughts arrive)

**Sprint 4** (test harness, dev mode, mock gateway — was deferred by previous Claude):
- pytest fixtures for in-memory SQLite + temp LanceDB + mock gateway
- Smoke tests for queue (priority, retry, crash recovery), store, chat agent
- `SID_DEV_MODE=true` env flag → use MockGateway → enables UI work without Ollama

**Sprint 5** (macOS surface — needs the Mac):
- rumps menubar, osascript notifications, escalating alarm via afplay

---

## Open Questions / Blockers

(Append here when you hit something that needs Sudheer's input.)

- *(none currently)*

---

## Quick Sanity Commands for Any Agent

```bash
# Verify you're on the right state
git log --oneline -5
git status                       # should be clean
git remote -v                    # should show origin

# Smoke tests (Linux/Mac, no Ollama needed)
/opt/homebrew/bin/python3.11 -m py_compile $(find services interface shared config main.py -name "*.py")
/opt/homebrew/bin/python3.11 -c "import yaml; yaml.safe_load(open('config/models.yaml'))"

# Live tests (needs Mac + Ollama running)
ollama serve &
python main.py
# In another terminal:
curl -s localhost:8765/api/agent/status | jq
curl -s localhost:8765/api/stats | jq
```
