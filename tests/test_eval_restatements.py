from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from crosscheck.evaluation.restatements import (
    dump_candidates,
    find_restatements,
    load_candidates,
    load_confirmed_cases,
    period_label,
    restatement_pairs,
    to_claim,
)
from crosscheck.models import Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "companyfacts_restatement.json"


def _candidates():
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return find_restatements(facts, "DHR", "0000313616", "Danaher Corporation")


def test_detects_value_change_across_filings():
    cands = [c for c in _candidates() if c.period == "FY2019-Q2"]
    assert len(cands) == 1
    c = cands[0]
    assert (c.tag, c.unit, c.start, c.end) == (
        "Revenues",
        "USD",
        date(2019, 4, 1),
        date(2019, 6, 28),
    )
    assert c.canonical_metric_key == "revenue.total"
    assert c.period == "FY2019-Q2"
    assert [v.value for v in c.values] == [Decimal("1000"), Decimal("900"), Decimal("900")]
    pairs = restatement_pairs(c)
    assert len(pairs) == 1
    assert (pairs[0][0].value, pairs[0][1].value) == (Decimal("1000"), Decimal("900"))


def test_detects_ytd_and_annual():
    by_period = {c.period: c for c in _candidates()}
    assert set(by_period) == {"FY2019-Q2", "FY2019-9M", "FY2019"}
    assert [v.value for v in by_period["FY2019-9M"].values] == [Decimal("2800"), Decimal("2700")]
    assert [v.value for v in by_period["FY2019"].values] == [Decimal("4000"), Decimal("3900")]


def test_ignores_durations_outside_the_accepted_windows():
    # The fixture holds a restated 45-day fact and a restated 2017 quarter: neither is detected.
    assert len(_candidates()) == 3


def test_period_label():
    assert period_label(date(2019, 4, 1), date(2019, 6, 28)) == "FY2019-Q2"
    assert period_label(date(2019, 1, 1), date(2019, 6, 28)) == "FY2019-6M"
    assert period_label(date(2019, 1, 1), date(2019, 9, 27)) == "FY2019-9M"
    assert period_label(date(2019, 1, 1), date(2019, 12, 31)) == "FY2019"
    assert period_label(date(2019, 5, 1), date(2019, 6, 15)) is None


def test_to_claim():
    c = _candidates()[0]
    claim = to_claim(c, c.values[1], document_id=7)
    assert (claim.metric, claim.value, claim.extraction_method, claim.confidence) == (
        "Revenues",
        Decimal("900"),
        "automated_xbrl",
        1.0,
    )
    assert (claim.document_id, claim.period, claim.subject) == (7, "FY2019-Q2", c.subject)


def test_candidates_roundtrip(tmp_path):
    cands = _candidates()
    path = tmp_path / "c.json"
    dump_candidates(cands, path)
    assert load_candidates(path) == cands


def _causes(tmp_path, cause="restatement", reviewed=True, periods=("FY2019-Q2",)):
    c = {c.period: c for c in _candidates()}
    covers = []
    for p in periods:
        a, b = restatement_pairs(c[p])[0]
        covers.append(
            {"tag": c[p].tag, "period": p, "accession_a": a.accession, "accession_b": b.accession}
        )
    path = tmp_path / "causes.json"
    path.write_text(
        json.dumps(
            {
                "root_causes": [
                    {
                        "id": "rc1",
                        "cause": cause,
                        "ticker": "DHR",
                        "source_accession": "x",
                        "source_document": "x.htm",
                        "quote": "q",
                        "user_reviewed": reviewed,
                        "covers": covers,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_unreviewed_or_missing_cause_is_excluded_not_defaulted(tmp_path):
    # FY2019-Q2 is covered by an unreviewed cause; FY2019-9M has no coverage at all.
    path = _causes(tmp_path, reviewed=False)
    cands = [c for c in _candidates() if c.period in ("FY2019-Q2", "FY2019-9M")]
    cases, stats = load_confirmed_cases(cands, path)
    assert cases == []
    assert (stats["excluded_unreviewed"], stats["excluded_no_cause"]) == (1, 1)


def test_reviewed_cause_yields_discrepant_case_with_stable_id(tmp_path):
    path = _causes(tmp_path)
    cands = [c for c in _candidates() if c.period == "FY2019-Q2"]
    cases, stats = load_confirmed_cases(cands, path)
    assert len(cases) == 1 and stats["root_causes"] == 1
    assert (cases[0].gold, cases[0].cause, cases[0].root_cause_id) == (
        Verdict.DISCREPANT,
        "restatement",
        "rc1",
    )
    assert cases[0].claim_a.value != cases[0].claim_b.value
    assert cases[0].claim_a.document_id < 0 and cases[0].claim_b.document_id < 0
    assert load_confirmed_cases(cands, path)[0][0].case_id == cases[0].case_id


def test_stock_split_gold_is_ambiguous(tmp_path):
    path = _causes(tmp_path, cause="stock_split")
    cases, _ = load_confirmed_cases(_candidates(), path)
    assert [c.gold for c in cases] == [Verdict.AMBIGUOUS]


def test_unknown_cause_raises(tmp_path):
    path = _causes(tmp_path, cause="typo")
    with pytest.raises(ValueError):
        load_confirmed_cases(_candidates(), path)


def test_rounding_gold_is_consistent(tmp_path):
    path = _causes(tmp_path, cause="rounding")
    cases, _ = load_confirmed_cases(_candidates(), path)
    assert [(c.gold, c.cause) for c in cases] == [(Verdict.CONSISTENT, "rounding")]
