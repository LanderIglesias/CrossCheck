import json
from decimal import Decimal
from pathlib import Path

import pytest

from crosscheck.consistency.checker import check_pair
from crosscheck.evaluation.blind import pair_key
from crosscheck.evaluation.mutations import (
    VALUE_SIZES,
    MutationType,
    NeighborValues,
    dump_mutations,
    generate_mutations,
    load_mutations,
    mutated_value,
    neighbor_values,
)
from crosscheck.models import Claim, Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "companyfacts_neighbors.json"
EPS = Decimal("0.0001")


def _claim(value, doc=1, method="automated_xbrl", period="FY2020-Q2", unit="USD"):
    return Claim(
        document_id=doc,
        subject="X",
        metric="Revenues",
        canonical_metric_key="revenue.total",
        period=period,
        value=Decimal(value) if value is not None else None,
        unit=unit,
        extraction_method=method,
    )


def _pair(value):
    return _claim(value), _claim(value, doc=2, method="manual")


@pytest.mark.parametrize("base", ["3000000000", "0.72", "-125400000"])
@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("size", VALUE_SIZES)
def test_value_mutation_hits_exact_relative_diff(base, direction, size):
    a = _claim(base)
    b = _claim(base, doc=2).model_copy(update={"value": mutated_value(a.value, size, direction)})
    verdict, _ = check_pair(a, b)
    denom = max(abs(a.value), abs(b.value))
    assert abs(abs(a.value - b.value) / denom - size) <= EPS / 10
    if size == Decimal("0.0049"):
        assert verdict == Verdict.CONSISTENT
    if size == Decimal("0.0051"):
        assert verdict == Verdict.DISCREPANT


def test_generated_value_mutations_cover_all_sizes():
    muts, _ = generate_mutations([_pair("1000")], {}, seed=1)
    value_muts = [m for m in muts if m.type == MutationType.VALUE]
    assert [m.size for m in value_muts] == list(VALUE_SIZES)
    assert all(m.direction in (-1, 1) for m in value_muts)


def test_zero_base_is_skipped_and_counted():
    muts, skips = generate_mutations([_pair("0")], {}, seed=1)
    assert not [m for m in muts if m.type in (MutationType.VALUE, MutationType.UNIT_X1000)]
    assert skips["zero_base"] == 1


def test_zero_anchor_with_zero_neighbor_is_skipped_not_divided():
    a, b = _pair("0")
    nb = {pair_key(a, b): NeighborValues(prev_quarter=Decimal("0"), ytd=Decimal("5"))}
    muts, skips = generate_mutations([(a, b)], nb, seed=1)
    assert not [m for m in muts if m.type == MutationType.PERIOD_PREV]
    assert [m.claim_b.value for m in muts if m.type == MutationType.PERIOD_YTD] == [Decimal("5")]
    assert skips["zero_base"] == 2  # the anchor itself and the 0/0 neighbour


def test_unit_mutation_multiplies_by_1000_keeps_unit_label():
    a, b = _pair("2500")
    muts, _ = generate_mutations([(a, b)], {}, seed=1)
    (m,) = [m for m in muts if m.type == MutationType.UNIT_X1000]
    assert m.claim_b.value == Decimal("2500000")
    assert m.claim_b.unit == b.unit
    assert m.size is None and m.direction is None


def test_period_mutation_uses_neighbor_value_and_correct_label():
    a, b = _pair("1000")
    nb = {pair_key(a, b): NeighborValues(prev_quarter=Decimal("800"), ytd=Decimal("1003"))}
    muts, skips = generate_mutations([(a, b)], nb, seed=1)
    (m,) = [m for m in muts if m.type == MutationType.PERIOD_PREV]
    assert m.claim_b.period == m.claim_a.period == a.period
    assert m.claim_b.value == Decimal("800")
    assert not [m for m in muts if m.type == MutationType.PERIOD_YTD]
    assert skips["neighbor_within_tolerance"] == 1  # 1003 vs 1000 is within 0.5 %


def test_missing_neighbor_is_counted():
    _, skips = generate_mutations([_pair("1000")], {}, seed=1)
    assert skips["no_neighbor"] == 2


def test_same_seed_same_output_different_seed_differs():
    pairs = [_pair(str(1000 + i)) for i in range(5)]
    one, _ = generate_mutations(pairs, {}, seed=7)
    again, _ = generate_mutations(pairs, {}, seed=7)
    other, _ = generate_mutations(pairs, {}, seed=8)
    assert one == again
    assert one != other
    rev, _ = generate_mutations(pairs[::-1], {}, seed=7)
    assert {m.mutation_id for m in rev} == {m.mutation_id for m in one}


def test_dump_load_roundtrip(tmp_path):
    a, b = _pair("1000")
    nb = {pair_key(a, b): NeighborValues(Decimal("800"), None)}
    muts, _ = generate_mutations([(a, b)], nb, seed=3)
    path = tmp_path / "sub" / "mutations.json"
    dump_mutations(muts, path)
    assert load_mutations(path) == muts


def test_neighbor_values_from_fixture():
    facts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    q2 = neighbor_values(facts, "revenue.total", "0000000002-20-000002")
    assert q2 == NeighborValues(prev_quarter=Decimal("400"), ytd=Decimal("910"))
    q1 = neighbor_values(facts, "revenue.total", "0000000002-20-000001")
    assert q1 == NeighborValues(None, None)
    missing = neighbor_values(facts, "income.net", "0000000002-20-000002")
    assert missing == NeighborValues(None, None)
