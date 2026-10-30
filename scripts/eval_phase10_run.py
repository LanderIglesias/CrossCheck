"""Phase 10 harness: run the rule-based checker and the paid LLM judge over real hard cases and
injected errors, under a hard API spend cap, then aggregate (report.py).

  --count      print every planned number (no API calls, no cost)
  --pilot N    at most N live judge calls over mutation items; prints real cost per call and the
               projected total of the full plan
  --full       the whole plan; writes predictions.jsonl, results.json, report.md

Execution order (a cut leaves the most valuable part): confirmed restatements and blind labels,
real `consistent` controls, mutations, stability. The rules run on everything (free); the judge is
cached on disk, so re-running costs nothing. Real and injected items are never combined.

Run from the repo root: python scripts/eval_phase10_run.py --count
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval_consistency_checker import load_all_claims, load_all_gold_labels
from extract_xbrl_claims import COMPANIES

from crosscheck.consistency.checker import check_pair
from crosscheck.consistency.llm_judge import (
    LLMJudgeNotConfiguredError,
    is_cached,
    judge_pair_with_usage,
)
from crosscheck.db import get_connection
from crosscheck.evaluation.blind import claim_key, load_blind_labels, pair_key
from crosscheck.evaluation.budget import BudgetExceededError, BudgetGuard
from crosscheck.evaluation.mutations import (
    Mutation,
    NeighborValues,
    dump_mutations,
    generate_mutations,
    neighbor_values,
)
from crosscheck.evaluation.report import render_report, summarize
from crosscheck.evaluation.restatements import load_candidates, load_confirmed_cases
from crosscheck.models import Claim
from crosscheck.sources.edgar import fetch_company_facts

OUT = Path("eval/phase10")
PHASE8_ESTIMATE_USD = 0.0035
SOFT_CAP_USD = 3.5  # above this planned spend, base pairs are sub-sampled
STABILITY_REPEATS = range(1, 6)
STABILITY_MUTATIONS = STABILITY_REAL = 30


@dataclass(frozen=True)
class Item:
    item_id: str
    source: str
    claim_a: Claim
    claim_b: Claim
    gold: str
    cause: str | None = None
    root_cause_id: str | None = None
    mutation_type: str | None = None
    size: str | None = None


def _short(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def base_pairs(claims: list[Claim], gold: dict[frozenset[int], str]) -> list[tuple[Claim, Claim]]:
    """Real gold `consistent` rows with a claim_b, ordered by content (stable across re-seeds)."""
    by_id = {c.id: c for c in claims}
    pairs = []
    for ids, verdict in gold.items():
        if verdict != "consistent" or len(ids) != 2:
            continue
        a, b = sorted((by_id[i] for i in ids), key=claim_key)
        pairs.append((a, b))
    return sorted(pairs, key=lambda p: pair_key(*p))


def stratified(muts: list[Mutation], n: int, seed: int) -> list[Mutation]:
    """n mutations spread evenly over (type, size) cells, picked with the seed."""
    cells: dict[tuple[str, str], list[Mutation]] = defaultdict(list)
    for m in sorted(muts, key=lambda m: m.mutation_id):
        cells[(m.type.value, str(m.size))].append(m)
    rng = random.Random(seed)
    queues = [cells[k] for k in sorted(cells)]
    for q in queues:
        rng.shuffle(q)
    out: list[Mutation] = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop())
    return out


def _company_meta(claims: list[Claim]) -> dict[int, tuple[str, str]]:
    """document_id -> (ticker, cik) through documents -> quarters -> companies (Ruling 9: the
    subject string differs across extraction methods, so it can't identify the company)."""
    ids = sorted({c.document_id for c in claims})
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.id, co.ticker, co.cik FROM documents d "
            "JOIN quarters q ON q.id = d.quarter_id JOIN companies co ON co.id = q.company_id "
            "WHERE d.id = ANY(%s)",
            (ids,),
        )
        return {doc_id: (ticker, cik) for doc_id, ticker, cik in cur.fetchall()}


def _neighbors(pairs: list[tuple[Claim, Claim]]) -> dict[str, NeighborValues]:
    meta = _company_meta([a for a, _ in pairs])
    targets = {c.ticker: c for c in COMPANIES}
    facts: dict[str, Any] = {}
    out: dict[str, NeighborValues] = {}
    for a, b in pairs:
        ticker, cik = meta[a.document_id]
        if cik not in facts:
            facts[cik] = fetch_company_facts(cik)
        out[pair_key(a, b)] = neighbor_values(
            facts[cik], a.canonical_metric_key, targets[ticker].accession_number
        )
    return out


@dataclass
class Plan:
    real: list[Item]
    controls: list[Item]
    mutations: list[Item]
    stability: list[Item]
    info: dict[str, Any]

    @property
    def main(self) -> list[Item]:
        return self.real + self.controls + self.mutations


