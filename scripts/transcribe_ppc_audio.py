"""Phase 2: VAD + ASR + diarization on PPC's real earnings-call audio.

Usage:
    python scripts/transcribe_ppc_audio.py --vad-only     # just run VAD, print segment stats
    python scripts/transcribe_ppc_audio.py --diarize-only  # just run diarization, write .diar.txt
    python scripts/transcribe_ppc_audio.py                 # full VAD + ASR transcription
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from crosscheck.audio.asr import transcribe
from crosscheck.audio.diarization import diarize
from crosscheck.audio.vad import detect_speech_segments
from crosscheck.db import get_connection

TICKER = "PPC"


def find_audio_path() -> Path:
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
        return Path(row[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vad-only", action="store_true")
    parser.add_argument("--diarize-only", action="store_true")
    args = parser.parse_args()

    audio_path = find_audio_path()
    print(f"Audio file: {audio_path}")

    if args.diarize_only:
        start = time.monotonic()
        turns = diarize(audio_path)
        diar_elapsed = time.monotonic() - start
        speakers = {t.speaker for t in turns}
        print(
            f"Diarization: {len(turns)} turns, {len(speakers)} unique speakers "
            f"(took {diar_elapsed / 60:.1f} min)"
        )
        out_path = audio_path.with_suffix(".diar.txt")
        with out_path.open("w", encoding="utf-8") as f:
            for t in turns:
                f.write(f"[{t.start_sec:.1f}-{t.end_sec:.1f}] {t.speaker}\n")
        print(f"Diarization turns written to {out_path}")
        return

    start = time.monotonic()
    segments = detect_speech_segments(audio_path)
    vad_elapsed = time.monotonic() - start
    total_speech_sec = sum(s.end_sec - s.start_sec for s in segments)
    print(
        f"VAD: {len(segments)} speech segments, {total_speech_sec / 60:.1f} min of speech "
        f"detected (VAD took {vad_elapsed:.1f}s)"
    )

    if args.vad_only:
        return

    print("Running faster-whisper ASR (this will take real wall-clock time on CPU)...")
    start = time.monotonic()
    transcript_segments = transcribe(audio_path)
    asr_elapsed = time.monotonic() - start
    print(f"ASR: {len(transcript_segments)} segments transcribed in {asr_elapsed / 60:.1f} min")

    out_path = audio_path.with_suffix(".asr.txt")
    with out_path.open("w", encoding="utf-8") as f:
        for seg in transcript_segments:
            f.write(f"[{seg.start_sec:.1f}-{seg.end_sec:.1f}] {seg.text}\n")
    print(f"ASR transcript written to {out_path}")


if __name__ == "__main__":
    main()
