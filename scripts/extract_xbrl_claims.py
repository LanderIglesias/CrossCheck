"""Phase 8: automated Claim extraction from all 5 companies' real, already-downloaded XBRL
companyfacts JSON (supersedes the Phase 3 PPC-only extract_ppc_xbrl_claims.py).

Accession numbers below are each company's real 10-Q filing accession number for the period in
the `quarters` table (confirmed live from db/data_scouting.md and by directly inspecting each
company's cached companyfacts JSON) -- used instead of fiscal_year/fiscal_period to select the
right quarterly fact, since SEC's own fy/fp metadata is not always reliable (real, confirmed case:
GE's companyfacts JSON tags its FY2020-Q1 fact fy=2019/fp="Q3" -- see src/crosscheck/extraction/
xbrl.py's docstring for the fix).

Inserts Claim + EvidenceSpan rows with extraction_method='automated_xbrl', distinct from the
Phase 0 hand-labeled ('manual') claims already in the DB -- run scripts/eval_xbrl_extraction.py
afterward to compare the two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from crosscheck.db import get_connection
from crosscheck.extraction.xbrl import extract_claims
from crosscheck.models import XBRLFactSpan


@dataclass(frozen=True)
class CompanyTarget:
    ticker: str
    subject: str
    period: str
    accession_number: str


COMPANIES: list[CompanyTarget] = [
    CompanyTarget("PPC", "Pilgrim's Pride Corporation", "FY2020-Q3", "0000802481-20-000080"),
    CompanyTarget("DHR", "Danaher Corporation", "FY2020-Q1", "0000313616-20-000093"),
    CompanyTarget("GE", "General Electric Company", "FY2020-Q1", "0000040545-20-000021"),
    CompanyTarget("TRV", "The Travelers Companies, Inc.", "FY2020-Q2", "0000086312-20-000039"),
    CompanyTarget("ADTN", "ADTRAN Holdings, Inc.", "FY2020-Q3", "0001564590-20-052017"),
]


def main() -> None:
    total_inserted = 0
    with get_connection() as conn, conn.cursor() as cur:
        for company in COMPANIES:
            cur.execute(
                "SELECT d.id, d.local_path FROM documents d "
                "JOIN quarters q ON q.id = d.quarter_id "
                "JOIN companies co ON co.id = q.company_id "
                "WHERE co.ticker = %s AND d.modality = 'xbrl'",
                (company.ticker,),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    f"No xbrl document for {company.ticker} -- run `make seed` first"
                )
            document_id, local_path = row

            with open(local_path, encoding="utf-8") as f:
                company_facts = json.load(f)

            pairs = extract_claims(
                company_facts,
                document_id=document_id,
                subject=company.subject,
                period=company.period,
                accession_number=company.accession_number,
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

                assert isinstance(span.span_json, XBRLFactSpan)  # nosec B101 - extract_claims
                # always produces XBRLFactSpan here; narrows the EvidenceSpan union for mypy.
                span_payload = Jsonb(span.span_json.model_dump(mode="json"))
                cur.execute(
                    "INSERT INTO evidence_spans (claim_id, span_type, span_json) "
                    "VALUES (%s,%s,%s)",
                    (claim_id, span.span_type.value, span_payload),
                )
                print(
                    f"{company.ticker} {claim.canonical_metric_key}: {claim.metric} = "
                    f"{claim.value} {claim.unit} (claim_id={claim_id}, tag={span.span_json.tag})"
                )

            total_inserted += len(pairs)

        print(
            f"\nInserted {total_inserted} automated_xbrl claims across {len(COMPANIES)} companies."
        )


if __name__ == "__main__":
    main()