def build_plan(seed: int) -> Plan:
    claims = load_all_claims()
    gold = load_all_gold_labels()
    all_base = base_pairs(claims, gold)
    neighbors = _neighbors(all_base)

    def make(base: list[tuple[Claim, Claim]]) -> tuple[list[Mutation], dict[str, int]]:
        return generate_mutations(base, neighbors, seed)

    cands = load_candidates(OUT / "restatement_candidates.json")
    cases, case_stats = load_confirmed_cases(cands, OUT / "restatement_causes.json")
    real = [
        Item(
            c.case_id,
            "real_restatement",
            c.claim_a,
            c.claim_b,
            c.gold.value,
            c.cause,
            c.root_cause_id,
        )
        for c in cases
    ]
    blind = load_blind_labels(OUT / "blind_pairs.csv", claims)
    real += [Item(_short(pair_key(a, b)), "real_blind", a, b, v.value) for a, b, v, _r in blind]

    # Sub-sample the base pairs (with the seed) until the plan fits under the soft cap.
    base = list(all_base)
    reduced = False
    while True:
        muts, skips = make(base)
        controls = [
            Item(_short(pair_key(a, b)), "real_consistent_control", a, b, "consistent")
            for a, b in base
        ]
        n_stab = STABILITY_MUTATIONS + STABILITY_REAL
        planned = len(real) + len(controls) + len(muts) + n_stab * len(STABILITY_REPEATS)
        if planned * PHASE8_ESTIMATE_USD <= SOFT_CAP_USD or len(base) <= 1:
            break
        reduced = True
        base = random.Random(seed).sample(base, len(base) - 1)
        base.sort(key=lambda p: pair_key(*p))

    mut_items = [
        Item(
            m.mutation_id,
            "injected",
            m.claim_a,
            m.claim_b,
            "discrepant",
            mutation_type=m.type.value,
            size=None if m.size is None else str(m.size),
        )
        for m in muts
    ]
    by_id = {i.item_id: i for i in mut_items}
    stab = [by_id[m.mutation_id] for m in stratified(muts, STABILITY_MUTATIONS, seed)]
    real_pool = [i for i in real if i.source == "real_restatement"] + [
        i for i in real if i.source == "real_blind"
    ]
    ctrl = list(controls)
    random.Random(seed).shuffle(ctrl)
    stab += (real_pool + ctrl)[:STABILITY_REAL]

    info = {
        "eligible_base_pairs": len(all_base),
        "base_pairs_used": len(base),
        "base_reduced": reduced,
        "skips": skips,
        "case_stats": case_stats,
        "restatement_cases": sum(1 for i in real if i.source == "real_restatement"),
        "blind_labels": sum(1 for i in real if i.source == "real_blind"),
        "mutations": muts,
    }
    return Plan(real, controls, mut_items, stab, info)


def _row(item: Item, checker: str, repeat: int, source: str | None = None) -> dict:
    return {
        "item_id": item.item_id,
        "source": source or item.source,
        "checker": checker,
        "repeat": repeat,
        "gold": item.gold,
        "predicted": None,
        "rationale": "",
        "cause": item.cause,
        "root_cause_id": item.root_cause_id,
        "mutation_type": item.mutation_type,
        "size": item.size,
        "live": False,
        "cost_usd": 0.0,
        "error": None,
    }


def rules_row(item: Item) -> dict:
    row = _row(item, "rules", 0)
    verdict, rationale = check_pair(item.claim_a, item.claim_b)
    row.update(predicted=verdict.value, rationale=rationale)
    return row


def judge_row(
    item: Item,
    repeat: int,
    guard: BudgetGuard,
    judge: Callable[..., Any] = judge_pair_with_usage,
    source: str | None = None,
) -> dict:
    """One judge call. The guard is checked before EVERY call: is_cached only checks that a file
    exists, and a corrupt entry is silently re-fetched live (Ruling 6)."""
    row = _row(item, "llm", repeat, source)
    guard.check_can_call()
    try:
        pred, usage = judge(item.claim_a, item.claim_b, repeat)
    except LLMJudgeNotConfiguredError:
        raise
    except RuntimeError as exc:
        guard.record_failure()
        row["error"] = str(exc)
        return row
    row.update(predicted=pred.verdict.value, rationale=pred.rationale)
    if usage is not None:
        row.update(live=True, cost_usd=guard.record_usage(usage))
    return row


def execute(plan: Plan, guard: BudgetGuard) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    try:
        for item in plan.main:
            rows.append(rules_row(item))
            rows.append(judge_row(item, 0, guard))
        for item in plan.stability:
            for rep in STABILITY_REPEATS:
                rows.append(judge_row(item, rep, guard, source="stability"))
    except BudgetExceededError as exc:
        print(f"AVISO: tope de gasto alcanzado, resultados parciales: {exc}")
        return rows, True
    return rows, False


