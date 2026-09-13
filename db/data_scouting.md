# Phase 0 data scouting — verification trail

## Finding: Earnings-21 has one call per company, not per-quarter history

`earnings21-file-metadata.csv` (fetched from
`https://raw.githubusercontent.com/revdotcom/speech-datasets/main/earnings21/earnings21-file-metadata.csv`,
44 rows) has exactly one row per company. There is no way to get 4 quarters of audio per company
from this corpus. **Scope decision (confirmed with user): reduce to 1 quarter per company.** All
4 modalities (audio, deck, filing, XBRL) are only jointly available for that single quarter; nothing
downstream should assume multi-quarter audio coverage.

## Finding: not every company publishes an investor deck

The first candidate set (HSY, AXP, DHR, ILMN, COP) was picked purely for brand recognition and
clean US-domestic filing status. Once deck URLs were actually hunted down (live browser
navigation of each company's own IR site — necessary because these sites are JS-rendered and
don't yield to plain HTTP fetches), 3 of them turned out to have **no investor deck at all** for
the matching quarter:

- **Illumina (ILMN)**: their own quarterly-results page lists Press Release / Summary of Remarks /
  Prepared Remarks / 10-Q for Q3 2020 — no "Earnings Presentation" column exists until **2022**.
- **ConocoPhillips (COP)**: their public earnings archive's earliest entry is Q4 2020; Q3 2020 was
  never archived there.
- **Hershey (HSY)**: their quarterly-results table (2016-2026, checked in full) has exactly 4
  columns — Earnings Release, Transcript of Recorded Remarks, Transcript of Q&A, Filing — **no
  Presentation column, ever, for any quarter**.
- Also checked and rejected for the same reason: **YETI Holdings** (no Presentation column at
  all, any year).

These 3 were swapped for **GE, Travelers (TRV), and Adtran (ADTN)**, each independently confirmed
by finding a real, downloadable deck PDF (verified with `curl`: correct HTTP 200, `%PDF-` magic
bytes, plausible file size) directly from the company's own IR site.

## Finding: AXP's Earnings-21 audio was not actually an earnings call

While extracting real claims from AXP's documents for a labeling pilot, its Earnings-21 reference
transcript opened with: *"Good morning, this is Craig Moore with Autonomous... for our fifth
annual Future of Commerce Symposium."* — an unrelated analyst-hosted conference, not American
Express's Q3 2020 earnings call. The corpus's `financial_quarter`/`sector` metadata columns had
labeled it as if it were AXP's own earnings audio.

In hindsight this was screenable in advance: AXP's row has `unique_speakers=2` in the metadata CSV
(a moderator + one AXP exec — consistent with a fireside chat, not an earnings call), while every
other chosen company has 7-15 unique speakers (CEO + CFO + several analysts in Q&A, consistent
with a genuine earnings call). All 4 other companies' transcript openings were read in full and
independently confirmed as genuine earnings-call operator/IR introductions.

AXP was swapped for **Pilgrim's Pride (PPC)**, Q3 2020 (`unique_speakers=11`), whose transcript
opens with an explicit "Pilgrim's Pride Earnings Conference Call" introduction that also
name-checks the slide deck — independently confirmed, deck and 10-Q and XBRL all fetched for real.

## The 5 final companies (all 4 modalities confirmed available)

| Ticker | CIK | Earnings-21 file_id | Quarter | 10-Q report_date | 10-Q Accession # | Deck URL (verified real) |
|---|---|---|---|---|---|---|
| PPC | 0000802481 | 4383161 | Q3 2020 | 2020-09-27 | 0000802481-20-000080 | `ir.pilgrims.com/static-files/60bb1952-27cc-4256-8699-bd48d2ceefe2` |
| DHR | 0000313616 | 4344338 | Q1 2020 | 2020-04-03 | 0000313616-20-000093 | `filecache.investorroom.com/mr5ir_danaher/650/1Q2020%20Danaher%20Earnings%20Presentation.pdf` |
| GE  | 0000040545 | 4341191 | Q1 2020 | 2020-03-31 | 0000040545-20-000021 | `ge.com/sites/default/files/ge_webcast_presentation_04292020_0.pdf` |
| TRV | 0000086312 | 4360366 | Q2 2020 | 2020-06-30 | 0000086312-20-000039 | `s26.q4cdn.com/410417801/files/doc_financials/quarterly_results/2020/q2/ed012ea5-616a-7a4a-3a04-38a1ef782740.pdf` |
| ADTN| 0000926282 | 4384744 | Q3 2020 | 2020-09-30 | 0001564590-20-052017 | `s205.q4cdn.com/856112109/files/doc_financials/2020/Q3-2020-Earnings-Call-Supporting-Materials.pdf` |

CIKs verified via SEC's `company_tickers.json` master file. 10-Q accession numbers verified via
`data.sec.gov/submissions/CIK<n>.json`. Deck PDFs verified by actually downloading them (not just
finding a link) — file sizes: PPC 2.0MB, DHR 945KB, GE 805KB, TRV 1.1MB, ADTN 236KB. All 5
transcript openings were read and confirmed as genuine earnings-call introductions.

## Technique notes (for anyone extending this list later)

- Company IR sites are almost universally JS-rendered SPAs (Q4 Inc. or Notified-hosted) — plain
  `curl`/`WebFetch` sees only the app shell, not the actual document links. Real browser
  navigation (accessibility-tree snapshots) was required to read the rendered quarterly-results
  tables.
- The Wayback Machine's CDX API (`web.archive.org/cdx/search/cdx?url=<host>&matchType=domain&...
  &filter=mimetype:application/pdf`) is a fast way to recover a company's *older* CDN account
  and file-naming pattern when the live site's dropdown/pagination only surfaces recent years —
  this is exactly how Danaher's deck was found.
- Never blindly guess a filename pattern and trust it silently — every candidate URL here was
  verified by an actual `curl` download checked for `%PDF-` magic bytes and a plausible size
  before being accepted.

## Done

`DECK_MANIFEST`, Earnings-21 audio+transcript download, XBRL companyfacts fetch, and full
`documents` table population (all 4 modalities × 5 companies, 20 rows) are complete — see
`scripts/populate_phase0_documents.py` and the README's Setup section (`make seed`).

## Explicitly not yet done (next steps)

- **Gold-set labeling**: claims haven't been extracted/inserted into the `claims` table yet, so
  nothing exists in `gold_labels` either. This is the last Phase 0 milestone.
