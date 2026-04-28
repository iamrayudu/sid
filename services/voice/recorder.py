import sounddevice as sd
import numpy as np

class Recorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self._buffer = []
        self._stream = None

    def _callback(self, indata, frames, time, status):
        # We ignore status here but in a production environment 
        # it could be useful to log overflows.
        if self.is_recording:
            # indata is shape (frames, channels), dtype is int16
            self._buffer.append(indata.copy())

    def start(self):
        """Start recording audio."""
        if self.is_recording:
            return
            
        self._buffer = []
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype='int16',
            callback=self._callback
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return the flattened 1D int16 array of audio."""
        if not self.is_recording:
            return np.array([], dtype=np.int16)
            
        self.is_recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._buffer:
            return np.array([], dtype=np.int16)
            
        audio_data = np.concatenate(self._buffer, axis=0)
        return audio_data.flatten()
