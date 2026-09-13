import subprocess
from pathlib import Path

import pytest

from crosscheck.audio.diarization import FfmpegNotAvailableError, _transcode_to_wav


def test_transcode_raises_clear_error_when_ffmpeg_missing(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("ffmpeg not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("crosscheck.audio.diarization.tempfile.gettempdir", lambda: str(tmp_path))

    with pytest.raises(FfmpegNotAvailableError, match="full-shared"):
        _transcode_to_wav(Path("some_audio.mp3"))


def test_transcode_raises_clear_error_when_ffmpeg_fails(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1, cmd=["ffmpeg"], stderr=b"missing shared library"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("crosscheck.audio.diarization.tempfile.gettempdir", lambda: str(tmp_path))

    with pytest.raises(FfmpegNotAvailableError, match="missing shared library"):
        _transcode_to_wav(Path("some_audio.mp3"))
