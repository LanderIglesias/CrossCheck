"""Thin wrapper around faster-whisper for local, CPU-capable ASR.

Model choice: `small` (int8 quantized), not `large-v3-turbo` — this runs on CPU-only hardware, and
`small` is the honest choice for a ~54-minute call in reasonable wall-clock time. WER numbers
reported downstream reflect this choice, not an assumed larger model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

MODEL_SIZE = "small"

_model: Any = None


@dataclass(frozen=True)
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_path: Path, vad_filter: bool = True) -> list[TranscriptSegment]:
    """Transcribe `audio_path`, returning timestamped segments."""
    model = _get_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=vad_filter)
    return [TranscriptSegment(seg.start, seg.end, seg.text.strip()) for seg in segments]
