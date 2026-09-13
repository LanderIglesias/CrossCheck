"""Earnings-21 corpus client.

Public earnings-call corpus released by Rev.com (CC-BY-SA), hosted at
https://github.com/revdotcom/speech-datasets. Ships raw audio + human-produced reference
transcripts, which Phase 0 uses directly for gold-set labeling (no ASR run needed yet).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests

from crosscheck.config import settings
from crosscheck.io_utils import atomic_write_bytes

CORPUS_METADATA_URL = (
    "https://raw.githubusercontent.com/revdotcom/speech-datasets/main/earnings21/metadata.csv"
)

# A GitHub raw-content 404 or rate-limit page comes back as small HTML, never as our CSV/audio/
# transcript payloads. Sniffing for this is cheap insurance against silently caching an error page.
_HTML_ERROR_MARKERS = (b"<html", b"<!DOCTYPE html")


class Earnings21ResponseError(RuntimeError):
    """Raised when a corpus URL doesn't return the expected file type."""


def _reject_if_html_error(raw_bytes: bytes, url: str) -> None:
    head = raw_bytes[:256].lstrip().lower()
    if any(head.startswith(marker) for marker in _HTML_ERROR_MARKERS):
        raise Earnings21ResponseError(
            f"expected a data file from {url}, got an HTML page instead (likely a 404 or rate limit)"
        )


def fetch_corpus_metadata() -> Path:
    """Download the Earnings-21 metadata CSV (company/ticker/file-id listing) once, cached."""
    cache_dir = settings.raw_dir / "earnings21"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / "metadata.csv"
    if not dest.exists():
        resp = requests.get(CORPUS_METADATA_URL, timeout=30)
        resp.raise_for_status()
        _reject_if_html_error(resp.content, CORPUS_METADATA_URL)
        atomic_write_bytes(dest, resp.content)
    return dest


def download_audio_and_transcript(
    file_id: str, audio_url: str, transcript_url: str
) -> dict[str, Path]:
    """Download one call's audio + reference transcript, deduped by content hash."""
    cache_dir = settings.raw_dir / "earnings21"
    cache_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for kind, url, suffix in (("audio", audio_url, ".mp3"), ("transcript", transcript_url, ".txt")):
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        raw_bytes = resp.content
        _reject_if_html_error(raw_bytes, url)
        digest = hashlib.sha256(raw_bytes).hexdigest()[:12]
        dest = cache_dir / f"{file_id}_{digest}{suffix}"
        if not dest.exists():
            atomic_write_bytes(dest, raw_bytes)
        paths[kind] = dest
    return paths
