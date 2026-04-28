import uuid
import datetime
import asyncio
import logging
from typing import Optional

from shared.schemas.models import RawChunk
from config.settings import get_settings

logger = logging.getLogger("sid.voice")


class VoiceService:
    def __init__(self):
        self.settings = get_settings()
        self._recorder = None
        self._vad = None
        self._transcriber = None

    def _ensure_loaded(self):
        """Lazy-initialize heavy components on first use (VAD loads PyTorch, Whisper loads model)."""
        if self._recorder is None:
            from services.voice.recorder import Recorder
            self._recorder = Recorder(sample_rate=self.settings.sample_rate)
        if self._vad is None:
            from services.voice.vad import VADFilter
            self._vad = VADFilter(threshold=self.settings.vad_threshold, sample_rate=self.settings.sample_rate)
        if self._transcriber is None:
            from services.voice.transcriber import Transcriber
            logger.info("Loading Whisper model '%s' (first use)...", self.settings.whisper_model)
            self._transcriber = Transcriber(model_size=self.settings.whisper_model)

    @property
    def recorder(self):
        self._ensure_loaded()
        return self._recorder

    @property
    def vad(self):
        self._ensure_loaded()
        return self._vad

    @property
    def transcriber(self):
        self._ensure_loaded()
        return self._transcriber

    def start_recording(self):
        self._ensure_loaded()
        self._recorder.start(max_seconds=self.settings.max_recording_seconds)

    async def stop_recording_and_process(self, session_id: str) -> Optional[RawChunk]:
        audio = self._recorder.stop()
        if len(audio) == 0:
            return None

        duration_sec = len(audio) / self.settings.sample_rate

        trimmed_audio, silence_ratio = self._vad.trim_silence(audio)
        if len(trimmed_audio) == 0:
            return None

        raw_text = await asyncio.to_thread(
            self._transcriber.transcribe,
            trimmed_audio,
            self.settings.sample_rate
        )

        if not raw_text:
            return None

        chunk_id = str(uuid.uuid4())
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        return RawChunk(
            chunk_id=chunk_id,
            session_id=session_id,
            timestamp=timestamp,
            raw_text=raw_text,
            audio_duration_sec=duration_sec,
            silence_ratio=silence_ratio
        )


_voice_service: Optional[VoiceService] = None

def get_voice_service() -> VoiceService:
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service
