from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from crosscheck.evaluation.restatements import (
    dump_candidates,
    find_restatements,
    load_candidates,
    period_label,
    restatement_pairs,
    to_claim,
)

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
