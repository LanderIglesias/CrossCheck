"""Automated Claim extraction from SEC EDGAR companyfacts JSON (real XBRL facts, no NLP/LLM).

Only a small, explicit set of us-gaap tags is mapped — the ones with a hand-labeled counterpart
in the Phase 0 gold set (see scripts/populate_phase0_gold_labels.py) — not all ~600 tags a
company's companyfacts JSON can contain. Extending coverage is a matter of adding entries to
TAG_TO_CANONICAL_KEY, not a design change.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from crosscheck.models import Claim, EvidenceSpan, SpanType, XBRLFactSpan

# Real, non-obvious wrinkle: companyfacts' per-tag time series repeats the same accn for multiple
# overlapping periods within one filing (prior-year comparatives, year-to-date, and the quarter
# itself) — the accession number alone does not identify the quarterly fact. We additionally
# require the fact's start/end duration to be roughly one fiscal quarter (~80-100 days), which is
# what distinguishes the quarterly figure from 9-month-YTD or prior-year entries in that filing.
_MIN_QUARTER_DAYS = 80
_MAX_QUARTER_DAYS = 100

# canonical_metric_key, metric label -> matches scripts/populate_phase0_gold_labels.py's taxonomy.
# Real cross-company divergence, confirmed by inspecting all 5 companies' actual cached
# companyfacts JSON: revenue is tagged RevenueFromContractWithCustomerExcludingAssessedTax for
# PPC/DHR/ADTN but plain Revenues for GE/TRV (insurer/conglomerate revenue recognition, not
# ASC606-labeled) -- both map to the same canonical_metric_key, since they're the same fact.
TAG_TO_CANONICAL_KEY: dict[str, tuple[str, str]] = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": (
        "revenue.total",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ),
    "Revenues": ("revenue.total", "Revenues"),
    "NetIncomeLoss": ("income.net", "NetIncomeLoss"),
    "EarningsPerShareDiluted": ("eps.diluted.gaap", "EarningsPerShareDiluted"),
    "EarningsPerShareBasic": ("eps.basic.gaap", "EarningsPerShareBasic"),
    "IncomeLossFromContinuingOperationsPerDilutedShare": (
        "eps.diluted.continuing.gaap",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ),
    "GrossProfit": ("gross_profit", "GrossProfit"),
}

# XBRL's raw unit keys (e.g. "USD/shares") don't match the unit-string convention already
# established across all 64 hand-labeled gold claims (e.g. "USD_per_share",
# see scripts/populate_phase0_gold_labels.py) -- normalize so automated and manual claims for the
# same metric are actually comparable, not spuriously "mismatched" on unit spelling alone.
_UNIT_KEY_NORMALIZATION: dict[str, str] = {
    "USD/shares": "USD_per_share",
}


def _normalize_unit(unit_key: str) -> str:
    return _UNIT_KEY_NORMALIZATION.get(unit_key, unit_key)


def _is_quarterly_fact(fact: dict[str, Any], accession_number: str) -> bool:
    # accn (the filing's real SEC accession number) is the authoritative "this specific filing"
    # identifier -- unlike fy/fp, which can be genuinely wrong (confirmed real case: GE's own
    # companyfacts JSON tags its FY2020-Q1 10-Q fact fy=2019/fp="Q3", even though the fact's own
    # start/end dates and accn correctly identify it as the Q1 2020 quarterly figure).
    if fact.get("accn") != accession_number or fact.get("form") != "10-Q":
        return False
    start = date.fromisoformat(fact["start"])
    end = date.fromisoformat(fact["end"])
    duration_days = (end - start).days
    return _MIN_QUARTER_DAYS <= duration_days <= _MAX_QUARTER_DAYS


def _find_quarterly_fact(
    facts: list[dict[str, Any]], accession_number: str
) -> dict[str, Any] | None:
    matches = [f for f in facts if _is_quarterly_fact(f, accession_number)]
    if not matches:
        return None
    # If more than one still matches (shouldn't happen for one accn + duration window, but be
    # explicit rather than silently picking one), take the most recently filed.
    matches.sort(key=lambda f: f["filed"])
    return matches[-1]


def extract_claims(
    company_facts: dict[str, Any],
    document_id: int,
    subject: str,
    period: str,
    accession_number: str,
) -> list[tuple[Claim, EvidenceSpan]]:
    """Extract (Claim, EvidenceSpan) pairs for the mapped tags found in `company_facts`.

    Tags absent from `company_facts` (e.g. this company doesn't report them) or with no matching
    quarterly fact are silently skipped, not errored — a real company's XBRL data legitimately
    doesn't cover every tag we might look for.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    results: list[tuple[Claim, EvidenceSpan]] = []
    # Real edge case: a company could report the same canonical_metric_key under two different
    # mapped tags (e.g. a legacy tag alongside the current one). Keep only the first match, in
    # TAG_TO_CANONICAL_KEY's own order, rather than silently emitting a duplicate claim.
    seen_canonical_keys: set[str] = set()

    for tag, (canonical_key, metric_label) in TAG_TO_CANONICAL_KEY.items():
        if canonical_key in seen_canonical_keys:
            continue
        tag_data = us_gaap.get(tag)
        if tag_data is None:
            continue
        units = tag_data.get("units", {})
        for unit_key, facts in units.items():
            fact = _find_quarterly_fact(facts, accession_number)
            if fact is None:
                continue

            seen_canonical_keys.add(canonical_key)
            claim = Claim(
                document_id=document_id,
                subject=subject,
                metric=metric_label,
                canonical_metric_key=canonical_key,
                period=period,
                value=Decimal(str(fact["val"])),
                unit=_normalize_unit(unit_key),
                qualifier=None,
                speaker=None,
                extraction_method="automated_xbrl",
                model_id=None,
                prompt_hash=None,
                confidence=1.0,
            )
            span = EvidenceSpan(
                claim_id=-1,  # placeholder; caller fills in the real claim_id after INSERT
                span_type=SpanType.XBRL_FACT,
                span_json=XBRLFactSpan(
                    tag=tag,
                    # companyfacts JSON carries no raw XBRL contextRef; accn (accession number)
                    # uniquely identifies the source filing instance and is the closest available
                    # substitute — a documented approximation, not the literal XBRL element.
                    context_ref=fact["accn"],
                    unit_ref=unit_key,
                ),
            )
            results.append((claim, span))

    return results
