import logging
import torch
import numpy as np

logger = logging.getLogger(__name__)


class VADFilter:
    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True
        )
        self.get_speech_timestamps = utils[0]

    def trim_silence(self, audio: np.ndarray) -> tuple[np.ndarray, float]:
        if len(audio) == 0:
            return audio, 1.0

        if audio.dtype == np.int16:
            audio_f32 = audio.astype(np.float32) / 32768.0
        else:
            audio_f32 = audio.astype(np.float32)

        audio_tensor = torch.from_numpy(audio_f32)
        if len(audio_tensor.shape) > 1:
            audio_tensor = audio_tensor.squeeze()

        try:
            timestamps = self.get_speech_timestamps(
                audio_tensor,
                self.model,
                sampling_rate=self.sample_rate,
                threshold=self.threshold
            )
        except Exception as e:
            logger.warning("VAD failed, returning raw audio: %s", e)
            return audio, 0.0

        if not timestamps:
            return np.array([], dtype=audio.dtype), 1.0

        start_idx = timestamps[0]['start']
        end_idx = timestamps[-1]['end']

        trimmed_audio = audio[start_idx:end_idx]

        original_len = len(audio)
        trimmed_len = end_idx - start_idx
        silence_ratio = 1.0 - (trimmed_len / original_len) if original_len > 0 else 0.0

        return trimmed_audio, silence_ratio
