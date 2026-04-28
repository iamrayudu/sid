from faster_whisper import WhisperModel
import numpy as np

class Transcriber:
    def __init__(self, model_size: str = "base.en"):
        # device="auto" uses optimal available device (CPU/CUDA/CoreML)
        # compute_type="int8" speeds up inference
        self.model = WhisperModel(model_size, device="auto", compute_type="int8")
        
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if len(audio) == 0:
            return ""
            
        # faster-whisper expects float32
        if audio.dtype == np.int16:
            audio_f32 = audio.astype(np.float32) / 32768.0
        else:
            audio_f32 = audio.astype(np.float32)
            
        # Transcribe directly from numpy array
        segments, _ = self.model.transcribe(
            audio_f32,
            beam_size=1,
            language="en"
        )
        
        text = " ".join([segment.text.strip() for segment in segments])
        return text.strip()
