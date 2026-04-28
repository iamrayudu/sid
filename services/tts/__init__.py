"""Text-to-speech service.

V1: macOS `say` command (non-blocking subprocess).
Upgrade path: swap backend to Piper TTS for offline neural voice without changing callers.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger("sid.tts")

_MACOS_VOICE = "Samantha"   # change to "Alex", "Karen", etc. in .env or models.yaml
_RATE = 185                  # words-per-minute (default 200, slightly slower = clearer)


class TTSService:
    """Speaks text aloud. Fire-and-forget: callers don't wait for audio to finish."""

    def __init__(self, voice: str = _MACOS_VOICE, rate: int = _RATE):
        self._voice = voice
        self._rate = rate
        self._has_say = shutil.which("say") is not None
        self._proc: Optional[asyncio.subprocess.Process] = None

        if not self._has_say:
            logger.warning("'say' command not found — TTS disabled (non-macOS?)")

    async def speak(self, text: str) -> None:
        """Speak text. Returns immediately; audio plays in background."""
        if not self._has_say or not text:
            return

        await self._kill_current()

        try:
            self._proc = await asyncio.create_subprocess_exec(
                "say",
                "-v", self._voice,
                "-r", str(self._rate),
                text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            asyncio.create_task(self._wait_and_clear())
        except Exception as e:
            logger.warning("TTS speak failed: %s", e)

    async def stop(self) -> None:
        """Interrupt any currently speaking output."""
        await self._kill_current()

    async def _kill_current(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=1.0)
            except Exception:
                pass
        self._proc = None

    async def _wait_and_clear(self) -> None:
        if self._proc:
            await self._proc.wait()
            self._proc = None

    def is_speaking(self) -> bool:
        return self._proc is not None and self._proc.returncode is None


_tts: Optional[TTSService] = None


def get_tts() -> TTSService:
    global _tts
    if _tts is None:
        _tts = TTSService()
    return _tts
