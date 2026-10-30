"""Harness behaviour with a fake judge: no DB, no API."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from eval_phase10_run import Item, judge_row  # noqa: E402

from crosscheck.consistency.checker import Prediction  # noqa: E402
from crosscheck.evaluation.budget import BudgetExceededError, BudgetGuard  # noqa: E402
from crosscheck.models import Claim, Verdict  # noqa: E402


def _item() -> Item:
    c = Claim(
        document_id=-1,
        subject="X",
        metric="m",
        canonical_metric_key="k",
        period="p",
        value=Decimal(1),
        unit="USD",
        extraction_method="manual",
    )
    return Item("i", "injected", c, c, "discrepant", mutation_type="value", size="0.05")


def _fake(usage):
    def judge(a, b, repeat):
        return Prediction(claim_a=a, claim_b=b, verdict=Verdict.DISCREPANT, rationale="r"), usage

    return judge


def test_live_call_records_usage():
    g = BudgetGuard()
    row = judge_row(_item(), 0, g, _fake({"input_tokens": 1000, "output_tokens": 100}))
    assert row["live"] and row["cost_usd"] == pytest.approx(0.003) and g.live_calls == 1


def test_cache_hit_is_free_but_still_guarded():
    g = BudgetGuard(cap_usd=0.0)
    with pytest.raises(BudgetExceededError):
        judge_row(_item(), 0, g, _fake(None))
    g = BudgetGuard()
    row = judge_row(_item(), 0, g, _fake(None))
    assert not row["live"] and g.live_calls == 0 and row["predicted"] == "discrepant"


def test_runtime_error_counts_as_failure():
    def boom(a, b, repeat):
        raise RuntimeError("rate limited")

    g = BudgetGuard()
    row = judge_row(_item(), 0, g, boom)
    assert row["error"] == "rate limited" and row["predicted"] is None and g.failed_calls == 1
