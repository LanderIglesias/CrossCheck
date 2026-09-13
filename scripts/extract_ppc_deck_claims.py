"""Phase 6: automated Claim extraction from PPC's real, already-downloaded investor deck PDF.

Inserts Claim + EvidenceSpan rows with extraction_method='automated_deck', distinct from the
Phase 0 hand-labeled ('manual') claims already in the DB for the same company/period -- run
scripts/eval_deck_extraction.py afterward to compare the two.
"""

from __future__ import annotations

from pathlib import Path

from psycopg.types.json import Jsonb

from crosscheck.db import get_connection
from crosscheck.extraction.deck import extract_claims
from crosscheck.models import PageBBoxSpan

TICKER = "PPC"
SUBJECT = "Pilgrim's Pride Corporation"
PERIOD = "FY2020-Q3"


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.id, d.local_path FROM documents d "
            "JOIN quarters q ON q.id = d.quarter_id "
            "JOIN companies co ON co.id = q.company_id "
            "WHERE co.ticker = %s AND d.modality = 'deck'",
            (TICKER,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"No deck document for {TICKER} -- run `make seed` first")
        document_id, local_path = row

        pairs = extract_claims(
            Path(local_path), document_id=document_id, subject=SUBJECT, period=PERIOD
        )

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

            assert isinstance(span.span_json, PageBBoxSpan)  # nosec B101 - extract_claims always
            # produces PageBBoxSpan here; this narrows the EvidenceSpan union for mypy/attr access.
            span_payload = Jsonb(span.span_json.model_dump(mode="json"))
            cur.execute(
                "INSERT INTO evidence_spans (claim_id, span_type, span_json) VALUES (%s,%s,%s)",
                (claim_id, span.span_type.value, span_payload),
            )
            print(
                f"{claim.canonical_metric_key}: {claim.metric} = {claim.value} {claim.unit} "
                f"(claim_id={claim_id}, page={span.span_json.page})"
            )

        print(f"\nInserted {len(pairs)} automated_deck claims for {TICKER} {PERIOD}.")


if __name__ == "__main__":
    main()
