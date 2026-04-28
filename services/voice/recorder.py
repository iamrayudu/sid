import logging
import sounddevice as sd
import numpy as np

logger = logging.getLogger(__name__)


class Recorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self._buffer = []
        self._stream = None
        self._max_samples = 0
        self._total_samples = 0

    def _callback(self, indata, frames, time, status):
        if status:
            logger.debug("Recorder status: %s", status)
        if self.is_recording:
            self._total_samples += frames
            if self._max_samples and self._total_samples >= self._max_samples:
                self.is_recording = False  # auto-stop at max duration
                return
            self._buffer.append(indata.copy())

    def start(self, max_seconds: int = 60):
        if self.is_recording:
            return

        self._buffer = []
        self._max_samples = max_seconds * self.sample_rate
        self._total_samples = 0
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype='int16',
            callback=self._callback
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self.is_recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._buffer:
            return np.array([], dtype=np.int16)

        audio_data = np.concatenate(self._buffer, axis=0)
        return audio_data.flatten()
