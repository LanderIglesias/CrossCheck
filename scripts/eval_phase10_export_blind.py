"""Phase 10: export unlabeled candidate pairs to eval/phase10/blind_pairs.csv for blind labeling.

Read-only on the DB. The CSV carries no checker prediction; the user fills verdict, rationale and
labeled_by following protocol.md.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from eval_consistency_checker import load_all_claims, load_all_gold_labels

from crosscheck.evaluation.blind import unlabeled_pairs, write_blind_csv

OUT = Path(__file__).resolve().parent.parent / "eval" / "phase10" / "blind_pairs.csv"


def main() -> None:
    pairs = unlabeled_pairs(load_all_claims(), load_all_gold_labels())
    n = write_blind_csv(OUT, pairs)
    print(f"{n} unlabeled pairs -> {OUT}")
    for subject, count in sorted(Counter(a.subject for a, _ in pairs).items()):
        print(f"  {subject}: {count}")


if __name__ == "__main__":
    main()
