from __future__ import annotations

import csv
from decimal import Decimal

import pytest

from crosscheck.evaluation.blind import (
    BLIND_COLUMNS,
    claim_key,
    load_blind_labels,
    pair_key,
    unlabeled_pairs,
    write_blind_csv,
)
from crosscheck.models import Claim, Verdict


def _claim(cid: int, doc: int, value: str, subject: str = "ACME") -> Claim:
    return Claim(
        id=cid,
        document_id=doc,
        subject=subject,
        metric="Revenue",
        canonical_metric_key="revenue",
        period="FY2020-Q3",
        value=Decimal(value),
        unit="USD",
        extraction_method="manual",
    )


def test_pair_key_ignores_ids_and_order():
    a, b = _claim(1, 1, "100"), _claim(2, 2, "110")
    a2, b2 = a.model_copy(update={"id": 90}), b.model_copy(update={"id": 91})
    assert pair_key(a, b) == pair_key(b2, a2)
    assert claim_key(a) != claim_key(b)


def test_export_has_no_prediction_columns():
    for col in BLIND_COLUMNS:
        assert not any(bad in col for bad in ("rule", "llm", "pred", "rationale_"))


def test_labeled_pair_excluded():
    a, b, c = _claim(1, 1, "100"), _claim(2, 2, "110"), _claim(3, 3, "120")
    gold = {frozenset({1, 2}): "discrepant"}
    pairs = unlabeled_pairs([a, b, c], gold)
    assert {frozenset({x.id, y.id}) for x, y in pairs} == {frozenset({1, 3}), frozenset({2, 3})}


def test_singletons_and_same_document_excluded():
    a, b = _claim(1, 1, "100"), _claim(2, 1, "100")
    solo = _claim(3, 2, "5", subject="OTHER")
    assert unlabeled_pairs([a, b, solo], {}) == []


def test_load_blind_labels_rematches_by_content(tmp_path):
    a, b = _claim(1, 1, "100"), _claim(2, 2, "110")
    path = tmp_path / "blind.csv"
    row = dict.fromkeys(BLIND_COLUMNS, "")
    row.update(pair_key=pair_key(a, b), verdict="discrepant", rationale="r", labeled_by="me")
    skipped = dict.fromkeys(BLIND_COLUMNS, "")
    skipped.update(pair_key="x || y")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BLIND_COLUMNS)
        w.writeheader()
        w.writerows([row, skipped])
    # fresh ids, as after another `make seed`
    a2, b2 = a.model_copy(update={"id": 50}), b.model_copy(update={"id": 51})
    out = load_blind_labels(path, [b2, a2])
    assert len(out) == 1
    assert {out[0][0].id, out[0][1].id} == {50, 51}
    assert out[0][2] == Verdict.DISCREPANT and out[0][3] == "r"


def test_content_identical_claims_export_one_row_and_label_once(tmp_path):
    a, b = _claim(1, 1, "100"), _claim(2, 2, "110")
    b_dup = b.model_copy(update={"id": 3})
    pairs = unlabeled_pairs([a, b, b_dup], {})
    assert len(pairs) == 2
    path = tmp_path / "blind.csv"
    assert write_blind_csv(path, pairs) == 1
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows[0]["verdict"] = "consistent"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BLIND_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert len(load_blind_labels(path, [a, b, b_dup])) == 1
    w_rows = rows + rows
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BLIND_COLUMNS)
        w.writeheader()
        w.writerows(w_rows)
    with pytest.raises(ValueError, match="twice"):
        load_blind_labels(path, [a, b, b_dup])


def test_bad_verdict_names_pair_key_and_value(tmp_path):
    a, b = _claim(1, 1, "100"), _claim(2, 2, "110")
    path = tmp_path / "blind.csv"
    write_blind_csv(path, [(a, b)])
    path.write_text(
        path.read_text(encoding="utf-8").replace(",,,\n", ",bogus,,\n"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="bogus"):
        load_blind_labels(path, [a, b])
