"""Voice activity detection: speech-segment timestamps from raw audio.

Uses faster-whisper's bundled Silero VAD (onnxruntime-based) directly, rather than pulling in a
separate `silero-vad` package — faster-whisper already ships and depends on this exact model, so
reusing it avoids a second VAD implementation with potentially different results.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from faster_whisper.audio import decode_audio
from faster_whisper.vad import get_speech_timestamps

SAMPLING_RATE = 16000


@dataclass(frozen=True)
class SpeechSegment:
    start_sec: float
    end_sec: float


def detect_speech_segments(audio_path: Path) -> list[SpeechSegment]:
    """Return detected speech segments (in seconds) for the audio file at `audio_path`."""
    audio = decode_audio(str(audio_path), sampling_rate=SAMPLING_RATE)
    raw_segments = get_speech_timestamps(audio, sampling_rate=SAMPLING_RATE)
    return [
        SpeechSegment(seg["start"] / SAMPLING_RATE, seg["end"] / SAMPLING_RATE)
        for seg in raw_segments
    ]
