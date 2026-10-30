from __future__ import annotations

import pytest

from crosscheck.evaluation.budget import BudgetExceededError, BudgetGuard


def test_stops_before_exceeding_cap():
    guard = BudgetGuard(cap_usd=0.01)
    guard.record_usage({"input_tokens": 2000, "output_tokens": 200})
    with pytest.raises(BudgetExceededError):
        guard.check_can_call()


def test_failure_counts_against_budget():
    guard = BudgetGuard()
    guard.record_failure()
    assert guard.spent_usd > 0 and guard.failed_calls == 1


def test_cost_matches_pricing():
    guard = BudgetGuard()
    assert guard.record_usage({"input_tokens": 1_000_000, "output_tokens": 0}) == 2.0
    assert guard.live_calls == 1
