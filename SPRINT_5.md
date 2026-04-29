# SID — Sprint 5
## Mac Desktop App + File Vault — Hand-off Contract

**Purpose of this doc:** Any agent (Claude session, Gemini, future me) can pick up
Sprint 5 from any task boundary without losing context. Mirrors the structure of
`BRAIN_SPRINT.md`. Each task is self-contained: stated goal, exact files, contract,
acceptance check, commit message template.

**Last updated:** 2026-04-28 by main-instance Claude on Sudheer's MacBook.
**Branch:** `main` (single source of truth — stale branches deleted earlier).
**HEAD at sprint start:** `d77d300` (B5 of Brain Sprint A).
**Lead:** main-instance Claude (Sudheer's local Mac). Container Claudes follow this doc.

---

## Why Sprint 5 Is Now (and not Brain Sprint B)

Brain Sprint B (proactive surfacing, critique→checkin, memory consolidation)
*needs real data*. ~2 weeks of captures. Right now Sudheer has run end-to-end
once and verified the pipeline works. The next blocker isn't intelligence —
it's **product feel**:

- Running `python main.py` in a terminal doesn't feel like a daily tool.
- A menubar app does.
- A single drop folder he can browse in Finder does.
- An always-visible status pill that shows "ok / processing / stuck" does.

Sprint 5 is the bridge between "the assistant works" and "the assistant lives
on my Mac." It is the precondition for actually accumulating the real data
Brain Sprint B needs.

---

## Operating Rules for Agents

1. **One commit per task (S5.1 → S5.5).** Push after each commit.
2. **Pull `origin/main` before starting any task.** Never branch off stale state.
3. **Update this doc** when finishing a task: tick the checkbox, write the commit
   SHA next to it, note any deviations from the plan.
4. **If blocked**, append the blocker to "Open questions / blockers" at the bottom
   and stop. Do not invent answers.
5. **Container-side agents**: this file IS your context. The Mac-side lead has full
   environment access; you don't. Run static checks (compile, YAML parse, Pydantic
   validate) but don't try to run rumps or sounddevice in your container.
6. **Do not break Rule #1 of the project**: every LLM call goes through
   `services/llm_gateway/gateway.py`.
7. **Do not move files in `~/SID/` or `~/.sid/` from code without writing a
   migration step in `setup.sh`.** Users may already have data.

---

## Locked Decisions (Sudheer 2026-04-28)

These are final for this sprint. Do not redebate.

| # | Decision | Rationale |
|---|---|---|
| 1 | **Vault at `~/SID/`**, NOT `~/Documents/SID/` | Avoid iCloud sync conflicts with file watcher; clear "this is SID's territory" |
| 2 | **Notes re-watched on edit** | Matches Obsidian behavior; user expects living documents |
| 3 | **Auto-archive to `~/SID/processed/YYYY-MM-DD/`** | Keeps inbox clean; archive recoverable by date |
| 4 | **"Open SID" menu item launches default browser** to `http://127.0.0.1:8765/` | Reuse polished web UI; no PyWebView yet |
| 5 | **Manual launch only** for V1 (no launchd / auto-start) | Trust the daemon manually first; promote to auto later |
| 6 | **FastAPI server is internal plumbing.** Menubar is the user surface. | Port is implementation detail; user shouldn't see it |

---

## Storage Layout (this is what S5.1 builds)

```
~/SID/                          ← VISIBLE vault. Browsable in Finder.
├── README.txt                  ← explains the layout (created by setup.sh)
├── inbox/                      ← single drop point. Anything here gets ingested.
│   └── .keep
├── notes/                      ← persistent text/markdown. Re-watched on edit.
│   └── .keep
├── processed/                  ← auto-archived after successful ingest
│   └── 2026-04-28/             ← (date dirs created on first archive of that day)
├── flagged/                    ← parse failures
│   └── (failed-file.pdf + failed-file.pdf.reason)
└── exports/                    ← daily journal exports, weekly review files
    └── .keep

~/.sid/                         ← HIDDEN internal data
├── sid.db                      ← SQLite (WAL mode)
├── vectors/                    ← LanceDB
├── agent_state.json            ← FSM persistence
├── sid.log                     ← Server log (rolled by launcher)
└── audio_cache/                ← (future) raw audio backups
```

