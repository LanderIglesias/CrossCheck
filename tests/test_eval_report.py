from __future__ import annotations

import pytest

from crosscheck.evaluation.report import render_report, summarize

BUDGET = {
    "live_calls": 10,
    "failed_calls": 0,
    "input_tokens": 1000,
    "output_tokens": 100,
    "spent_usd": 0.5,
}


def _row(item_id, source, checker, predicted, gold="discrepant", **kw):
    row = {
        "item_id": item_id,
        "source": source,
        "checker": checker,
        "repeat": 0,
        "gold": gold,
        "predicted": predicted,
        "rationale": "",
        "cause": None,
        "root_cause_id": None,
        "mutation_type": None,
        "size": None,
        "live": False,
        "cost_usd": 0.0,
        "error": None,
    }
    row.update(kw)
    return row


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)


def test_summary_never_mixes_sources():
    rows = [
        _row("r1", "real_restatement", "llm", "discrepant", cause="restatement"),
        _row("r2", "real_blind", "llm", "consistent"),
        _row("i1", "injected", "llm", "discrepant", mutation_type="value", size="0.05"),
        _row("i2", "injected", "llm", "discrepant", mutation_type="value", size="0.05"),
        _row("i3", "injected", "llm", "consistent", mutation_type="unit_x1000"),
    ]
    s = summarize(rows, BUDGET, partial=False)
    real = s["real"]["llm"]
    assert real["restatement"]["n"] == 1 and real["blind"]["n"] == 1 and real["combined"]["n"] == 2
    inj = s["injected"]["llm"]
    assert sum(c["n"] for by_size in inj.values() for c in by_size.values()) == 3
    # No block anywhere aggregates the 5 real+injected rows.
    for part in ("real", "injected", "false_alarms"):
        assert all(v != 5 for k, v in _walk(s[part]) if k == "n")
    assert "combined" not in s["injected"]["llm"]
    # Whole summary (cost and stability included): nothing equals the pooled 5 rows.
    assert all(v != 5 for k, v in _walk(s) if k in ("n", "pairs", "detected"))


def test_recall_by_type_and_size():
    rows = [
        _row("a", "injected", "rules", "discrepant", mutation_type="value", size="0.01"),
        _row("b", "injected", "rules", "consistent", mutation_type="value", size="0.01"),
        _row("c", "injected", "rules", "discrepant", mutation_type="value", size="0.10"),
        _row("d", "injected", "rules", None, mutation_type="value", size="0.10", error="x"),
    ]
    cell = summarize(rows, BUDGET, False)["injected"]["rules"]["value"]
    assert cell["0.01"]["recall"] == 0.5 and cell["0.01"]["n"] == 2
    assert cell["0.10"]["recall"] == 1.0 and cell["0.10"]["n"] == 1  # error row not scored
    assert len(cell["0.01"]["recall_ci"]) == 2


def test_false_alarm_rate_on_controls():
    rows = [
        _row("c1", "real_consistent_control", "rules", "discrepant", gold="consistent"),
        _row("c2", "real_consistent_control", "rules", "consistent", gold="consistent"),
        _row("c3", "real_consistent_control", "rules", "consistent", gold="consistent"),
        _row("c4", "real_consistent_control", "rules", "consistent", gold="consistent"),
    ]
    fa = summarize(rows, BUDGET, False)["false_alarms"]["rules"]
    assert fa["n"] == 4 and fa["rate"] == 0.25
    # Controls never leak into the real precision/recall block.
    assert summarize(rows, BUDGET, False)["real"]["rules"]["combined"]["n"] == 0


def test_stability_flip_rate():
    rows = []
    for rep in range(1, 6):
        rows.append(_row("p1", "stability", "llm", "discrepant", repeat=rep))
        rows.append(
            _row("p2", "stability", "llm", "consistent" if rep == 3 else "discrepant", repeat=rep)
        )
    st = summarize(rows, BUDGET, False)["stability"]
    assert st["repeats"] == 5
    assert "flip_rate" not in st and "pairs" not in st  # no pooled figure
    real = st["by_origin"]["real"]
    assert real["pairs"] == 2 and real["flip_rate"] == 0.5
    assert real["modal_agreement"] == (1.0 + 0.8) / 2
    assert st["by_origin"]["injected"]["pairs"] == 0


def test_stability_and_cost_split_by_source():
    rows = [
        _row("r", "real_blind", "llm", "discrepant", cost_usd=0.1, live=True),
        _row("i1", "injected", "llm", "discrepant", mutation_type="value", cost_usd=0.2),
        _row("i2", "injected", "llm", "discrepant", mutation_type="value", cost_usd=0.2),
        _row("c", "real_consistent_control", "llm", "consistent", gold="consistent", cost_usd=0.3),
        _row("s", "stability", "llm", "discrepant", repeat=1, mutation_type="value", cost_usd=0.4),
        _row("s", "stability", "llm", "discrepant", repeat=2, mutation_type="value", cost_usd=0.4),
        _row("e", "real_blind", "llm", None, error="boom"),
    ]
    s = summarize(rows, BUDGET, False)
    co = s["cost"]
    assert "cost_per_detected_inconsistency" not in co
    assert co["by_source"]["real"] == {
        "cost_usd": 0.1,
        "detected": 1,
        "cost_per_detected_inconsistency": 0.1,
    }
    assert co["by_source"]["injected"]["cost_per_detected_inconsistency"] == pytest.approx(0.2)
    assert co["controls_spent_usd"] == 0.3 and co["stability_spent_usd"] == pytest.approx(0.8)
    assert s["real"]["llm"]["blind"]["errors"] == 1
    assert "errores: 1" in render_report(s)


def test_evaluation_cost_counts_cached_rows_apart_from_spent():
    rows = [
        _row("i1", "injected", "llm", "discrepant", mutation_type="value", cost_usd=0.2),
        _row("i2", "injected", "llm", "discrepant", mutation_type="value", cost_usd=0.2),
    ]
    co = summarize(rows, BUDGET, False)["cost"]
    assert co["evaluation_cost_usd"] == pytest.approx(0.4)
    assert co["spent_usd"] == BUDGET["spent_usd"] == 0.5
    assert co["by_source"]["injected"]["cost_usd"] == pytest.approx(0.4)
    report = render_report(summarize(rows, BUDGET, False))
    assert "Coste de la evaluación" in report and "Pagado en esta ejecución: 0.5000 $" in report


def test_partial_flag_propagates_to_report():
    s = summarize([], BUDGET, partial=True)
    assert s["partial"] is True
    assert "parcial" in render_report(s).splitlines()[0].lower()
    assert "parcial" not in render_report(summarize([], BUDGET, False)).lower()


def test_cost_per_detected_inconsistency_none_when_zero_detected():
    rows = [_row("i1", "injected", "llm", "consistent", mutation_type="value", size="0.05")]
    by = summarize(rows, BUDGET, False)["cost"]["by_source"]
    assert by["injected"]["cost_per_detected_inconsistency"] is None
    assert by["real"]["cost_per_detected_inconsistency"] is None


def test_report_prints_na_for_undefined_ratio():
    s = summarize(
        [_row("r", "real_blind", "rules", "consistent", gold="consistent")], BUDGET, False
    )
    md = render_report(s)
    assert "n/a" in md
