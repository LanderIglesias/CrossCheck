"""Phase 2: real WER of faster-whisper (small, CPU) vs. Earnings-21's human reference transcript.

Uses the ASR output written by scripts/transcribe_ppc_audio.py (run that first) and the reference
transcript already downloaded in Phase 0 (data/raw/earnings21/*.txt for PPC's file_id 4383161).

Both reference and hypothesis are lowercased and stripped of punctuation before scoring (jiwer's
standard normalization) — this measures word-recognition accuracy, not verbatim-formatting match,
consistent with how WER is conventionally reported for ASR systems.
"""

from __future__ import annotations

import re
from pathlib import Path

import jiwer

from crosscheck.audio.reference import reference_text
from crosscheck.db import get_connection

TICKER = "PPC"

_NORMALIZE = jiwer.Compose(
    [
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
)


def find_paths() -> tuple[Path, Path]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.local_path FROM documents d "
            "JOIN quarters q ON q.id = d.quarter_id "
            "JOIN companies co ON co.id = q.company_id "
            "WHERE co.ticker = %s AND d.modality = 'audio'",
            (TICKER,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"No audio document for {TICKER} — run `make seed` first")
        audio_path = Path(row[0])

    asr_path = audio_path.with_suffix(".asr.txt")
    if not asr_path.exists():
        raise RuntimeError(
            f"No ASR output at {asr_path} — run scripts/transcribe_ppc_audio.py first"
        )

    # The reference transcript shares the audio's file_id prefix (e.g. "4383161_") but has a
    # different content-hash suffix, since it was downloaded as a separate file — glob for it
    # rather than assuming a matching filename. Exclude our own *.asr.txt output, which also
    # matches "*.txt" and would otherwise be picked up as a false "reference" transcript.
    file_id = audio_path.stem.split("_")[0]
    matches = [
        p for p in audio_path.parent.glob(f"{file_id}_*.txt") if not p.name.endswith(".asr.txt")
    ]
    if not matches:
        raise RuntimeError(
            f"No reference transcript found for file_id {file_id} in {audio_path.parent}"
        )
    return asr_path, matches[0]


def load_asr_text(asr_path: Path) -> str:
    lines = asr_path.read_text(encoding="utf-8").splitlines()
    texts = [re.sub(r"^\[[\d.]+-[\d.]+\]\s*", "", line) for line in lines]
    return " ".join(texts)


def main() -> None:
    asr_path, reference_path = find_paths()
    hypothesis = load_asr_text(asr_path)
    reference = reference_text(reference_path)

    result = jiwer.process_words(
        reference, hypothesis, reference_transform=_NORMALIZE, hypothesis_transform=_NORMALIZE
    )

    print(f"Reference: {reference_path.name} ({len(reference.split())} words)")
    print(f"Hypothesis: {asr_path.name} ({len(hypothesis.split())} words)")
    print(f"\nWER:  {result.wer:.3f}")
    print(f"MER:  {result.mer:.3f}")
    print(f"WIL:  {result.wil:.3f}")
    print(
        f"substitutions={result.substitutions} deletions={result.deletions} "
        f"insertions={result.insertions} hits={result.hits}"
    )


if __name__ == "__main__":
    main()