---

## Sprint 5 — Task Index

| ID | Title | Status | Commit |
|---|---|---|---|
| S5.1 | Vault restructure (~/SID/ tree + watcher refactor) | pending | — |
| S5.2 | rumps menubar app | pending | — |
| S5.3 | Launcher + lifecycle (run.sh / run.command) | pending | — |
| S5.4 | setup.sh wizard | pending | — |
| S5.5 | SETUP.md + CLAUDE.md polish | pending | — |

When a task is complete, change `pending` to the commit SHA and tick all
acceptance checkboxes in that task.

---

## S5.1 — Vault restructure

### Goal
Move from the existing single-folder `~/Documents/SID/` to the locked layout:
`~/SID/{inbox,notes,processed,flagged,exports}` plus internal `~/.sid/`.

The document watcher must:
- Watch `inbox/` (any file → ingest → move to `processed/YYYY-MM-DD/`)
- Watch `notes/` (file create OR edit → ingest; on edit, replace the existing
  Thought row keyed by file path hash, NOT create a duplicate)
- On parse failure: move file to `flagged/` and write `<name>.reason` next to it
- Migrate any existing `~/Documents/SID/` content into `~/SID/inbox/` on first
  startup, with a one-time log message

### Files to modify
- `services/document_agent/watcher.py` — multi-folder watch, archive-on-success,
  flag-on-failure, edit-detection on notes/
- `services/document_agent/extractor.py` — return structured result `{ok, text, error}`
  so watcher can route to processed vs flagged
- `config/settings.py` — add `vault_root: Path = Path.home() / "SID"`,
  derived properties `inbox_dir`, `notes_dir`, `processed_dir`, `flagged_dir`,
  `exports_dir`. Remove any reference to `~/Documents/SID/`.
- `services/memory/store.py` — extend `save_raw_chunk` (or add `upsert_thought_by_source`)
  to support replace-on-edit for notes (key by `source_path` if provided).
  Schema migration: add `source_path TEXT` column to `thoughts`.
- `services/memory/db.py` — add the `source_path` migration to `_MIGRATIONS`
- `services/memory/schema.sql` — add `idx_thoughts_source` index
- `shared/schemas/models.py` — Thought gains `source_path: Optional[str] = None`;
  RawChunk gains optional `source_path` for the document agent path

### Behavior contract
```python
# Watcher startup:
1. Ensure all vault dirs exist (mkdir -p)
2. If ~/Documents/SID/ has any files, move them to ~/SID/inbox/ + log "migrated N files"
3. Start observers on inbox/ and notes/ (single Observer with two handlers OK)
4. On startup, process any leftover files in inbox/ (catch-up after restart)

# Inbox event (file created):
1. Try extractor.extract_chunks(path)
2. If success → for each chunk: save_raw_chunk + enqueue with PRIORITY_DOCUMENT
3. After ALL chunks succeed → move file to ~/SID/processed/<today>/
4. If failure → move file to ~/SID/flagged/, write <name>.reason with traceback summary

# Notes event (file created OR modified):
1. extract_chunks(path)
2. For each chunk: upsert by source_path — replace if existing thought has same source_path
3. NOTE: do NOT auto-archive notes. They stay in notes/ as the user's vault.
4. On failure: log warning but DO NOT move (notes are precious)
```

### Acceptance
- [ ] Fresh start: `setup.sh` not yet built but manually `mkdir ~/SID/{inbox,notes,...}` works
- [ ] Drop a `.txt` in `~/SID/inbox/` → appears in timeline within 30s, file moves to
      `~/SID/processed/YYYY-MM-DD/<name>` after pipeline finishes
- [ ] Drop a `.txt` in `~/SID/notes/` → appears in timeline; **does not** move
- [ ] Edit the note → existing Thought row is updated (same `id`), new content reflected
- [ ] Drop a corrupt PDF in `inbox/` → moves to `flagged/`, sibling `.reason` file
      contains a one-line error
- [ ] Old `~/Documents/SID/` files (if any) get migrated into `~/SID/inbox/` on first start
- [ ] `services/memory/db.py` migration adds `source_path` column idempotently

