"""Parse Earnings-21's pipe-separated reference-transcript format.

Real format (confirmed against `data/raw/earnings21/*.txt`, header row):
`token|speaker|ts|endTs|punctuation|case|tags|wer_tags`

`ts`/`endTs` are empty for every token in the files we have (Earnings-21 ships per-utterance
timing separately, not per-token) — only `token`, `speaker`, and `punctuation` are used here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerTurn:
    speaker: str
    text: str


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="|")
        return list(reader)


def reference_text(path: Path) -> str:
    """Reconstruct plain reference text (token sequence + trailing punctuation) for WER scoring."""
    words = []
    for row in _read_rows(path):
        token = row["token"]
        punctuation = row.get("punctuation") or ""
        words.append(token + punctuation)
    return " ".join(words)


def speaker_turns(path: Path) -> list[SpeakerTurn]:
    """Group consecutive same-speaker tokens into turns (no absolute timing available)."""
    turns: list[SpeakerTurn] = []
    current_speaker: str | None = None
    current_words: list[str] = []

    for row in _read_rows(path):
        speaker = row["speaker"]
        token = row["token"] + (row.get("punctuation") or "")
        if speaker != current_speaker:
            if current_speaker is not None:
                turns.append(SpeakerTurn(current_speaker, " ".join(current_words)))
            current_speaker = speaker
            current_words = [token]
        else:
            current_words.append(token)

    if current_speaker is not None:
        turns.append(SpeakerTurn(current_speaker, " ".join(current_words)))

    return turns


def unique_speaker_count(path: Path) -> int:
    return len({row["speaker"] for row in _read_rows(path)})
