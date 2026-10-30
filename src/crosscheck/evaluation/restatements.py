"""Detect XBRL facts whose value differs across the SEC filings that publish them (Phase 10).

companyfacts repeats a (tag, period) in every filing that reports it, including later filings
that show it as a prior-year comparative. When those filings disagree, the company restated (or
recast) the figure: a real, naturally occurring cross-document discrepancy, with no injected
error. A candidate is one (tag, unit, start, end) quarterly duration with >= 2 distinct values.

Candidates are frozen to JSON because data/raw/ (the EDGAR cache) is gitignored and companyfacts
grows over time; the committed file keeps the evaluation reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from crosscheck.extraction.xbrl import (
    _MAX_QUARTER_DAYS,
    _MIN_QUARTER_DAYS,
    TAG_TO_CANONICAL_KEY,
    _normalize_unit,
)
from crosscheck.models import Claim

_FORMS = ("10-Q", "10-K")


@dataclass(frozen=True)
class FilingValue:
    accession: str
    form: str
    filed: date
    value: Decimal


@dataclass(frozen=True)
class RestatementCandidate:
    ticker: str
    cik: str
    subject: str
    tag: str
    canonical_metric_key: str
    unit: str
    period: str
    start: date
    end: date
    values: tuple[FilingValue, ...]


def period_label(end: date) -> str:
    """Calendar-quarter label of a period end date, e.g. 2019-06-28 -> "FY2019-Q2".

    Only valid for companies whose fiscal year ends in December (DHR and GE).
    """
    return f"FY{end.year}-Q{(end.month - 1) // 3 + 1}"


def find_restatements(
    company_facts: dict[str, Any],
    ticker: str,
    cik: str,
    subject: str,
    years: tuple[int, ...] = (2019, 2020),
) -> list[RestatementCandidate]:
    """Quarterly facts (80-100 days, end.year in `years`, 10-Q/10-K) with >= 2 distinct values.

    One value per accession (the latest `filed` if an accession repeats the fact).
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    out: list[RestatementCandidate] = []
    for tag, (canonical_key, _label) in TAG_TO_CANONICAL_KEY.items():
        for unit_key, facts in us_gaap.get(tag, {}).get("units", {}).items():
            groups: dict[tuple[date, date], dict[str, FilingValue]] = {}
            for f in facts:
                if f.get("form") not in _FORMS or "start" not in f:
                    continue
                start, end = date.fromisoformat(f["start"]), date.fromisoformat(f["end"])
                if not _MIN_QUARTER_DAYS <= (end - start).days <= _MAX_QUARTER_DAYS:
                    continue
                if end.year not in years:
                    continue
                fv = FilingValue(
                    f["accn"], f["form"], date.fromisoformat(f["filed"]), Decimal(str(f["val"]))
                )
                by_accn = groups.setdefault((start, end), {})
                if f["accn"] not in by_accn or fv.filed >= by_accn[f["accn"]].filed:
                    by_accn[f["accn"]] = fv
            for (start, end), by_accn in groups.items():
                values = tuple(sorted(by_accn.values(), key=lambda v: (v.filed, v.accession)))
                if len({v.value for v in values}) < 2:
                    continue
                out.append(
                    RestatementCandidate(
                        ticker,
                        cik,
                        subject,
                        tag,
                        canonical_key,
                        _normalize_unit(unit_key),
                        period_label(end),
                        start,
                        end,
                        values,
                    )
                )
    return out


def restatement_pairs(c: RestatementCandidate) -> list[tuple[FilingValue, FilingValue]]:
    """First published value against each later distinct value (its earliest filing)."""
    first = c.values[0]
    seen = {first.value}
    pairs = []
    for v in c.values[1:]:
        if v.value not in seen:
            seen.add(v.value)
            pairs.append((first, v))
    return pairs


def to_claim(c: RestatementCandidate, fv: FilingValue, document_id: int) -> Claim:
    """In-memory Claim for one filing's value; never persisted."""
    return Claim(
        document_id=document_id,
        subject=c.subject,
        metric=c.tag,
        canonical_metric_key=c.canonical_metric_key,
        period=c.period,
        value=fv.value,
        unit=c.unit,
        extraction_method="automated_xbrl",
        confidence=1.0,
    )


def dump_candidates(cands: list[RestatementCandidate], path: Path) -> None:
    def enc(c: RestatementCandidate) -> dict[str, Any]:
        return {
            "ticker": c.ticker,
            "cik": c.cik,
            "subject": c.subject,
            "tag": c.tag,
            "canonical_metric_key": c.canonical_metric_key,
            "unit": c.unit,
            "period": c.period,
            "start": c.start.isoformat(),
            "end": c.end.isoformat(),
            "values": [
                {
                    "accession": v.accession,
                    "form": v.form,
                    "filed": v.filed.isoformat(),
                    "value": str(v.value),
                }
                for v in c.values
            ],
        }

    path.write_text(json.dumps([enc(c) for c in cands], indent=2) + "\n", encoding="utf-8")


def load_candidates(path: Path) -> list[RestatementCandidate]:
    return [
        RestatementCandidate(
            d["ticker"],
            d["cik"],
            d["subject"],
            d["tag"],
            d["canonical_metric_key"],
            d["unit"],
            d["period"],
            date.fromisoformat(d["start"]),
            date.fromisoformat(d["end"]),
            tuple(
                FilingValue(
                    v["accession"],
                    v["form"],
                    date.fromisoformat(v["filed"]),
                    Decimal(v["value"]),
                )
                for v in d["values"]
            ),
        )
        for d in json.loads(path.read_text(encoding="utf-8"))
    ]
