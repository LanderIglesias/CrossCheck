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
    cands = _candidates()
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


def test_ignores_non_quarterly_and_out_of_range_years():
    # The fixture also holds a 9-month fact (restated) and a 2017 quarter (restated).
    assert len(_candidates()) == 1


def test_period_label():
    assert period_label(date(2019, 6, 28)) == "FY2019-Q2"


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
