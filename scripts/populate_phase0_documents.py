"""Populate the `documents` table for the 5 Phase 0 companies from already-acquired raw files.

Run after `make migrate` + `psql ... -f db/seed_companies.sql`. Re-run is idempotent (ON CONFLICT
DO NOTHING on the documents table's (quarter_id, modality, content_hash) unique constraint) and
safe to call again after `pytest` — the DB migration test drops and recreates the public schema,
which wipes seeded data; this script (plus re-running seed_companies.sql) restores it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from crosscheck.config import settings
from crosscheck.db import get_connection
from crosscheck.sources.decks import DECK_MANIFEST, download_deck
from crosscheck.sources.earnings21 import download_audio_and_transcript
from crosscheck.sources.edgar import fetch_company_facts, fetch_filing_document

EARNINGS21_BASE = "https://raw.githubusercontent.com/revdotcom/speech-datasets/main/earnings21"


@dataclass(frozen=True)
class CompanyInfo:
    cik: str
    fiscal_year: int
    fiscal_period: str
    accession: str
    primary_document: str
    audio_file_id: int


COMPANIES: dict[str, CompanyInfo] = {
    "PPC": CompanyInfo(
        "0000802481", 2020, "Q3", "0000802481-20-000080", "ppc-20200927.htm", 4383161
    ),
    "DHR": CompanyInfo(
        "0000313616", 2020, "Q1", "0000313616-20-000093", "dhr-202043x10q.htm", 4344338
    ),
    "GE": CompanyInfo(
        "0000040545", 2020, "Q1", "0000040545-20-000021", "ge1q202010-q.htm", 4341191
    ),
    "TRV": CompanyInfo(
        "0000086312", 2020, "Q2", "0000086312-20-000039", "trv-20200630.htm", 4360366
    ),
    "ADTN": CompanyInfo(
        "0000926282", 2020, "Q3", "0001564590-20-052017", "adtn-10q_20200930.htm", 4384744
    ),
}


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        for ticker, info in COMPANIES.items():
            cur.execute("SELECT id FROM companies WHERE ticker = %s", (ticker,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"{ticker} not seeded — run db/seed_companies.sql first")
            company_id = row[0]

            cur.execute(
                "SELECT id FROM quarters WHERE company_id = %s AND fiscal_year = %s "
                "AND fiscal_period = %s",
                (company_id, info.fiscal_year, info.fiscal_period),
            )
            quarter_row = cur.fetchone()
            # Type-narrowing, not a security control: db/seed_companies.sql guarantees this
            # quarter row exists for every company inserted above.
            assert quarter_row is not None  # nosec B101
            quarter_id = quarter_row[0]

            audio_url = f"{EARNINGS21_BASE}/media/{info.audio_file_id}.mp3"
            transcript_url = (
                f"{EARNINGS21_BASE}/transcripts/nlp_references/{info.audio_file_id}.nlp"
            )
            audio_paths = download_audio_and_transcript(
                str(info.audio_file_id), audio_url, transcript_url
            )
            audio_hash = hashlib.sha256(audio_paths["audio"].read_bytes()).hexdigest()
            cur.execute(
                """INSERT INTO documents (quarter_id, modality, source_url, content_hash, local_path)
                   VALUES (%s, 'audio', %s, %s, %s) ON CONFLICT DO NOTHING""",
                (quarter_id, audio_url, audio_hash, str(audio_paths["audio"])),
            )

            deck_url = DECK_MANIFEST[(ticker, info.fiscal_year, info.fiscal_period)]
            deck_path, deck_hash = download_deck(
                ticker, info.fiscal_year, info.fiscal_period, deck_url
            )
            cur.execute(
                """INSERT INTO documents (quarter_id, modality, source_url, content_hash, local_path)
                   VALUES (%s, 'deck', %s, %s, %s) ON CONFLICT DO NOTHING""",
                (quarter_id, deck_url, deck_hash, str(deck_path)),
            )

            filing_path, filing_hash = fetch_filing_document(
                info.cik, info.accession, info.primary_document
            )
            accn_nodash = info.accession.replace("-", "")
            cik_nolead = str(int(info.cik))
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accn_nodash}/"
                f"{info.primary_document}"
            )
            cur.execute(
                """INSERT INTO documents (quarter_id, modality, source_url, content_hash, local_path)
                   VALUES (%s, 'filing', %s, %s, %s) ON CONFLICT DO NOTHING""",
                (quarter_id, filing_url, filing_hash, str(filing_path)),
            )

            facts = fetch_company_facts(info.cik)
            xbrl_hash = hashlib.sha256(json.dumps(facts).encode()).hexdigest()
            xbrl_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{info.cik}.json"
            xbrl_cache_path = (
                settings.raw_dir
                / "edgar_cache"
                / f"{hashlib.sha256(xbrl_url.encode()).hexdigest()}.json"
            )
            cur.execute(
                """INSERT INTO documents (quarter_id, modality, source_url, content_hash, local_path)
                   VALUES (%s, 'xbrl', %s, %s, %s) ON CONFLICT DO NOTHING""",
                (quarter_id, xbrl_url, xbrl_hash, str(xbrl_cache_path)),
            )

            print(f"{ticker}: 4 documents inserted (audio, deck, filing, xbrl)")


if __name__ == "__main__":
    main()
