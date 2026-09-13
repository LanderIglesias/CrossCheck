from decimal import Decimal

from crosscheck.consistency.checker import check_pair, generate_predictions
from crosscheck.models import Claim, Verdict


def _claim(
    document_id: int, canonical_metric_key: str, value, unit: str, period="FY2020-Q3", subject="X"
):
    return Claim(
        document_id=document_id,
        subject=subject,
        metric=canonical_metric_key,
        canonical_metric_key=canonical_metric_key,
        period=period,
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        extraction_method="manual",
    )


def test_within_tolerance_is_consistent():
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1003000", "USD")  # 0.3% apart
    verdict, _ = check_pair(a, b)
    assert verdict == Verdict.CONSISTENT


def test_outside_tolerance_is_discrepant():
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1050000", "USD")  # 5% apart
    verdict, _ = check_pair(a, b)
    assert verdict == Verdict.DISCREPANT


def test_exact_tolerance_boundary_is_consistent():
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1005000", "USD")  # exactly 0.5% apart
    verdict, _ = check_pair(a, b)
    assert verdict == Verdict.CONSISTENT


def test_just_over_boundary_is_discrepant():
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1006000", "USD")  # ~0.6% apart (relative to the larger value)
    verdict, _ = check_pair(a, b)
    assert verdict == Verdict.DISCREPANT


def test_unconvertible_units_is_ambiguous_not_a_guess():
    a = _claim(1, "combined_ratio.underlying", "91.4", "pct")
    b = _claim(2, "combined_ratio.underlying", "9140", "bps")
    verdict, rationale = check_pair(a, b)
    assert verdict == Verdict.AMBIGUOUS
    assert "no known unit conversion" in rationale.lower()


def test_singleton_group_is_unsupported_with_no_claim_b():
    claims = [_claim(1, "cashflow.free", "694000000", "USD")]
    predictions = generate_predictions(claims)
    assert len(predictions) == 1
    assert predictions[0].verdict == Verdict.UNSUPPORTED
    assert predictions[0].claim_b is None


def test_same_document_claims_are_never_paired():
    # Two claims from the same document_id (e.g. two tags extracted from one xbrl document)
    # sharing a metric key would be a data error, not a cross-modality comparison -- must be
    # skipped, not compared.
    claims = [
        _claim(1, "revenue.total", "1000000", "USD"),
        _claim(1, "revenue.total", "1000000", "USD"),
    ]
    predictions = generate_predictions(claims)
    assert predictions == []


def test_generates_pairwise_predictions_across_group():
    claims = [
        _claim(1, "revenue.total", "1000000", "USD"),
        _claim(2, "revenue.total", "1001000", "USD"),
        _claim(3, "revenue.total", "2000000", "USD"),
    ]
    predictions = generate_predictions(claims)
    assert len(predictions) == 3  # C(3,2)
    verdicts = {p.verdict for p in predictions}
    assert Verdict.CONSISTENT in verdicts
    assert Verdict.DISCREPANT in verdicts


def test_different_companies_sharing_a_period_string_are_never_compared():
    """Regression for a real bug found running this against all 5 companies at once: period
    strings are not globally unique (e.g. PPC and ADTN both use "FY2020-Q3"). Without `subject`
    in the grouping key, their unrelated revenue claims were grouped together and predicted
    discrepant against each other -- a false positive, not a real cross-company discrepancy."""
    claims = [
        _claim(1, "revenue.total", "1000000", "USD", subject="Company A"),
        _claim(2, "revenue.total", "9999999", "USD", subject="Company B"),  # wildly different
    ]
    predictions = generate_predictions(claims)
    # Each company's lone claim is unsupported on its own -- never paired cross-company.
    assert len(predictions) == 2
    assert all(p.verdict == Verdict.UNSUPPORTED and p.claim_b is None for p in predictions)
