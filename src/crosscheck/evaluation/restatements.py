"""Detect XBRL facts whose value differs across the SEC filings that publish them (Phase 10).

companyfacts repeats a (tag, period) in every filing that reports it, including later filings
that show it as a prior-year comparative. When those filings disagree, the company restated (or
recast) the figure: a real, naturally occurring cross-document discrepancy, with no injected
error. A candidate is one (tag, unit, start, end) duration (quarter, YTD or year) with >= 2 distinct values.

Candidates are frozen to JSON because data/raw/ (the EDGAR cache) is gitignored and companyfacts
grows over time; the committed file keeps the evaluation reproducible.
"""

from __future__ import annotations

import hashlib
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
from crosscheck.models import Claim, Verdict

_FORMS = ("10-Q", "10-K")
# Year-to-date and full-year windows (days), next to xbrl.py's quarter window.
_MIN_6M_DAYS, _MAX_6M_DAYS = 170, 190
_MIN_9M_DAYS, _MAX_9M_DAYS = 260, 280
_MIN_YEAR_DAYS, _MAX_YEAR_DAYS = 350, 380


@dataclass(frozen=True)
class FilingValue:
    accession: str
    form: str
    filed: date
    value: Decimal


CAUSES = ("restatement", "recast_discontinued_ops", "stock_split", "error", "rounding")


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


def period_label(start: date, end: date) -> str | None:
    """Label of a duration, or None if its length is not accepted.

    Quarter (80-100 days) -> "FY2019-Q2"; 6-month YTD (170-190) -> "FY2019-6M"; 9-month YTD
    (260-280) -> "FY2019-9M"; full year (350-380) -> "FY2019". The year and quarter come from
    the end date, which is only valid for companies whose fiscal year equals the calendar year
    (DHR and GE close the fiscal year in December).
    """
    days = (end - start).days
    if _MIN_QUARTER_DAYS <= days <= _MAX_QUARTER_DAYS:
        return f"FY{end.year}-Q{(end.month - 1) // 3 + 1}"
    if _MIN_6M_DAYS <= days <= _MAX_6M_DAYS:
        return f"FY{end.year}-6M"
    if _MIN_9M_DAYS <= days <= _MAX_9M_DAYS:
        return f"FY{end.year}-9M"
    if _MIN_YEAR_DAYS <= days <= _MAX_YEAR_DAYS:
        return f"FY{end.year}"
    return None


def find_restatements(
    company_facts: dict[str, Any],
    ticker: str,
    cik: str,
    subject: str,
    years: tuple[int, ...] = (2019, 2020),
) -> list[RestatementCandidate]:
    """Facts with an accepted duration (see period_label), end.year in `years`, reported in
    10-Q/10-K, with >= 2 distinct values across accessions.

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
                if period_label(start, end) is None or end.year not in years:
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
                        period_label(start, end) or "",
                        start,
                        end,
                        values,
                    )
                )
    return out


def restatement_pairs(c: RestatementCandidate) -> list[tuple[FilingValue, FilingValue]]:
    """First published value against each later distinct value (its earliest filing).

    A later value equal to the first (a revert) yields no pair.
    """
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


_CAUSE_GOLD = {"stock_split": Verdict.AMBIGUOUS, "rounding": Verdict.CONSISTENT}


@dataclass(frozen=True)
class RealCase:
    case_id: str
    claim_a: Claim
    claim_b: Claim
    gold: Verdict
    cause: str
    root_cause_id: str


def load_confirmed_cases(
    candidates: list[RestatementCandidate], causes_path: Path
) -> tuple[list[RealCase], dict[str, int]]:
    """Gold-labeled cases for the restatement pairs whose cause a human reviewed.

    A pair enters only if a root cause with user_reviewed=true covers it (ticker, tag, period and
    both accessions). Pairs with no cause, or only an unreviewed one, are counted and left out:
    a cause is never guessed. Gold is `ambiguous` for stock_split (the figures are not comparable
    without adjusting for the split), `consistent` for rounding (a presentation-only
    difference: a trap, not an error) and `discrepant` otherwise. case_id is a hash of
    ticker|tag|period|accession_a|accession_b, so it survives reordering; claims get unique
    negative document_ids (they are never persisted).
    """
    root_causes = json.loads(causes_path.read_text(encoding="utf-8"))["root_causes"]
    by_pair = {}
    for rc in root_causes:
        if rc["cause"] not in CAUSES:
            raise ValueError(f"unknown cause {rc['cause']!r} in root cause {rc['id']!r}")
        for cv in rc["covers"]:
            key = (rc["ticker"], cv["tag"], cv["period"], cv["accession_a"], cv["accession_b"])
            by_pair[key] = rc
    cases: list[RealCase] = []
    stats = {"excluded_no_cause": 0, "excluded_unreviewed": 0, "root_causes": 0}
    used: set[str] = set()
    next_id = -1
    for c in candidates:
        for a, b in restatement_pairs(c):
            key = (c.ticker, c.tag, c.period, a.accession, b.accession)
            rc = by_pair.get(key)
            if rc is None:
                stats["excluded_no_cause"] += 1
                continue
            if not rc["user_reviewed"]:
                stats["excluded_unreviewed"] += 1
                continue
            gold = _CAUSE_GOLD.get(rc["cause"], Verdict.DISCREPANT)
            case_id = hashlib.sha256("|".join(key).encode()).hexdigest()[:12]
            cases.append(
                RealCase(
                    case_id,
                    to_claim(c, a, next_id),
                    to_claim(c, b, next_id - 1),
                    gold,
                    rc["cause"],
                    rc["id"],
                )
            )
            next_id -= 2
            used.add(rc["id"])
    stats["root_causes"] = len(used)
    return cases, stats
