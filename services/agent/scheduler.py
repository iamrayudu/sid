"""APScheduler jobs — morning brief, evening reflection, 4-hour check-in, Sunday weekly."""
from __future__ import annotations

import logging
from typing import Callable, Awaitable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import get_settings
from services.agent.fsm import get_fsm, AgentState

logger = logging.getLogger("sid.agent.scheduler")


class SIDScheduler:
    def __init__(self, notify: Callable[[str, str], Awaitable[None]]):
        """
        notify(text, event_type) — called when a scheduled event fires.
        event_type: 'checkin' | 'morning' | 'evening' | 'weekly'
        """
        self._notify = notify
        self._scheduler = AsyncIOScheduler()
        self._settings = get_settings()
        self._setup_jobs()

    def _setup_jobs(self):
        s = self._settings

        # Morning brief — daily at configured hour (default 8am)
        self._scheduler.add_job(
            self._run_morning,
            "cron",
            hour=s.morning_hour,
            minute=0,
            id="morning_brief",
            replace_existing=True,
        )

        # Evening reflection — daily at configured hour (default 9pm)
        self._scheduler.add_job(
            self._run_evening,
            "cron",
            hour=s.evening_hour,
            minute=0,
            id="evening_reflect",
            replace_existing=True,
        )

        # Check-in — every N hours (default 4)
        self._scheduler.add_job(
            self._run_checkin,
            "interval",
            hours=s.checkin_interval_hours,
            id="checkin",
            replace_existing=True,
        )

        # Weekly review — Sunday at 8pm
        self._scheduler.add_job(
            self._run_weekly,
            "cron",
            day_of_week="sun",
            hour=20,
            minute=0,
            id="weekly_review",
            replace_existing=True,
        )

    def start(self):
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started (morning=%dh, evening=%dh, checkin=%dh)",
                        self._settings.morning_hour, self._settings.evening_hour,
                        self._settings.checkin_interval_hours)

    def shutdown(self, wait: bool = False):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    async def _run_morning(self):
        fsm = get_fsm()
        if not fsm.can_interrupt():
            logger.debug("Morning brief skipped — FSM blocked (%s)", fsm.state.value)
            return
        fsm.transition(AgentState.MORNING_BRIEF)
        try:
            from services.agent.routines.morning import generate_morning_brief
            brief = await generate_morning_brief()
            await self._notify(brief, "morning")
        except Exception as e:
            logger.error("Morning brief failed: %s", e)
        finally:
            fsm.transition(AgentState.IDLE)

    async def _run_evening(self):
        fsm = get_fsm()
        if not fsm.can_interrupt():
            logger.debug("Evening reflection skipped — FSM blocked (%s)", fsm.state.value)
            return
        fsm.transition(AgentState.EVENING_REFLECT)
        try:
            from services.agent.routines.evening import generate_evening_reflection
            reflection = await generate_evening_reflection()
            await self._notify(reflection, "evening")
        except Exception as e:
            logger.error("Evening reflection failed: %s", e)
        finally:
            fsm.transition(AgentState.IDLE)

    async def _run_checkin(self):
        fsm = get_fsm()
        if not fsm.can_interrupt():
            logger.debug("Check-in skipped — FSM blocked or suppressed (%s)", fsm.state.value)
            return

        from services.memory import get_store
        store = get_store()
        since = fsm.last_checkin_iso

        try:
            count = await store.get_unchecked_count(since)
        except Exception as e:
            logger.warning("Could not get unchecked count: %s", e)
            return

        if count < self._settings.checkin_threshold:
            logger.debug("Check-in skipped — only %d new thoughts (threshold %d)",
                         count, self._settings.checkin_threshold)
            return

        fsm.transition(AgentState.CHECK_IN)
        fsm.mark_checkin()
        try:
            from services.agent.routines.checkin import generate_checkin
            msg = await generate_checkin(since)
            if msg:
                await self._notify(msg, "checkin")
        except Exception as e:
            logger.error("Check-in failed: %s", e)
        finally:
            fsm.transition(AgentState.IDLE)

    async def _run_weekly(self):
        fsm = get_fsm()
        if not fsm.can_interrupt():
            logger.debug("Weekly review skipped — FSM blocked (%s)", fsm.state.value)
            return
        fsm.transition(AgentState.WEEKLY_REVIEW)
        try:
            from services.agent.routines.weekly import generate_weekly_review
            review = await generate_weekly_review()
            await self._notify(review, "weekly")
        except Exception as e:
            logger.error("Weekly review failed: %s", e)
        finally:
            fsm.transition(AgentState.IDLE)

    # ── Manual triggers (API endpoints) ───────────────────────────────────────

    async def trigger_morning(self) -> str:
        from services.agent.routines.morning import generate_morning_brief
        return await generate_morning_brief()

    async def trigger_evening(self) -> str:
        from services.agent.routines.evening import generate_evening_reflection
        return await generate_evening_reflection()

    async def trigger_weekly(self) -> str:
        from services.agent.routines.weekly import generate_weekly_review
        return await generate_weekly_review()


_scheduler: Optional[SIDScheduler] = None


def get_scheduler() -> Optional[SIDScheduler]:
    return _scheduler


def init_scheduler(notify: Callable[[str, str], Awaitable[None]]) -> SIDScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = SIDScheduler(notify=notify)
    return _scheduler
