"""Seeded generator of injected errors over real `consistent` claim pairs (Phase 10).

Used to draw a sensitivity curve (recall of `discrepant` by error size and type) for the checker
and the LLM judge. The mutations are synthetic: they live in memory and in an eval artifact
(`eval/phase10/mutations.json`), never in the `claims` or `gold_labels` tables. The gold of every
mutation is `discrepant`, so it is not stored.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from crosscheck.consistency.checker import TOLERANCE_PCT
from crosscheck.evaluation.blind import pair_key
from crosscheck.extraction.xbrl import (
    _MAX_QUARTER_DAYS,
    _MIN_QUARTER_DAYS,
    TAG_TO_CANONICAL_KEY,
    _find_quarterly_fact,
)
from crosscheck.models import Claim

# 0.0049 / 0.0051 straddle the 0.5 % tolerance by epsilon = 0.01 pp.
VALUE_SIZES: tuple[Decimal, ...] = (
    Decimal("0.003"),
    Decimal("0.0049"),
    Decimal("0.0051"),
    Decimal("0.01"),
    Decimal("0.02"),
    Decimal("0.05"),
    Decimal("0.10"),
)
_SIG_DIGITS = 10  # rounding error ~1e-9 relative, far below epsilon/10 = 1e-5


class MutationType(StrEnum):
    VALUE = "value"
    UNIT_X1000 = "unit_x1000"
    PERIOD_PREV = "period_prev_quarter"
    PERIOD_YTD = "period_ytd"


@dataclass(frozen=True)
class NeighborValues:
    prev_quarter: Decimal | None
    ytd: Decimal | None


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    base_pair_key: str
    type: MutationType
    size: Decimal | None
    direction: int | None
    claim_a: Claim
    claim_b: Claim


def neighbor_values(
    company_facts: dict[str, Any], canonical_metric_key: str, quarter_accession: str
) -> NeighborValues:
    """Previous-quarter and year-to-date values of the same tag as the 10-Q's quarterly fact.

    The previous quarter is an 80-100 day fact ending the day before the base quarter starts; the
    year-to-date one ends on the same day but lasts longer (so a Q1 has none). Each takes the first
    value published, which is the one a reader of the original filing would see.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag, (key, _label) in TAG_TO_CANONICAL_KEY.items():
        if key != canonical_metric_key:
            continue
        for facts in us_gaap.get(tag, {}).get("units", {}).values():
            base = _find_quarterly_fact(facts, quarter_accession)
            if base is None:
                continue
            start = date.fromisoformat(base["start"])
            end = date.fromisoformat(base["end"])
            prev = ytd = None
            for f in facts:
                f_start, f_end = date.fromisoformat(f["start"]), date.fromisoformat(f["end"])
                days = (f_end - f_start).days
                if (
                    prev is None
                    and f_end == start - timedelta(days=1)
                    and _MIN_QUARTER_DAYS <= days <= _MAX_QUARTER_DAYS
                ):
                    prev = Decimal(str(f["val"]))
                elif ytd is None and f_end == end and days > _MAX_QUARTER_DAYS:
                    ytd = Decimal(str(f["val"]))
            return NeighborValues(prev, ytd)
    return NeighborValues(None, None)


def mutated_value(anchor: Decimal, size: Decimal, direction: int) -> Decimal:
    """Value whose checker relative diff against `anchor` is exactly `size`.

    The checker divides by max(|a|, |b|): going down (b = a(1-s)) that max is |a|, going up
    (b = a/(1-s)) it is |b|, so both give |a-b| / max = s.
    """
    raw = anchor * (1 - size) if direction < 0 else anchor / (1 - size)
    return raw.quantize(Decimal(1).scaleb(raw.adjusted() - _SIG_DIGITS + 1))


def _mutation_id(key: str, mtype: MutationType, size: Decimal | None, direction: int | None) -> str:
    return hashlib.sha1(f"{key}|{mtype}|{size}|{direction}".encode()).hexdigest()[:12]


def generate_mutations(
    base_pairs: list[tuple[Claim, Claim]], neighbors: dict[str, NeighborValues], seed: int
) -> tuple[list[Mutation], dict[str, int]]:
    """Mutate `claim_b` of each pair; `claim_a.value` is the anchor.

    `neighbors` is keyed by base_pair_key. The direction of a value mutation is seeded per
    (pair, type, size), so it does not depend on iteration order.
    """
    skips = {"zero_base": 0, "no_neighbor": 0, "neighbor_within_tolerance": 0}
    out: list[Mutation] = []

    def add(
        key: str,
        mtype: MutationType,
        size: Decimal | None,
        direction: int | None,
        a: Claim,
        new_b: Claim,
    ) -> None:
        mid = _mutation_id(key, mtype, size, direction)
        out.append(Mutation(mid, key, mtype, size, direction, a, new_b))

    for a, b in base_pairs:
        key = pair_key(a, b)
        anchor = a.value
        if anchor is not None and anchor != 0:
            for size in VALUE_SIZES:
                rng = random.Random(f"{seed}:{key}:{MutationType.VALUE}:{size}")
                direction = rng.choice((-1, 1))
                new_b = b.model_copy(update={"value": mutated_value(anchor, size, direction)})
                add(key, MutationType.VALUE, size, direction, a, new_b)
            add(
                key,
                MutationType.UNIT_X1000,
                None,
                None,
                a,
                b.model_copy(update={"value": anchor * 1000}),
            )
        else:
            skips["zero_base"] += 1

        nb = neighbors.get(key)
        for mtype, value in (
            (MutationType.PERIOD_PREV, nb.prev_quarter if nb else None),
            (MutationType.PERIOD_YTD, nb.ytd if nb else None),
        ):
            if value is None or anchor is None:
                skips["no_neighbor"] += 1
            elif abs(anchor - value) / max(abs(anchor), abs(value)) <= TOLERANCE_PCT:
                # Undetectable by definition: the checker would call it consistent.
                skips["neighbor_within_tolerance"] += 1
            else:
                add(key, mtype, None, None, a, b.model_copy(update={"value": value}))
    return out, skips


def dump_mutations(muts: list[Mutation], path: Path) -> None:
    rows = [
        {
            "mutation_id": m.mutation_id,
            "base_pair_key": m.base_pair_key,
            "type": m.type.value,
            "size": None if m.size is None else str(m.size),
            "direction": m.direction,
            "claim_a": m.claim_a.model_dump(mode="json"),
            "claim_b": m.claim_b.model_dump(mode="json"),
        }
        for m in muts
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def load_mutations(path: Path) -> list[Mutation]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        Mutation(
            r["mutation_id"],
            r["base_pair_key"],
            MutationType(r["type"]),
            None if r["size"] is None else Decimal(r["size"]),
            r["direction"],
            Claim.model_validate(r["claim_a"]),
            Claim.model_validate(r["claim_b"]),
        )
        for r in rows
    ]
