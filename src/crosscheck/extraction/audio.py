"""Automated Claim extraction from PPC's real ASR transcript + diarization turns (Phase 7).

Unlike XBRL/deck (structured data with known field positions), spoken financial figures require
actual language understanding -- recognizing "$3.08 billion" as a value+unit, "adjusted GAP EPS"
as a qualifier despite a real ASR transcription typo, and which sentence is a company claim vs.
narrative filler. This reuses src/crosscheck/consistency/llm_judge.py's pattern (lazy client,
forced strict-schema tool call, disk cache by prompt hash) for extraction rather than judging.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from crosscheck.config import settings
from crosscheck.io_utils import atomic_write_text
from crosscheck.models import AudioTimestampSpan, Claim, EvidenceSpan, SpanType

MODEL_ID = "claude-sonnet-5"

# Only these 3 keys have an existing hand-labeled PPC audio gold claim to validate against.
_TARGET_CANONICAL_KEYS = ["revenue.total", "eps.diluted.adjusted", "ebitda.adjusted"]

_LINE_RE = re.compile(r"^\[(?P<start>[\d.]+)-(?P<end>[\d.]+)\]\s*(?P<rest>.*)$")

_SYSTEM_PROMPT = """\
You are extracting structured financial claims from a real, imperfect ASR (speech-to-text) \
transcript of an earnings call, with each line prefixed by its [start-end] timestamp range (in \
seconds) and speaker label. The transcript may contain transcription errors (e.g. "GAP EPS" \
instead of "GAAP EPS") -- use your judgment to recognize the intended meaning.

Find every place a company spokesperson states one of these specific metrics for the current \
quarter, and call submit_claims once with one entry per metric found:
- revenue.total (total company net revenue for the quarter)
- eps.diluted.adjusted (adjusted / non-GAAP diluted earnings per share)
- ebitda.adjusted (adjusted / non-GAAP EBITDA)

For each claim: copy the exact [start-end] timestamp range and speaker label from the transcript \
line it appears in (do not invent or approximate these), extract the numeric value in raw units \
(e.g. "$3.08 billion" -> 3080000000, not 3.08), and note any qualifier (e.g. "non-GAAP", \
"adjusted", "spoken approx"). If a metric is never explicitly stated, omit it -- do not guess.

Use exactly "USD" as the unit for dollar-amount metrics (revenue, EBITDA) and exactly \
"USD_per_share" for per-share metrics (EPS) -- this project's existing hand-labeled data always \
uses these two unit strings, not "USD/share" or "$" or any other spelling."""

_TOOL = {
    "name": "submit_claims",
    "description": "Submit the financial claims found in the transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "canonical_metric_key": {
                            "type": "string",
                            "enum": _TARGET_CANONICAL_KEYS,
                        },
                        "metric": {"type": "string"},
                        "value": {"type": "number"},
                        "unit": {"type": "string"},
                        "qualifier": {"type": "string"},
                        "speaker": {"type": "string"},
                        "start_sec": {"type": "number"},
                        "end_sec": {"type": "number"},
                    },
                    "required": [
                        "canonical_metric_key",
                        "metric",
                        "value",
                        "unit",
                        "qualifier",
                        "speaker",
                        "start_sec",
                        "end_sec",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["claims"],
        "additionalProperties": False,
    },
    "strict": True,
}

_client: Any = None


class LLMExtractorNotConfiguredError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is missing -- the LLM extractor cannot run without it."""


def _get_client() -> Any:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise LLMExtractorNotConfiguredError(
                "ANTHROPIC_API_KEY is not set in .env -- audio claim extraction requires a real "
                "Anthropic API key (get one at console.anthropic.com). See .env.example."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _parse_timestamped_lines(path: Path) -> list[tuple[float, float, str]]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE_RE.match(line)
        if m:
            lines.append((float(m.group("start")), float(m.group("end")), m.group("rest")))
    return lines


def merge_transcript_with_speakers(asr_path: Path, diar_path: Path) -> str:
    """Merge ASR segments with diarization turns by timestamp overlap, producing one
    "[start-end] SPEAKER_NN: text" line per ASR segment. Speaker labels stay anonymized
    (e.g. "SPEAKER_06") -- mapping them to real names is out of scope here."""
    asr_segments = _parse_timestamped_lines(asr_path)
    diar_turns = _parse_timestamped_lines(diar_path)

    lines = []
    for start, end, text in asr_segments:
        best_speaker = "UNKNOWN"
        best_overlap = 0.0
        for turn_start, turn_end, speaker in diar_turns:
            overlap = min(end, turn_end) - max(start, turn_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        lines.append(f"[{start:.1f}-{end:.1f}] {best_speaker}: {text}")

    return "\n".join(lines)


def _cache_path(transcript: str) -> Path:
    # Hash the system prompt together with the transcript -- a prompt/schema edit must invalidate
    # the cache too, otherwise a stale response from before the edit would be silently reused.
    digest = hashlib.sha256((_SYSTEM_PROMPT + "\n---\n" + transcript).encode("utf-8")).hexdigest()
    return settings.raw_dir / "llm_cache" / MODEL_ID / f"audio_{digest}.json"


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        cache_path.unlink(missing_ok=True)
        return None
    if not isinstance(data, dict) or "claims" not in data:
        cache_path.unlink(missing_ok=True)
        return None
    return data


def _call_llm(transcript: str) -> dict[str, Any]:
    import anthropic

    client = _get_client()
    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_claims"},
            messages=[{"role": "user", "content": transcript}],
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
        "claims": tool_use.input["claims"],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


def extract_claims(
    transcript: str, document_id: int, subject: str, period: str
) -> list[tuple[Claim, EvidenceSpan]]:
    """Extract Claims for the 3 target canonical_metric_keys from a speaker-labeled transcript
    (see merge_transcript_with_speakers)."""
    cache_path = _cache_path(transcript)
    cached = _read_cache(cache_path) if cache_path.exists() else None
    if cached is None:
        cached = _call_llm(transcript)
        atomic_write_text(cache_path, json.dumps(cached))

    prompt_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    results: list[tuple[Claim, EvidenceSpan]] = []
    for item in cached["claims"]:
        if item["canonical_metric_key"] not in _TARGET_CANONICAL_KEYS:
            continue
        claim = Claim(
            document_id=document_id,
            subject=subject,
            metric=item["metric"],
            canonical_metric_key=item["canonical_metric_key"],
            period=period,
            value=Decimal(str(item["value"])),
            unit=item["unit"],
            qualifier=item["qualifier"] or None,
            speaker=item["speaker"] or None,
            extraction_method="automated_audio",
            model_id=MODEL_ID,
            prompt_hash=prompt_hash,
            confidence=1.0,
        )
        span = EvidenceSpan(
            claim_id=-1,  # placeholder; caller fills in the real claim_id after INSERT
            span_type=SpanType.AUDIO_TS,
            span_json=AudioTimestampSpan(start_sec=item["start_sec"], end_sec=item["end_sec"]),
        )
        results.append((claim, span))

    return results
