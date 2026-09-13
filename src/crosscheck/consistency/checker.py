"""Rule-based cross-modality consistency checker.

Mechanically applies the exact tolerance rules a human labeler used (see
src/crosscheck/labeling/protocol.md) to predict a Verdict for pairs of Claims describing the same
fact. Deliberately not LLM-based — protocol.md itself frames a later LLM-as-judge phase as
something to validate *against* a deterministic baseline, which is what this is.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from crosscheck.models import Claim, Verdict

TOLERANCE_PCT = Decimal("0.005")

# Empty for this vertical slice: PPC's real claims only use "USD" and "USD_per_share", so no
# cross-unit comparison (e.g. bps vs percent) is ever exercised here. Documented as extensible,
# not implemented speculatively for units that don't occur in the data at hand.
UNIT_CONVERSIONS: dict[tuple[str, str], Decimal] = {}


@dataclass(frozen=True)
class Prediction:
    claim_a: Claim
    claim_b: Claim | None
    verdict: Verdict
    rationale: str


def _convert(value: Decimal, unit_from: str, unit_to: str) -> Decimal | None:
    """Convert `value` from unit_from to unit_to, or None if no conversion is known."""
    if unit_from == unit_to:
        return value
    factor = UNIT_CONVERSIONS.get((unit_from, unit_to))
    if factor is not None:
        return value * factor
    inverse = UNIT_CONVERSIONS.get((unit_to, unit_from))
    if inverse is not None:
        return value / inverse
    return None


def check_pair(claim_a: Claim, claim_b: Claim) -> tuple[Verdict, str]:
    """Predict a Verdict for one candidate pair (same canonical_metric_key+period already
    assumed by the caller -- this function only handles unit conversion + tolerance)."""
    if claim_a.value is None or claim_b.value is None:
        return (
            Verdict.AMBIGUOUS,
            "One or both claims have no numeric value to compare.",
        )

    unit_a = claim_a.unit or ""
    unit_b = claim_b.unit or ""
    converted_b = _convert(claim_b.value, unit_b, unit_a)
    if converted_b is None:
        return (
            Verdict.AMBIGUOUS,
            f"No known unit conversion between {unit_b!r} and {unit_a!r} -- abstaining rather "
            "than guessing.",
        )

    value_a = claim_a.value
    denom = max(abs(value_a), abs(converted_b))
    if denom == 0:
        relative_diff = Decimal("0")
    else:
        relative_diff = abs(value_a - converted_b) / denom

    if relative_diff <= TOLERANCE_PCT:
        return (
            Verdict.CONSISTENT,
            f"{value_a} {unit_a} vs {claim_b.value} {unit_b} -- {relative_diff:.4%} apart, "
            f"within the {TOLERANCE_PCT:.1%} tolerance.",
        )
    return (
        Verdict.DISCREPANT,
        f"{value_a} {unit_a} vs {claim_b.value} {unit_b} -- {relative_diff:.4%} apart, "
        f"exceeds the {TOLERANCE_PCT:.1%} tolerance.",
    )


def group_by_metric_and_period(claims: list[Claim]) -> dict[tuple[str, str, str], list[Claim]]:
    """Group by (subject, canonical_metric_key, period) -- subject is required, not just metric
    key+period, because period strings are not globally unique across companies (real bug found
    running this against all 5 companies at once: PPC and ADTN both use period "FY2020-Q3", so
    without `subject` in the key, their unrelated revenue claims were grouped together and
    compared as if they described the same fact)."""
    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for claim in claims:
        key = (claim.subject, claim.canonical_metric_key, claim.period)
        groups.setdefault(key, []).append(claim)
    return groups


def generate_predictions(claims: list[Claim]) -> list[Prediction]:
    """Predict a Verdict for every candidate pair (or unsupported singleton) across `claims`.

    Claims sharing a document_id (e.g. Phase 3's automated_xbrl claim and the hand-labeled manual
    claim sourced from the same xbrl document) are never paired against each other -- they're the
    same source, not two independent modalities to cross-check.
    """
    predictions: list[Prediction] = []
    for (_subject, _metric_key, _period), group in group_by_metric_and_period(claims).items():
        if len(group) == 1:
            predictions.append(
                Prediction(
                    claim_a=group[0],
                    claim_b=None,
                    verdict=Verdict.UNSUPPORTED,
                    rationale="No other claim shares this canonical_metric_key+period.",
                )
            )
            continue

        for claim_a, claim_b in combinations(group, 2):
            if claim_a.document_id == claim_b.document_id:
                continue
            verdict, rationale = check_pair(claim_a, claim_b)
            predictions.append(
                Prediction(claim_a=claim_a, claim_b=claim_b, verdict=verdict, rationale=rationale)
            )

    return predictions
