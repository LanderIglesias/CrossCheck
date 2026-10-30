"""Phase 10: print keyword passages from the filings that restate each candidate (read-only).

For every later accession in eval/phase10/restatement_candidates.json, download the primary
document (cached EDGAR client), extract its text and print the passages (+-400 chars) around
recast / discontinued operation / retrospectively / restat / reverse stock split / as adjusted,
with their character offset in extract_text(html). Used to draft restatement_causes.json by hand:
a quote there must be a literal substring of that same extracted text. Writes nothing.

Run from the repo root: python scripts/eval_phase10_fetch_restating_filings.py [TICKER]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from crosscheck.evaluation.restatements import load_candidates, restatement_pairs
from crosscheck.ingest.filing_text import extract_text
from crosscheck.sources.edgar import _get_json, fetch_filing_document, fetch_submissions

CANDIDATES = (
    Path(__file__).resolve().parent.parent / "eval" / "phase10" / "restatement_candidates.json"
)
KEYWORDS = re.compile(
    r"recast|discontinued operation|retrospectively|restat|reverse stock split|as adjusted",
    re.IGNORECASE,
)
WINDOW = 400


def primary_documents(cik: str) -> dict[str, str]:
    """accession -> primaryDocument from submissions' recent block and its older-history pages."""
    sub = fetch_submissions(cik)
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        blocks.append(_get_json(f"https://data.sec.gov/submissions/{f['name']}"))
    return {
        a: d
        for b in blocks
        for a, d in zip(b["accessionNumber"], b["primaryDocument"], strict=True)
    }


def passages(text: str) -> list[tuple[int, str]]:
    """Merged (+-WINDOW) windows around keyword hits: (start offset, text)."""
    spans: list[list[int]] = []
    for m in KEYWORDS.finditer(text):
        lo, hi = max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = hi
        else:
            spans.append([lo, hi])
    return [(lo, text[lo:hi]) for lo, hi in spans]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows cp1252 lacks U+2011
    only = sys.argv[1] if len(sys.argv) > 1 else None
    wanted: dict[tuple[str, str], str] = {}  # (ticker, accession) -> cik
    for c in load_candidates(CANDIDATES):
        if only and c.ticker != only:
            continue
        for _a, b in restatement_pairs(c):
            wanted[(c.ticker, b.accession)] = c.cik
    docs: dict[str, dict[str, str]] = {}
    for (ticker, accession), cik in sorted(wanted.items()):
        docs.setdefault(cik, primary_documents(cik))
        doc = docs[cik].get(accession)
        if doc is None:
            print(f"##### {ticker} {accession}: UNRESOLVED (not in submissions)")
            continue
        path, _hash = fetch_filing_document(cik, accession, doc)
        text = extract_text(path.read_text(encoding="utf-8", errors="replace"))
        found = passages(text)
        print(f"##### {ticker} {accession} {doc} ({len(found)} passages)")
        for offset, body in found:
            print(f"--- offset {offset}\n{body}\n")


if __name__ == "__main__":
    main()
