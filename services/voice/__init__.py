import uuid
import datetime
import asyncio
from typing import Optional

from shared.schemas.models import RawChunk
from services.voice.recorder import Recorder
from services.voice.vad import VADFilter
from services.voice.transcriber import Transcriber
from config.settings import get_settings


class VoiceService:
    def __init__(self):
        self.settings = get_settings()
        self.recorder = Recorder(sample_rate=self.settings.sample_rate)
        # Load VAD and Transcriber models eagerly to prevent first-call latency
        self.vad = VADFilter(threshold=self.settings.vad_threshold, sample_rate=self.settings.sample_rate)
        self.transcriber = Transcriber(model_size=self.settings.whisper_model)
        
    def start_recording(self):
        """Starts capturing audio from the microphone."""
        self.recorder.start()
        
    async def stop_recording_and_process(self, session_id: str) -> Optional[RawChunk]:
        """Stops capturing, trims silence, transcribes, and returns a structured Chunk."""
        audio = self.recorder.stop()
        if len(audio) == 0:
            return None
            
        duration_sec = len(audio) / self.settings.sample_rate
        
        # Trim silence
        trimmed_audio, silence_ratio = self.vad.trim_silence(audio)
        if len(trimmed_audio) == 0:
            return None
            
        # Transcribe in a separate thread so we don't block the asyncio event loop
        raw_text = await asyncio.to_thread(
            self.transcriber.transcribe, 
            trimmed_audio, 
            self.settings.sample_rate
        )
        
        if not raw_text:
            return None
            
        chunk_id = str(uuid.uuid4())
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        
        return RawChunk(
            chunk_id=chunk_id,
            session_id=session_id,
            timestamp=timestamp,
            raw_text=raw_text,
            audio_duration_sec=duration_sec,
            silence_ratio=silence_ratio
        )


# Export the singleton pattern
_voice_service: Optional[VoiceService] = None

def get_voice_service() -> VoiceService:
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service
