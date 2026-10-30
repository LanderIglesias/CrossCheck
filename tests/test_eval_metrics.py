from __future__ import annotations

from crosscheck.evaluation.metrics import precision_recall, wilson_interval


def test_wilson_known_value():
    lo, hi = wilson_interval(8, 10)
    assert round(lo, 3) == 0.490 and round(hi, 3) == 0.943


def test_wilson_empty():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_precision_recall_counts_and_none_when_undefined():
    r = precision_recall(
        [
            ("discrepant", "discrepant"),
            ("consistent", "discrepant"),
            ("discrepant", "consistent"),
        ]
    )
    assert (r["tp"], r["fn"], r["fp"]) == (1, 1, 1)
    assert r["precision"] == 0.5 and r["recall"] == 0.5
    assert precision_recall([("consistent", "consistent")])["recall"] is None
