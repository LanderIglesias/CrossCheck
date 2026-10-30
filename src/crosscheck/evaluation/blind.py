"""Blind export of unlabeled candidate pairs (Phase 10).

The pairs the checkers generate that no human has labeled yet go to a CSV the user labels without
seeing any checker prediction (so the labels can't be anchored by them). Claim ids change on every
`make seed`, so pairs are matched by a content key instead of by id.
"""

from __future__ import annotations

import csv
from itertools import combinations
from pathlib import Path

from crosscheck.consistency.checker import group_by_metric_and_period
from crosscheck.models import Claim, Verdict

_CLAIM_FIELDS = ("metric", "value", "unit", "qualifier", "speaker", "extraction_method")
BLIND_COLUMNS = [
    "pair_key",
    "subject",
    "canonical_metric_key",
    "period",
    *(f"{side}_{f}" for side in ("a", "b") for f in _CLAIM_FIELDS),
    "verdict",
    "rationale",
    "labeled_by",
]


def claim_key(c: Claim) -> str:
    """Content identity of a claim: every field except the DB id (and model/prompt provenance)."""
    parts = (
        c.subject,
        c.canonical_metric_key,
        c.period,
        c.extraction_method,
        c.metric,
        c.value,
        c.unit,
        c.qualifier,
        c.speaker,
    )
    return "|".join("" if p is None else str(p) for p in parts)


def pair_key(a: Claim, b: Claim) -> str:
    """Order-independent identity of a pair, stable across re-seeds."""
    return " || ".join(sorted((claim_key(a), claim_key(b))))


def unlabeled_pairs(
    claims: list[Claim], gold: dict[frozenset[int], str]
) -> list[tuple[Claim, Claim]]:
    """Two-claim pairs `generate_predictions` would score (same group, different document) that
    have no gold label. Singletons are left out: `unsupported` is trivial for both checkers."""
    pairs = []
    for group in group_by_metric_and_period(claims).values():
        for a, b in combinations(group, 2):
            if a.document_id == b.document_id:
                continue
            if frozenset({a.id, b.id}) in gold:
                continue
            pairs.append((a, b))
    return pairs


def blind_rows(pairs: list[tuple[Claim, Claim]]) -> list[dict[str, str]]:
    """CSV rows sorted by pair_key, with empty verdict/rationale/labeled_by for the human."""
    rows = []
    for x, y in pairs:
        a, b = sorted((x, y), key=claim_key)
        row = dict.fromkeys(BLIND_COLUMNS, "")
        row.update(
            pair_key=pair_key(a, b),
            subject=a.subject,
            canonical_metric_key=a.canonical_metric_key,
            period=a.period,
        )
        for side, c in (("a", a), ("b", b)):
            for f in _CLAIM_FIELDS:
                v = getattr(c, f)
                row[f"{side}_{f}"] = "" if v is None else str(v)
        rows.append(row)
    return sorted(rows, key=lambda r: r["pair_key"])


def write_blind_csv(path: Path, pairs: list[tuple[Claim, Claim]]) -> int:
    rows = blind_rows(pairs)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BLIND_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_blind_labels(path: Path, claims: list[Claim]) -> list[tuple[Claim, Claim, Verdict, str]]:
    """Rematch labeled CSV rows to the current claims by pair_key. Rows without a verdict are
    skipped (the caller counts them: rows in the file minus the length of the result)."""
    by_key = {pair_key(a, b): (a, b) for a, b in unlabeled_pairs(claims, {})}
    labeled = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            verdict = row["verdict"].strip()
            if not verdict:
                continue
            if row["pair_key"] not in by_key:
                raise ValueError(f"labeled pair not found in current claims: {row['pair_key']}")
            a, b = by_key[row["pair_key"]]
            labeled.append((a, b, Verdict(verdict), row["rationale"]))
    return labeled