### Commit message
```
S5.1: vault restructure — ~/SID/ visible tree + multi-folder watcher

config/settings.py: vault_root = ~/SID; inbox_dir, notes_dir, processed_dir,
flagged_dir, exports_dir as derived properties. Removed all references to
~/Documents/SID/.

services/document_agent/watcher.py: dual-handler observer for inbox/ and
notes/. Inbox events trigger ingest + auto-archive to processed/<today>/.
Notes events use upsert-by-source_path so editing a note replaces its row
instead of duplicating. Parse failures move to flagged/ with sibling
.reason file. On startup, catches up on leftover inbox/ files and migrates
~/Documents/SID/ contents into inbox/.

services/document_agent/extractor.py: returns {ok, chunks, error} so
watcher can route success/failure cleanly.

services/memory/store.py: upsert_thought_by_source() — keyed by source_path
column. save_raw_chunk now accepts optional source_path.

services/memory/db.py: ALTER TABLE thoughts ADD COLUMN source_path TEXT
(idempotent via existing migration runner).

services/memory/schema.sql: idx_thoughts_source for fast lookup.

shared/schemas/models.py: Thought.source_path, RawChunk.source_path.

[Sprint 5 — S5.1 of 5]
```

---

## S5.2 — rumps menubar app

### Goal
Always-visible menubar app. Click → menu of actions. Status icon reflects FSM
state. Talks to the FastAPI server via httpx; never imports services directly.

### Files to create
- `interface/desktop/menubar.py` — main rumps app
- `interface/desktop/__init__.py` — already exists; export `run_menubar()`

