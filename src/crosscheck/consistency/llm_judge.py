"""LLM-as-judge consistency checker (Phase 5).

Real Anthropic API calls (Claude Sonnet 5, user-confirmed choice) -- unlike every prior phase's
local/free models, this costs real money per call. Responses are cached on disk by prompt hash
(mirroring src/crosscheck/sources/edgar.py's content-hash caching) so repeated runs don't re-pay.

Per src/crosscheck/labeling/protocol.md: "Phase 5 validates the LLM judge against these labels and
reports agreement" -- this module's output is the same Prediction shape Phase 4's rule-based
checker produces, over the same candidate pairs, so the two are directly comparable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from crosscheck.config import settings
from crosscheck.consistency.checker import Prediction, group_by_metric_and_period
from crosscheck.io_utils import atomic_write_text
from crosscheck.models import Claim, Verdict

MODEL_ID = "claude-sonnet-5"

_SYSTEM_PROMPT = """\
You are judging whether two financial disclosure claims about the same company and period \
describe the same fact consistently. Apply these exact rules (quoted from the project's real \
human labeling protocol):

- consistent: the two claims describe the same fact within reasonable tolerance. Values within \
0.5% of each other, where the difference is plausibly explained by rounding, are consistent.
- discrepant: the two claims conflict in a way a reader would care about -- different numbers \
for the same metric/period, a metric definition that silently changed, or a qualifier \
dropped/added that changes the meaning.
- unsupported: claim A asserts something with no counterpart to compare against (used when \
claim_b is absent).
- ambiguous: you genuinely cannot tell from the given context whether it's the same fact. Do not \
force a verdict -- abstain with ambiguous rather than guess.

Always convert units before comparing (a unit conversion alone is not evidence of a discrepancy). \
A claim with a qualifier (e.g. adjusted, non-GAAP, constant currency) is only comparable to \
another claim with the same qualifier -- comparing GAAP to adjusted and calling it discrepant is \
wrong.

Call submit_verdict with your decision and a one-sentence rationale."""

_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the consistency verdict for this claim pair.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["consistent", "discrepant", "unsupported", "ambiguous"],
            },
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "rationale"],
        "additionalProperties": False,
    },
    "strict": True,
}

_client: Any = None


class LLMJudgeNotConfiguredError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is missing -- the LLM judge cannot run without it."""


def _get_client() -> Any:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise LLMJudgeNotConfiguredError(
                "ANTHROPIC_API_KEY is not set in .env -- the LLM judge requires a real Anthropic "
                "API key (get one at console.anthropic.com). See .env.example."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _describe_claim(claim: Claim) -> str:
    parts = [
        f"subject={claim.subject!r}",
        f"metric={claim.metric!r}",
        f"canonical_metric_key={claim.canonical_metric_key!r}",
        f"period={claim.period!r}",
        f"value={claim.value!r}",
        f"unit={claim.unit!r}",
        f"qualifier={claim.qualifier!r}",
        f"speaker={claim.speaker!r}",
    ]
    return "{" + ", ".join(parts) + "}"


def _build_prompt(claim_a: Claim, claim_b: Claim | None) -> str:
    if claim_b is None:
        return (
            "claim_a: "
            + _describe_claim(claim_a)
            + "\nclaim_b: (none -- no other claim shares this canonical_metric_key+period)"
        )
    return f"claim_a: {_describe_claim(claim_a)}\nclaim_b: {_describe_claim(claim_b)}"


def _cache_path(prompt: str, repeat: int = 0) -> Path:
    """Cache location for a prompt. repeat=0 hashes the bare prompt (the pre-existing key, so the
    on-disk cache stays valid); repeat>0 salts only the hash input, so a stability study can re-ask
    the same pair independently while the prompt sent to the API is unchanged."""
    key = prompt if repeat == 0 else f"{prompt}\n#repeat={repeat}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return settings.raw_dir / "llm_cache" / MODEL_ID / f"{digest}.json"


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    """Return the cached judgment, or None to treat it as a miss.

    Mirrors edgar.py's _get_json: a prior run may have cached a corrupt/partial payload (process
    killed mid-write) or a structurally-invalid one (an older version of this module wrote a
    different shape) -- either way, evict it and re-fetch rather than trusting it forever.
    """
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        cache_path.unlink(missing_ok=True)
        return None

    if not isinstance(data, dict) or "verdict" not in data or "rationale" not in data:
        cache_path.unlink(missing_ok=True)
        return None
    try:
        Verdict(data["verdict"])
    except ValueError:
        cache_path.unlink(missing_ok=True)
        return None

    return data


def _call_llm(prompt: str) -> dict[str, Any]:
    import anthropic

    client = _get_client()
    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_verdict"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError as e:
        raise RuntimeError("Anthropic API rate-limited this request -- retry after a delay.") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Could not reach the Anthropic API -- check network access.") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(
            f"Anthropic API returned an error (status {e.status_code}): {e.message}"
        ) from e

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return {
        "verdict": tool_use.input["verdict"],
        "rationale": tool_use.input["rationale"],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


def is_cached(claim_a: Claim, claim_b: Claim | None, repeat: int = 0) -> bool:
    """True if judging this pair would be served from disk (no API cost). Existence check only: a
    corrupt entry still reports True and is evicted/re-fetched on the next judge call."""
    return _cache_path(_build_prompt(claim_a, claim_b), repeat).exists()


def cached_usage(claim_a: Claim, claim_b: Claim | None, repeat: int = 0) -> dict[str, int] | None:
    """The {"input_tokens","output_tokens"} stored with the cached judgment, or None if there is no
    readable entry. Lets callers price a cache hit at what it cost when it was paid for."""
    cache_path = _cache_path(_build_prompt(claim_a, claim_b), repeat)
    cached = _read_cache(cache_path) if cache_path.exists() else None
    usage = cached.get("usage") if cached else None
    return usage if isinstance(usage, dict) else None


def judge_pair_with_usage(
    claim_a: Claim, claim_b: Claim | None, repeat: int = 0
) -> tuple[Prediction, dict[str, int] | None]:
    """Like judge_pair, but also returns the live call's {"input_tokens","output_tokens"}, or None
    when the answer came from the cache -- lets callers enforce a spend budget."""
    prompt = _build_prompt(claim_a, claim_b)
    cache_path = _cache_path(prompt, repeat)

    usage: dict[str, int] | None = None
    cached = _read_cache(cache_path) if cache_path.exists() else None
    if cached is None:
        cached = _call_llm(prompt)
        atomic_write_text(cache_path, json.dumps(cached))
        usage = cached["usage"]

    prediction = Prediction(
        claim_a=claim_a,
        claim_b=claim_b,
        verdict=Verdict(cached["verdict"]),
        rationale=cached["rationale"],
    )
    return prediction, usage


def judge_pair(claim_a: Claim, claim_b: Claim | None, repeat: int = 0) -> Prediction:
    """Ask the LLM to judge one candidate pair (or unsupported singleton), returning a Prediction
    in the same shape Phase 4's rule-based check_pair() produces."""
    return judge_pair_with_usage(claim_a, claim_b, repeat)[0]


def generate_llm_predictions(claims: list[Claim]) -> list[Prediction]:
    """Same grouping/pairing logic as checker.generate_predictions(), but judged by the LLM."""
    predictions: list[Prediction] = []
    for (_subject, _metric_key, _period), group in group_by_metric_and_period(claims).items():
        if len(group) == 1:
            predictions.append(judge_pair(group[0], None))
            continue
        for i, claim_a in enumerate(group):
            for claim_b in group[i + 1 :]:
                if claim_a.document_id == claim_b.document_id:
                    continue
                predictions.append(judge_pair(claim_a, claim_b))
    return predictions
