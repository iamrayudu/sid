# Voice Service

## Purpose

Converts user speech into `RawChunk` objects. This is the entry point for all data in SID.

**Input**: User presses record button  
**Output**: `RawChunk` emitted to processing queue

## Files to Build

```
services/voice/
├── __init__.py          # Exports: VoiceService
├── recorder.py          # sounddevice audio capture (push-to-talk)
├── vad.py               # Silero VAD — trims leading/trailing silence
└── transcriber.py       # faster-whisper STT → raw text
```

## Stack

- `sounddevice` — microphone capture, cross-platform
- `silero-vad` (PyTorch, 1.8MB model) — voice activity detection, 87%+ accuracy
- `faster-whisper` — `base.en` model, Apple Silicon optimized, ~6s for 60s audio

## Output Contract

Every processed audio chunk produces one `RawChunk`. Import from `shared/schemas/models.py`:

```python
class RawChunk(BaseModel):
    chunk_id: str           # uuid4
    session_id: str         # uuid4, groups chunks in one sitting
    timestamp: str          # ISO8601
    raw_text: str           # direct whisper output, no cleaning
    audio_duration_sec: float
    silence_ratio: float    # ratio of silence detected by VAD
```

## Implementation Notes

### recorder.py

```python
# Push-to-talk: record while button held, stop on release
# Sample rate: 16000 Hz (Whisper requirement)
# Channels: 1 (mono)
# dtype: int16
# Buffer: 10 seconds max per chunk (Silero VAD requirement for full-file mode)
# Use sounddevice.rec() for simplicity in V1
```

### vad.py

```python
# Load Silero VAD model: torch.hub.load('snakers4/silero-vad', 'silero_vad')
# Run on full audio buffer after recording stops
# Returns timestamps of speech segments
# Trim: remove non-speech from start/end only (keep mid-sentence pauses)
# Threshold: 0.5 (adjustable via config)
```

### transcriber.py

```python
# Model: base.en (English only, 74MB, fastest)
# Device: "auto" (uses Apple Silicon GPU if available via CoreML)
# Beam size: 1 for speed
# Returns: text string only (no word timestamps in V1)
# Load model ONCE at startup (lazy singleton, ~3s load time)
```

## Key Behaviors

- Push-to-talk: recording starts on button press, stops on release
- Max duration: 60 seconds per chunk (auto-stop + notify user)
- Min duration: 1 second (ignore sub-second presses)
- Silence trimmed from start + end (VAD)
- Empty transcription (just noise): chunk discarded silently
- Never blocks the UI thread — all audio processing is async

## Dependencies (Internal)

- `config/settings.py` → `VoiceConfig` (sample rate, model, thresholds)
- `shared/schemas/models.py` → `RawChunk`
- `services/processing/queue.py` → `add_to_queue(chunk)` after transcription

## Dependencies (External)

```
sounddevice>=0.4.6
faster-whisper>=1.0.0
torch>=2.0.0
torchaudio>=2.0.0
```

## Testing

```python
# Test 1: Record 5 seconds of silence → RawChunk not emitted (VAD filtered)
# Test 2: Record 10 seconds of speech → RawChunk emitted with text
# Test 3: Record 65 seconds → auto-stops at 60s, chunk emitted
# Test 4: Load transcriber twice → second call uses cached model (< 100ms)
```

## How User Should Speak

Document this somewhere visible in the UI:
- **One idea per chunk** (5–25 seconds ideal)
- **Pause between ideas** — let VAD naturally split
- **Optional prefix**: "Idea:", "Task:", "Note:" helps Stage 1 classification but is not required
- System learns natural speech patterns over time