### Files to modify
- `requirements.txt` — uncomment `rumps>=0.4.0` (it's already commented in)

### Menu structure
```
SID  ●                                              ← icon shows state (●idle ◉rec ◔proc ✗down)
─────────────────────────
Status: idle  |  ollama: ok                          ← updates every 3s
Queue: 0  |  Pending tasks: 11                       ← from /api/agent/status + /api/agent/tasks
─────────────────────────
🔴 Start recording                                   ← toggles via /api/voice/start + /stop
─────────────────────────
Open SID (web UI)                                    ← opens http://127.0.0.1:8765 in default browser
Open vault (~/SID/)                                  ← opens Finder via subprocess `open ~/SID/`
─────────────────────────
Trigger morning brief                                ← POST /api/agent/morning
Trigger evening reflection                           ← POST /api/agent/evening
Trigger weekly review                                ← POST /api/agent/weekly
─────────────────────────
Suppress check-ins
  ├── 1 hour
  ├── 4 hours
  └── 8 hours
─────────────────────────
Quit SID                                             ← graceful shutdown (kills server subprocess)
```

### Implementation notes
- rumps app uses `@rumps.timer(3)` decorator for the 3-second status poll
- Icon uses unicode glyphs in title (rumps doesn't have great native icon support
  on all macOS versions; glyphs are reliable). Title format: `"SID ●"`
- All HTTP calls via httpx with 5s timeout; failures show in title as `"SID ✗"`
  and a popup notification once per failure burst (don't spam).
- "Start recording" toggle stores `_recording_session_id` on first click;
  second click POSTs /stop with that id. If user quits mid-recording, /stop fires.
- Routine triggers (morning/evening/weekly) fire-and-forget; show macOS
  notification when response returns: "Morning brief ready — open SID to view."
- Quit must SIGTERM the FastAPI subprocess (managed by launcher, not menubar
  itself — see S5.3). Menubar just calls launcher's shutdown signal.

### Acceptance
- [ ] `rumps` installed; `python -m interface.desktop.menubar` starts the menubar
- [ ] Icon visible in top-right of macOS menu bar
- [ ] Menu opens; status row updates every 3s with live values
- [ ] "Open SID" launches default browser to localhost:8765
- [ ] "Open vault" opens `~/SID/` in Finder
- [ ] "Start recording" → 5s of speech → "Stop recording" → transcript appears in timeline
- [ ] "Trigger morning brief" returns within 30s; macOS notification fires when ready
- [ ] When Ollama is stopped, icon flips to `✗` within 60s
- [ ] "Quit SID" cleanly stops both menubar and FastAPI server (via launcher signal)

### Commit message
```
S5.2: rumps menubar app — always-visible interface for SID

interface/desktop/menubar.py: rumps app with status row, action menu, and
3-second poll of /api/agent/status + /api/agent/tasks. Icon reflects FSM
state (● idle, ◉ recording, ◔ processing, ✗ ollama down).

Menu actions:
- Start/stop recording (toggles via /api/voice/start + /stop)
- Open SID web UI (default browser → localhost:8765)
- Open vault (~/SID/ in Finder)
- Trigger morning brief / evening reflection / weekly review (fire-and-forget,
  notifies on completion)
- Suppress check-ins (1h / 4h / 8h)
- Quit (signals launcher to stop server, then exits)

All HTTP via httpx with 5s timeouts; transient failures don't spam.
Recording toggle holds session id between start and stop calls.
Routine triggers post a macOS notification when response returns.

requirements.txt: rumps>=0.4.0 uncommented.

[Sprint 5 — S5.2 of 5]
```

---

## S5.3 — Launcher + server lifecycle

### Goal
One command starts the whole stack. `run.command` is double-clickable from Finder.
The launcher manages the FastAPI server as a subprocess; quitting the menubar
kills the server cleanly.

### Files to create
- `run.sh` — bash launcher (terminal use)
- `run.command` — wrapper that opens Terminal.app and runs `run.sh`
  (this is the Finder-double-clickable file)
- `interface/desktop/launcher.py` — Python module that:
  - Spawns uvicorn as subprocess
  - Waits for `/api/agent/status` to respond (up to 30s)
  - Starts the rumps menubar
  - On menubar quit → SIGTERM the uvicorn subprocess + wait for exit
  - Logs to `~/.sid/sid.log` (rotated to `sid.log.1` if >10MB)

### run.sh contract
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

# 1. Check Python venv exists; if not, run setup.sh
[ -d ".venv" ] || ./setup.sh

# 2. Check Ollama is running; print friendly error if not
curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null \
  || { echo "Ollama is not running. Start Ollama.app and try again."; exit 1; }

# 3. Launch the lifecycle manager (which boots server + menubar)
exec .venv/bin/python -m interface.desktop.launcher
```

### Acceptance
- [ ] `./run.sh` starts both server and menubar from a clean checkout (with
      venv already built)
- [ ] Double-clicking `run.command` in Finder opens Terminal and starts SID
- [ ] FastAPI server logs end up in `~/.sid/sid.log`
- [ ] Quitting menubar (Quit menu item) cleanly shuts down the server within 5s
- [ ] If server fails to come up in 30s, launcher prints error and exits
- [ ] `tail -f ~/.sid/sid.log` shows live request log

### Commit message
```
S5.3: launcher — run.sh + run.command + lifecycle manager

run.sh: bash entry point. Checks .venv, checks Ollama is running, then
exec's interface.desktop.launcher.

run.command: Finder-friendly wrapper that opens Terminal.app and runs
run.sh. Double-clickable.

interface/desktop/launcher.py: Python module that spawns uvicorn as a
subprocess, waits for /api/agent/status to return 200 (30s timeout),
then boots the rumps menubar. On menubar quit, SIGTERMs the server,
waits up to 5s for graceful exit, then SIGKILL if needed.

Server logs go to ~/.sid/sid.log; rotated to sid.log.1 when >10MB.

[Sprint 5 — S5.3 of 5]
```

---

## S5.4 — setup.sh wizard

### Goal
Idempotent first-run wizard. Checks Python, builds venv, installs deps, checks
Ollama, offers to pull missing models, creates vault directories with README.

### Files to create
- `setup.sh` — bash wizard

### Behavior contract
```bash
# Steps (each can be re-run safely):
1. Verify python3.11+ on PATH (try python3.11, python3, python in order)
2. Build .venv if missing (using best Python found)
3. pip install -r requirements.txt (skip if already up-to-date)
4. Check Ollama running; if not, prompt user to start Ollama.app
5. Check models in models.yaml are present; offer to `ollama pull` missing ones
6. Create ~/SID/{inbox,notes,processed,flagged,exports} (mkdir -p)
7. Create ~/SID/README.txt with the vault layout explanation
8. Create ~/.sid/ (mkdir -p) — DB will be created on first server start
9. Copy .env.example → .env if .env doesn't exist
10. Print "you're ready: double-click run.command"
```

### Acceptance
- [ ] `./setup.sh` from a fresh clone (no venv, no ~/SID, no .env) leaves the
      system fully ready to run
- [ ] Re-running `./setup.sh` is a no-op (idempotent)
- [ ] If Ollama is missing, prints clear instructions to install and re-run
- [ ] Models are pulled with progress bars (uses `ollama pull` directly)

### Commit message
```
S5.4: setup.sh — idempotent first-run wizard

Checks Python 3.11+, builds .venv, installs requirements.txt, verifies
Ollama is running, offers to ollama-pull any missing models from
models.yaml, creates ~/SID/{inbox,notes,processed,flagged,exports}
with README, creates ~/.sid/, copies .env.example → .env if missing.

Each step is idempotent — re-running is safe and prints "already done"
where applicable.

[Sprint 5 — S5.4 of 5]
```

---

## S5.5 — SETUP.md + CLAUDE.md polish

### Goal
A user-facing SETUP.md (30-second quickstart) and a final pass over CLAUDE.md
to reflect Sprint 5 completion.

### Files to create
- `SETUP.md` — 30-second quickstart for a new machine

### Files to modify
- `CLAUDE.md` — flip Sprint 5 from "Active" to "Complete", note the run command
- `BRAIN_SPRINT.md` — point readers to SPRINT_5.md (so the doc trail is linear)

### SETUP.md content (rough)
```markdown
# SID — 30-Second Setup

## Prerequisites
- macOS (Apple Silicon recommended)
- Python 3.11+
- Ollama installed and running

## Install
1. Clone the repo
2. `./setup.sh` — installs deps, pulls models, creates ~/SID/ vault
3. Double-click `run.command` (or `./run.sh` in terminal)

That's it. SID lives in your menubar.

## Daily Use
- Drop files into `~/SID/inbox/` — they get ingested and archived to processed/
- Drop notes into `~/SID/notes/` — re-watched on edit, like Obsidian
- Click menubar → "Start recording" to capture a thought by voice
- Click menubar → "Open SID" to chat / view timeline / mark tasks done
```

### Acceptance
- [ ] Fresh-machine simulation: with only the repo and Python+Ollama installed,
      following SETUP.md gets to a working menubar in under 5 minutes
- [ ] CLAUDE.md "Sprint 5" status reflects all 5 commits
- [ ] BRAIN_SPRINT.md mentions Sprint 5 came after, so doc order matches commit order

### Commit message
```
S5.5: SETUP.md + CLAUDE.md polish — Sprint 5 complete

SETUP.md: 30-second quickstart for new machines. Two commands
(setup.sh + run.command) get a user from clone → menubar.

CLAUDE.md: Sprint 5 marked complete with all 5 commit SHAs. Storage
Layout section reflects final shipping state.

BRAIN_SPRINT.md: cross-link to SPRINT_5.md so docs flow chronologically.

Sprint 5 is done. Next up: 2 weeks of real captures, then Brain Sprint B
(proactive surfacing, critique→checkin coupling, memory consolidation).

[Sprint 5 — S5.5 of 5 — sprint complete]
```

---

## After Sprint 5 — What's Next

**Brain Sprint B** (needs ~2 weeks of real data first):
- B4 — Proactive surfacing in chat
- B6 — Critique → check-in coupling
- B7 — Memory consolidation

**Sprint 4** (test harness + dev mode — also unfinished):
- pytest with mock gateway
- SID_DEV_MODE flag for UI iteration without Ollama

**Beyond:**
- Android port (same FastAPI backend, new mobile shell)
- launchd auto-start (after Sprint 5 stability proves out)
- PyWebView upgrade (replace browser tab with native window)

---

## Open Questions / Blockers

(Append here when you hit something that needs Sudheer's input.)

- *(none currently)*

---

## Quick Sanity Commands for Any Agent

```bash
# Check sprint state
git log --oneline -10
cat SPRINT_5.md | grep -E "^\| S5\." | head -10

# Smoke tests (Linux/Mac, no Ollama needed)
.venv/bin/python -m py_compile $(find services interface shared config main.py -name "*.py")
.venv/bin/python -c "import yaml; yaml.safe_load(open('config/models.yaml'))"

# Live test (Mac + Ollama running)
./run.sh   # starts everything; menubar shows up; ~/.sid/sid.log is the server log
```
