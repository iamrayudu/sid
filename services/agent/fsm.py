"""Agent FSM — controls what SID is allowed to do at any moment.

CAPTURING is sacred: zero interruptions while the user is speaking.
Suppression: user can say 'not now' to silence check-ins for N hours.
"""
from __future__ import annotations

import datetime
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sid.agent.fsm")

_STATE_FILE = Path.home() / ".sid" / "agent_state.json"


class AgentState(Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    CHECK_IN = "check_in"
    MORNING_BRIEF = "morning_brief"
    EVENING_REFLECT = "evening_reflect"
    WEEKLY_REVIEW = "weekly_review"
    CHAT = "chat"


# Which states can each state transition to
_TRANSITIONS: dict[AgentState, list[AgentState]] = {
    AgentState.IDLE: [
        AgentState.CAPTURING,
        AgentState.CHECK_IN,
        AgentState.MORNING_BRIEF,
        AgentState.EVENING_REFLECT,
        AgentState.WEEKLY_REVIEW,
        AgentState.CHAT,
    ],
    AgentState.CAPTURING: [
        AgentState.IDLE,
        AgentState.PROCESSING,
    ],
    AgentState.PROCESSING: [
        AgentState.IDLE,
        AgentState.CAPTURING,
    ],
    AgentState.CHECK_IN: [
        AgentState.IDLE,
        AgentState.CAPTURING,
        AgentState.CHAT,
    ],
    AgentState.MORNING_BRIEF: [
        AgentState.IDLE,
        AgentState.CAPTURING,
        AgentState.CHAT,
    ],
    AgentState.EVENING_REFLECT: [
        AgentState.IDLE,
        AgentState.CAPTURING,
        AgentState.CHAT,
    ],
    AgentState.WEEKLY_REVIEW: [
        AgentState.IDLE,
        AgentState.CAPTURING,
        AgentState.CHAT,
    ],
    AgentState.CHAT: [
        AgentState.IDLE,
        AgentState.CAPTURING,
    ],
}


class AgentFSM:
    def __init__(self):
        self.state = AgentState.IDLE
        self._suppressed_until: Optional[datetime.datetime] = None
        self._last_checkin: Optional[datetime.datetime] = None
        self._load_state()

    def _load_state(self) -> None:
        try:
            if _STATE_FILE.exists():
                data = json.loads(_STATE_FILE.read_text())
                lc = data.get("last_checkin")
                if lc:
                    self._last_checkin = datetime.datetime.fromisoformat(lc)
        except Exception:
            pass  # corrupt or missing — fresh start is fine

    def _save_state(self) -> None:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps({
                "last_checkin": self._last_checkin.isoformat() if self._last_checkin else None,
            }))
        except Exception:
            pass  # non-critical; next restart defaults to 4h ago

    def transition(self, to: AgentState) -> bool:
        """Attempt a state transition. Returns True if successful."""
        allowed = _TRANSITIONS.get(self.state, [])
        if to in allowed:
            logger.debug("FSM: %s → %s", self.state.value, to.value)
            self.state = to
            return True
        logger.warning("FSM: invalid transition %s → %s (staying in %s)", self.state.value, to.value, self.state.value)
        return False

    def force(self, to: AgentState) -> None:
        """Force a transition regardless of rules (use sparingly, e.g. on recording start)."""
        logger.debug("FSM: forced %s → %s", self.state.value, to.value)
        self.state = to

    def can_interrupt(self) -> bool:
        """True if SID may proactively speak/notify."""
        if self.state == AgentState.CAPTURING:
            return False
        if self._suppressed_until:
            if datetime.datetime.now() < self._suppressed_until:
                return False
            else:
                self._suppressed_until = None
        return True

    def suppress(self, hours: int = 2) -> None:
        self._suppressed_until = datetime.datetime.now() + datetime.timedelta(hours=hours)
        logger.info("FSM: check-ins suppressed for %d hours", hours)

    def mark_checkin(self) -> None:
        self._last_checkin = datetime.datetime.now()
        self._save_state()

    @property
    def last_checkin_iso(self) -> Optional[str]:
        if self._last_checkin is None:
            # Default: 4 hours ago so first check-in can fire
            t = datetime.datetime.now() - datetime.timedelta(hours=4)
        else:
            t = self._last_checkin
        return t.isoformat()

    def status_dict(self) -> dict:
        return {
            "state": self.state.value,
            "can_interrupt": self.can_interrupt(),
            "suppressed_until": self._suppressed_until.isoformat() if self._suppressed_until else None,
            "last_checkin": self._last_checkin.isoformat() if self._last_checkin else None,
        }


_fsm: Optional[AgentFSM] = None


def get_fsm() -> AgentFSM:
    global _fsm
    if _fsm is None:
        _fsm = AgentFSM()
    return _fsm
