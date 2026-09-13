"""Phase 7: automated Claim extraction from PPC's real ASR transcript + diarization turns.

Requires ANTHROPIC_API_KEY in .env and scripts/transcribe_ppc_audio.py to have already produced
both --vad/ASR (.asr.txt) and --diarize-only (.diar.txt) output for PPC's audio.

Inserts Claim + EvidenceSpan rows with extraction_method='automated_audio', distinct from the
Phase 0 hand-labeled ('manual') claims already in the DB for the same company/period -- run
scripts/eval_audio_extraction.py afterward to compare the two.
"""

from __future__ import annotations

from pathlib import Path

from psycopg.types.json import Jsonb

from crosscheck.db import get_connection
from crosscheck.extraction.audio import extract_claims, merge_transcript_with_speakers
from crosscheck.models import AudioTimestampSpan

TICKER = "PPC"
SUBJECT = "Pilgrim's Pride Corporation"
PERIOD = "FY2020-Q3"


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.id, d.local_path FROM documents d "
            "JOIN quarters q ON q.id = d.quarter_id "
            "JOIN companies co ON co.id = q.company_id "
            "WHERE co.ticker = %s AND d.modality = 'audio'",
            (TICKER,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"No audio document for {TICKER} -- run `make seed` first")
        document_id, local_path = row

        audio_path = Path(local_path)
        asr_path = audio_path.with_suffix(".asr.txt")
        diar_path = audio_path.with_suffix(".diar.txt")
        if not asr_path.exists() or not diar_path.exists():
            raise RuntimeError(
                f"Missing {asr_path} or {diar_path} -- run scripts/transcribe_ppc_audio.py "
                "(both plain and --diarize-only) first"
            )

        transcript = merge_transcript_with_speakers(asr_path, diar_path)
        pairs = extract_claims(transcript, document_id=document_id, subject=SUBJECT, period=PERIOD)

        for claim, span in pairs:
            cur.execute(
                """INSERT INTO claims
                   (document_id, subject, metric, canonical_metric_key, period, value, unit,
                    qualifier, speaker, extraction_method, model_id, prompt_hash, confidence)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    claim.document_id,
                    claim.subject,
                    claim.metric,
                    claim.canonical_metric_key,
                    claim.period,
                    claim.value,
                    claim.unit,
                    claim.qualifier,
                    claim.speaker,
                    claim.extraction_method,
                    claim.model_id,
                    claim.prompt_hash,
                    claim.confidence,
                ),
            )
            inserted_row = cur.fetchone()
            assert (
                inserted_row is not None
            )  # nosec B101 - INSERT...RETURNING always returns one row
            claim_id = inserted_row[0]

            assert isinstance(span.span_json, AudioTimestampSpan)  # nosec B101 - extract_claims
            # always produces AudioTimestampSpan here; narrows the EvidenceSpan union for mypy.
            span_payload = Jsonb(span.span_json.model_dump(mode="json"))
            cur.execute(
                "INSERT INTO evidence_spans (claim_id, span_type, span_json) VALUES (%s,%s,%s)",
                (claim_id, span.span_type.value, span_payload),
            )
            print(
                f"{claim.canonical_metric_key}: {claim.metric} = {claim.value} {claim.unit} "
                f"(claim_id={claim_id}, speaker={claim.speaker}, "
                f"[{span.span_json.start_sec}-{span.span_json.end_sec}])"
            )

        print(f"\nInserted {len(pairs)} automated_audio claims for {TICKER} {PERIOD}.")


if __name__ == "__main__":
    main()
