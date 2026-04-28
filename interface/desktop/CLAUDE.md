# Interface: macOS Desktop (Menubar App)

## Purpose

Always-visible macOS menubar app. One-click to record. Shows agent notifications. Talks to FastAPI backend via HTTP.

**Build this LAST** (Phase 4). The FastAPI backend must work first.

## Files to Build

```
interface/desktop/
└── menubar.py           # rumps macOS menubar application
```

## Stack

- `rumps` — Python macOS menubar app framework
- `httpx` — sync HTTP client to call localhost:8765
- macOS native notifications via rumps

## Menubar Design

```
[SID icon] → click → dropdown menu:
  ● Record (push to hold)     [keyboard: Cmd+Shift+R]
  ─────────────────────
  📋 Today's timeline         → opens browser at localhost:8765
  🔍 Search memory...         → input dialog → opens results
  ─────────────────────
  🌅 Morning brief            → triggers POST /api/agent/morning
  🌙 Evening reflection       → triggers POST /api/agent/evening
  ─────────────────────
  ◉ Status: Idle              [shows current FSM state]
  📊 Stats                    → opens browser at localhost:8765/stats
  ─────────────────────
  Quit SID
```

## Status Icon Colors

- Grey circle: IDLE
- Red circle: RECORDING (flashing)
- Yellow circle: PROCESSING
- Blue circle: CHECK_IN / agent wants to speak

## Implementation

```python
import rumps
import httpx
import threading

API_BASE = "http://127.0.0.1:8765"

class SIDMenubar(rumps.App):
    def __init__(self):
        super().__init__(
            name="SID",
            icon="assets/icon_idle.png",  # 22x22 PNG for menubar
            quit_button="Quit SID"
        )
        self._recording = False
        self._session_id = None
        self._start_poll()  # Background status polling
    
    @rumps.clicked("Record")
    def toggle_record(self, sender):
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()
    
    def _start_recording(self):
        self._recording = True
        self.icon = "assets/icon_recording.png"
        resp = httpx.post(f"{API_BASE}/api/voice/start")
        self._session_id = resp.json()["session_id"]
    
    def _stop_recording(self):
        self._recording = False
        self.icon = "assets/icon_processing.png"
        resp = httpx.post(f"{API_BASE}/api/voice/stop", 
                         json={"session_id": self._session_id})
        chunk = resp.json()
        rumps.notification(
            title="SID captured",
            subtitle="",
            message=chunk["raw_text"][:80] + "..." if len(chunk["raw_text"]) > 80 else chunk["raw_text"]
        )
        self.icon = "assets/icon_idle.png"
    
    @rumps.clicked("Morning brief")
    def morning_brief(self, _):
        resp = httpx.post(f"{API_BASE}/api/agent/morning", timeout=30)
        brief = resp.json()["brief"]
        rumps.notification(title="☀️ Good morning, Sudheer", subtitle="", message=brief[:200])
    
    def _start_poll(self):
        """Poll API every 5 seconds for agent notifications."""
        def poll():
            while True:
                try:
                    resp = httpx.get(f"{API_BASE}/api/agent/status", timeout=2)
                    status = resp.json()
                    self._update_icon(status["state"])
                except Exception:
                    pass
                time.sleep(5)
        threading.Thread(target=poll, daemon=True).start()
    
    def _update_icon(self, state: str):
        icons = {
            "idle": "assets/icon_idle.png",
            "capturing": "assets/icon_recording.png",
            "processing": "assets/icon_processing.png",
            "check_in": "assets/icon_checkin.png",
        }
        self.icon = icons.get(state, "assets/icon_idle.png")


if __name__ == "__main__":
    SIDMenubar().run()
```

## Assets Needed

```
interface/desktop/assets/
├── icon_idle.png       # 22x22 grey circle
├── icon_recording.png  # 22x22 red circle
├── icon_processing.png # 22x22 yellow circle
└── icon_checkin.png    # 22x22 blue circle
```

## Notification Strategy

When agent proactively wants to communicate, API sends notification via this app:
- rumps.notification() for short messages
- Dropdown menu updates for status
- Never open popups or dialogs automatically (non-intrusive)

## Running

```bash
# Run menubar app (separate process from API)
python interface/desktop/menubar.py

# Both must run: API (main.py) + menubar (menubar.py)
```

## Dependencies (External)

```
rumps>=0.4.0
httpx>=0.25.0
```

## Notes

- Menubar app is a separate process from the FastAPI server
- All data operations go via API — menubar has zero direct DB access
- This makes Android port easy: same API, different UI layer
- Phase 4 only — do not build this until API is fully tested
