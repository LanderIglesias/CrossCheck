"""Phase 10: freeze the real XBRL restatement candidates into eval/phase10/restatement_candidates.json.

Reads each company's companyfacts from the EDGAR cache (no network on a cache hit) and keeps every
(tag, unit, start, end) duration with end.year in 2019-2020, reported in 10-Q/10-K filings, with
>= 2 distinct values across accessions. Accepted durations: quarter 80-100 days (FY2019-Q2),
6-month YTD 170-190 (FY2019-6M), 9-month YTD 260-280 (FY2019-9M), full year 350-380 (FY2019).
Committed because data/raw/ is gitignored and companyfacts grows over time.

Definition note: the spec's exploratory count (DHR 39, GE 30, others 0) did not record its exact
definition. Counting all durations as above gives PPC 0, DHR 28, GE 30, TRV 0, ADTN 0: GE and the
zeros match the spec; DHR 28 vs 39 is unexplained (quarter-only gave DHR 15, GE 15). Filters were
not tuned to match.
"""

from __future__ import annotations

from pathlib import Path

from extract_xbrl_claims import COMPANIES

from crosscheck.evaluation.restatements import (
    RestatementCandidate,
    dump_candidates,
    find_restatements,
)
from crosscheck.sources.edgar import fetch_company_facts

# From db/seed_companies.sql.
CIKS = {
    "PPC": "0000802481",
    "DHR": "0000313616",
    "GE": "0000040545",
    "TRV": "0000086312",
    "ADTN": "0000926282",
}
OUT = Path(__file__).resolve().parent.parent / "eval" / "phase10" / "restatement_candidates.json"


def main() -> None:
    all_cands: list[RestatementCandidate] = []
    for co in COMPANIES:
        cik = CIKS[co.ticker]
        cands = find_restatements(fetch_company_facts(cik), co.ticker, cik, co.subject)
        print(f"{co.ticker}: {len(cands)}")
        all_cands.extend(cands)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    dump_candidates(all_cands, OUT)
    print(f"Wrote {len(all_cands)} candidates to {OUT}")


if __name__ == "__main__":
    main()