def _llm_calls(plan: Plan) -> tuple[int, int]:
    """(planned judge calls, of which not cached yet)."""
    calls = [(i, 0) for i in plan.main] + [
        (i, r) for i in plan.stability for r in STABILITY_REPEATS
    ]
    return len(calls), sum(1 for i, r in calls if not is_cached(i.claim_a, i.claim_b, r))


def cmd_count(plan: Plan, seed: int) -> None:
    info = plan.info
    OUT.mkdir(parents=True, exist_ok=True)
    dump_mutations(info["mutations"], OUT / "mutations.json")
    by_type: dict[str, int] = defaultdict(int)
    for m in plan.mutations:
        by_type[m.mutation_type or ""] += 1
    total, uncached = _llm_calls(plan)
    print(f"seed: {seed}")
    print(f"eligible base pairs (gold consistent, claim_b not null): {info['eligible_base_pairs']}")
    print(
        f"base pairs used: {info['base_pairs_used']}"
        + (" (REDUCED with the seed to fit under ~3.5 USD)" if info["base_reduced"] else "")
    )
    print(f"mutations: {len(plan.mutations)}")
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")
    print(f"mutation skips: {info['skips']}")
    cs = info["case_stats"]
    print(
        f"confirmed real restatement cases: {info['restatement_cases']} "
        f"(excluded no cause: {cs['excluded_no_cause']}, unreviewed: {cs['excluded_unreviewed']}, "
        f"root causes: {cs['root_causes']})"
    )
    print(f"blind labels found: {info['blind_labels']}")
    print(f"real consistent controls: {len(plan.controls)}")
    print(
        f"stability items: {len(plan.stability)} x {len(STABILITY_REPEATS)} = "
        f"{len(plan.stability) * len(STABILITY_REPEATS)} calls"
    )
    print(f"planned judge calls: {total} ({uncached} not cached yet)")
    print(
        f"estimated cost at {PHASE8_ESTIMATE_USD} USD/call (Phase 8): "
        f"{total * PHASE8_ESTIMATE_USD:.2f} USD total, {uncached * PHASE8_ESTIMATE_USD:.2f} USD live"
    )


def cmd_pilot(plan: Plan, seed: int, n: int, cap: float) -> None:
    guard = BudgetGuard(cap_usd=cap)
    items = {i.item_id: i for i in plan.mutations}
    # Stratified order over the whole set, so the pilot sees every type; stop at n live calls
    # (cache hits cost nothing and don't count).
    for m in stratified(plan.info["mutations"], len(plan.mutations), seed):
        if guard.live_calls + guard.failed_calls >= n:
            break
        judge_row(items[m.mutation_id], 0, guard)
    total, uncached = _llm_calls(plan)
    mean = guard.spent_usd / guard.live_calls if guard.live_calls else 0.0
    print(
        f"pilot: live calls: {guard.live_calls}, failed: {guard.failed_calls}, "
        f"spent: {guard.spent_usd:.4f} USD"
    )
    print(f"real mean cost per call: {mean:.5f} USD (Phase 8 estimate: {PHASE8_ESTIMATE_USD})")
    print(f"planned judge calls in the full plan: {total} ({uncached} still to pay)")
    print(
        f"projected total for the full plan: {total * mean:.2f} USD "
        f"(still to pay: {uncached * mean:.2f} USD)"
    )


def cmd_full(plan: Plan, seed: int, cap: float) -> None:
    guard = BudgetGuard(cap_usd=cap)
    rows, partial = execute(plan, guard)
    OUT.mkdir(parents=True, exist_ok=True)
    dump_mutations(plan.info["mutations"], OUT / "mutations.json")
    (OUT / "predictions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    budget = {
        k: getattr(guard, k)
        for k in ("live_calls", "failed_calls", "input_tokens", "output_tokens", "spent_usd")
    }
    summary = summarize(rows, budget, partial, seed)
    (OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(f"spent {guard.spent_usd:.4f} USD in {guard.live_calls} live calls; partial={partial}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--count", action="store_true")
    mode.add_argument("--pilot", type=int, metavar="N")
    mode.add_argument("--full", action="store_true")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--cap-usd", type=float, default=5.0)
    args = ap.parse_args()
    plan = build_plan(args.seed)
    if args.count:
        cmd_count(plan, args.seed)
    elif args.pilot is not None:
        cmd_pilot(plan, args.seed, args.pilot, args.cap_usd)
    else:
        cmd_full(plan, args.seed, args.cap_usd)


if __name__ == "__main__":
    main()
