"""Phase 8 eval: run the LLM-as-judge (Claude Sonnet 5) over ALL 5 companies' real candidate pairs
(broadened from Phase 5's PPC-only version), then report, as measured:

1. LLM accuracy against all 49 real, hand-labeled gold_labels (same scoring as Phase 4/8).
2. Agreement % between the LLM judge and the rule-based checker on the SAME pairs -- this is
   protocol.md's literal ask: "Phase 5 validates the LLM judge against these labels and reports
   agreement."
3. Real token usage and cost for any live (non-cached) API calls.

Makes real, paid Anthropic API calls on a cache miss -- requires ANTHROPIC_API_KEY in .env. This
now covers many more candidate pairs than Phase 5's PPC-only run (~12 live calls there) -- real
cost is reported at the end, not estimated in advance. Responses are cached by prompt hash (see
llm_judge.py) so re-running this script is free.
"""

from __future__ import annotations

import json

from eval_consistency_checker import load_all_claims, load_all_gold_labels

from crosscheck.consistency.checker import check_pair, group_by_metric_and_period
from crosscheck.consistency.llm_judge import MODEL_ID, _build_prompt, _cache_path, judge_pair
from crosscheck.models import Claim

# Sonnet 5 pricing at time of writing: $2/$10 per 1M input/output tokens.
_INPUT_PRICE_PER_TOKEN = 2.00 / 1_000_000
_OUTPUT_PRICE_PER_TOKEN = 10.00 / 1_000_000


def main() -> None:
    claims = load_all_claims()
    gold = load_all_gold_labels()

    scored: list[tuple[str, str]] = []
    unscored = 0
    agree = 0
    disagree = 0
    total_input_tokens = 0
    total_output_tokens = 0
    live_calls = 0

    for (_subject, _metric_key, _period), group in group_by_metric_and_period(claims).items():
        pairs: list[tuple[Claim, Claim | None]] = []
        if len(group) == 1:
            pairs.append((group[0], None))
        else:
            for i, member_a in enumerate(group):
                for member_b in group[i + 1 :]:
                    if member_a.document_id == member_b.document_id:
                        continue
                    pairs.append((member_a, member_b))

        for claim_a, claim_b in pairs:
            rule_verdict = (
                "unsupported" if claim_b is None else check_pair(claim_a, claim_b)[0].value
            )

            prompt = _build_prompt(claim_a, claim_b)
            cache_path = _cache_path(prompt)
            was_cached = cache_path.exists()

            llm_pred = judge_pair(claim_a, claim_b)

            if not was_cached:
                cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
                usage = cached_data.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                live_calls += 1

            if rule_verdict == llm_pred.verdict.value:
                agree += 1
            else:
                disagree += 1

            claim_a_id = claim_a.id
            claim_b_id = claim_b.id if claim_b else None
            assert claim_a_id is not None  # nosec B101 - loaded from DB, always has an id
            key = (
                frozenset({claim_a_id})
                if claim_b_id is None
                else frozenset({claim_a_id, claim_b_id})
            )
            actual = gold.get(key)
            both_manual = claim_a.extraction_method == "manual" and (
                claim_b is None or claim_b.extraction_method == "manual"
            )

            label_b = claim_b.metric if claim_b else "(none)"
            print(
                f"[{'SCORED' if actual and both_manual else 'unscored'}] "
                f"{claim_a.canonical_metric_key}: {claim_a.metric} vs {label_b} "
                f"-> rule={rule_verdict}, llm={llm_pred.verdict.value}"
                + (f", actual={actual}" if actual else "")
            )

            if actual is not None and both_manual:
                scored.append((llm_pred.verdict.value, actual))
            else:
                unscored += 1

    correct = sum(1 for p, a in scored if p == a)
    print(f"\n--- LLM judge ({MODEL_ID}) vs real gold_labels ---")
    print(f"{len(scored)} scored, {correct} correct.")
    if scored:
        print(f"Accuracy: {correct / len(scored):.1%}")
    print(f"{unscored} predictions had no real gold_label counterpart (unscored, not guessed).")

    print("\n--- LLM judge vs rule-based checker (same pairs) ---")
    total = agree + disagree
    print(f"Agreement: {agree}/{total} ({agree / total:.1%})" if total else "No pairs compared.")

    print("\n--- Real cost (this run) ---")
    print(f"Live API calls: {live_calls} (rest served from cache)")
    if live_calls:
        cost = (
            total_input_tokens * _INPUT_PRICE_PER_TOKEN
            + total_output_tokens * _OUTPUT_PRICE_PER_TOKEN
        )
        print(f"Tokens: {total_input_tokens} input, {total_output_tokens} output")
        print(f"Estimated cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
