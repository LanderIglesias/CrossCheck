"""Phase 8 eval: run the rule-based consistency checker over ALL 5 companies' real claims (manual
+ automated_xbrl) and score its predictions against all 49 real, hand-labeled gold_labels rows
(broadened from Phase 4's PPC-only version, which covered only the 10 PPC-specific rows).

Predictions involving a claim the human never paired (e.g. the automated_xbrl claims, or
manual-manual pairs the labeler simply didn't get to) have no ground truth to score against --
reported separately, not silently treated as correct.
"""

from __future__ import annotations

from crosscheck.consistency.checker import generate_predictions
from crosscheck.db import get_connection
from crosscheck.models import Claim


def load_all_claims() -> list[Claim]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, document_id, subject, metric, canonical_metric_key, period,
                   value, unit, qualifier, speaker, extraction_method, model_id,
                   prompt_hash, confidence
            FROM claims
            """)
        rows = cur.fetchall()

    claims = []
    for row in rows:
        (
            claim_id,
            document_id,
            subject,
            metric,
            canonical_metric_key,
            period,
            value,
            unit,
            qualifier,
            speaker,
            extraction_method,
            model_id,
            prompt_hash,
            confidence,
        ) = row
        claims.append(
            Claim(
                id=claim_id,
                document_id=document_id,
                subject=subject,
                metric=metric,
                canonical_metric_key=canonical_metric_key,
                period=period,
                value=value,
                unit=unit,
                qualifier=qualifier,
                speaker=speaker,
                extraction_method=extraction_method,
                model_id=model_id,
                prompt_hash=prompt_hash,
                confidence=confidence,
            )
        )
    return claims


def load_all_gold_labels() -> dict[frozenset[int], str]:
    """Map an unordered {claim_a_id, claim_b_id} pair (or a single-element set for
    unsupported claims) to its real, hand-labeled verdict string."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT claim_a_id, claim_b_id, verdict FROM gold_labels")
        rows = cur.fetchall()

    gold: dict[frozenset[int], str] = {}
    for claim_a_id, claim_b_id, verdict in rows:
        key = frozenset({claim_a_id}) if claim_b_id is None else frozenset({claim_a_id, claim_b_id})
        gold[key] = verdict
    return gold


def main() -> None:
    claims = load_all_claims()
    predictions = generate_predictions(claims)
    gold = load_all_gold_labels()

    scored: list[tuple[str, str]] = []  # (predicted, actual)
    unscored = 0

    for pred in predictions:
        claim_a_id = pred.claim_a.id
        claim_b_id = pred.claim_b.id if pred.claim_b else None
        assert claim_a_id is not None  # nosec B101 - loaded from DB, always has an id
        key = frozenset({claim_a_id}) if claim_b_id is None else frozenset({claim_a_id, claim_b_id})

        actual = gold.get(key)
        both_manual = pred.claim_a.extraction_method == "manual" and (
            pred.claim_b is None or pred.claim_b.extraction_method == "manual"
        )

        label_b = pred.claim_b.metric if pred.claim_b else "(none)"
        print(
            f"[{'SCORED' if actual and both_manual else 'unscored'}] "
            f"{pred.claim_a.canonical_metric_key}: {pred.claim_a.metric} vs {label_b} "
            f"-> predicted={pred.verdict.value}" + (f", actual={actual}" if actual else "")
        )

        if actual is not None and both_manual:
            scored.append((pred.verdict.value, actual))
        else:
            unscored += 1

    correct = sum(1 for p, a in scored if p == a)
    print(f"\n{len(scored)} scored against real gold_labels, {correct} correct.")
    if scored:
        print(f"Accuracy: {correct / len(scored):.1%}")
    for predicted, actual in scored:
        if predicted != actual:
            print(f"  MISMATCH: predicted={predicted}, actual={actual}")
    print(f"{unscored} predictions had no real gold_label counterpart (unscored, not guessed).")

    discrepant_or_ambiguous = [
        p for p in predictions if p.verdict.value in ("discrepant", "ambiguous")
    ]
    print(
        f"\n{len(discrepant_or_ambiguous)} predicted discrepant/ambiguous verdicts "
        "(scored or not) -- the real, unresolved question this project has carried since Phase 0."
    )
    for p in discrepant_or_ambiguous:
        label_b = p.claim_b.metric if p.claim_b else "(none)"
        print(
            f"  {p.claim_a.canonical_metric_key}: {p.claim_a.metric} vs {label_b} -> "
            f"{p.verdict.value} ({p.rationale})"
        )


if __name__ == "__main__":
    main()
