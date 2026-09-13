"""Thin wrapper around pyannote.audio's speaker-diarization-3.1 pipeline.

Requires HF_TOKEN in .env: a free Hugging Face account, with the gated-model terms accepted for
pyannote/speaker-diarization-3.1, pyannote/segmentation-3.0, AND pyannote/speaker-diarization-
community-1 (this last one is pulled in internally by pyannote.audio v4's implementation of the
3.1 pipeline — not obvious from the pipeline name alone), and a read-access token.
"""

from __future__ import annotations

import subprocess  # nosec B404 - used only to shell out to ffmpeg, no shell=True, no user input
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crosscheck.config import settings

_pipeline: Any = None


class DiarizationNotConfiguredError(RuntimeError):
    """Raised when HF_TOKEN is missing — diarization cannot run without it."""


class FfmpegNotAvailableError(RuntimeError):
    """Raised when ffmpeg isn't usable for the MP3->WAV transcode step (see .env.example)."""


@dataclass(frozen=True)
class SpeakerTurn:
    start_sec: float
    end_sec: float
    speaker: str


def _get_pipeline() -> Any:
    global _pipeline
    if _pipeline is None:
        if not settings.hf_token:
            raise DiarizationNotConfiguredError(
                "HF_TOKEN is not set in .env — diarization requires a Hugging Face access token "
                "with pyannote/speaker-diarization-3.1's gated-model terms accepted."
            )
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=settings.hf_token
        )
        if pipeline is None:
            raise DiarizationNotConfiguredError(
                "pyannote.audio could not load 'pyannote/speaker-diarization-3.1' — check that "
                "HF_TOKEN is valid and has accepted the model's gated-access terms."
            )
        _pipeline = pipeline
    return _pipeline


def _transcode_to_wav(audio_path: Path) -> Path:
    """Transcode to mono 16kHz WAV via ffmpeg.

    Works around a real pyannote.audio v4 / torchcodec bug: MP3 files can decode to slightly
    fewer samples than the container header's declared duration promises (encoder padding), which
    makes the pipeline's last audio crop request run past the end of the actual decoded waveform
    and raise `ValueError: ... resulted in N samples instead of the expected M samples`. WAV's
    PCM sample count is exact, which avoids the mismatch.

    The WAV is cached in the OS temp dir by filename stem and never deleted — deliberate for this
    single-file project (re-running diarization is common while iterating, and re-transcoding the
    ~54min call is wasted work), but there's no size cap or eviction; not meant to scale past a
    handful of files.
    """
    wav_path = Path(tempfile.gettempdir()) / f"{audio_path.stem}_16k_mono.wav"
    if not wav_path.exists():
        try:
            subprocess.run(  # nosec B603 B607 - fixed arg list, no shell; DB-sourced path, not attacker-controlled
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(wav_path),
                ],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as e:
            raise FfmpegNotAvailableError(
                "ffmpeg was not found on PATH — diarization needs a 'full-shared' ffmpeg build "
                "(not just any ffmpeg.exe). See .env.example for where to get one and how to add "
                "it to PATH."
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise FfmpegNotAvailableError(
                f"ffmpeg failed to transcode {audio_path.name} to WAV (exit {e.returncode}). "
                f"ffmpeg stderr:\n{stderr}"
            ) from e
    return wav_path


def diarize(audio_path: Path) -> list[SpeakerTurn]:
    """Run real speaker diarization on `audio_path`, returning speaker turns in order."""
    pipeline = _get_pipeline()
    wav_path = _transcode_to_wav(audio_path)
    output = pipeline(str(wav_path))
    turns = []
    for segment, _, speaker in output.speaker_diarization.itertracks(yield_label=True):
        turns.append(SpeakerTurn(segment.start, segment.end, speaker))
    return turns
