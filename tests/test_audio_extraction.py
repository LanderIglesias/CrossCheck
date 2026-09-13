from dataclasses import dataclass
from decimal import Decimal

import pytest

from crosscheck.extraction import audio
from crosscheck.extraction.audio import (
    LLMExtractorNotConfiguredError,
    extract_claims,
    merge_transcript_with_speakers,
)


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_merge_assigns_speaker_with_greatest_time_overlap(tmp_path):
    asr = _write(tmp_path / "a.asr.txt", "[10.0-20.0] hello there\n[20.0-30.0] second segment\n")
    diar = _write(
        tmp_path / "a.diar.txt",
        "[5.0-15.0] SPEAKER_00\n[15.0-25.0] SPEAKER_01\n[25.0-35.0] SPEAKER_02\n",
    )
    merged = merge_transcript_with_speakers(asr, diar)
    lines = merged.splitlines()
    assert lines[0] == "[10.0-20.0] SPEAKER_00: hello there"  # 5s overlap with SPEAKER_00
    assert lines[1] == "[20.0-30.0] SPEAKER_01: second segment"  # 5s overlap w/ 01 vs 5s w/ 02


def test_merge_handles_no_overlapping_diarization_turn(tmp_path):
    asr = _write(tmp_path / "a.asr.txt", "[100.0-110.0] no diarization here\n")
    diar = _write(tmp_path / "a.diar.txt", "[0.0-1.0] SPEAKER_00\n")
    merged = merge_transcript_with_speakers(asr, diar)
    assert "UNKNOWN" in merged


@dataclass
class _FakeToolUseBlock:
    type: str
    input: dict


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    content: list
    usage: _FakeUsage


class _FakeMessages:
    def __init__(self, claims: list[dict]):
        self.claims = claims
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _FakeResponse(
            content=[_FakeToolUseBlock("tool_use", {"claims": self.claims})],
            usage=_FakeUsage(input_tokens=500, output_tokens=50),
        )


class _FakeClient:
    def __init__(self, claims: list[dict]):
        self.messages = _FakeMessages(claims)


_SAMPLE_CLAIM = {
    "canonical_metric_key": "revenue.total",
    "metric": "net revenues",
    "value": 3080000000,
    "unit": "USD",
    "qualifier": "spoken approx",
    "speaker": "SPEAKER_06",
    "start_sec": 137.4,
    "end_sec": 152.4,
}


def test_extract_claims_parses_mocked_response(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.settings, "data_dir", tmp_path)
    monkeypatch.setattr(audio.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(audio, "_client", None)
    fake_client = _FakeClient([_SAMPLE_CLAIM])
    monkeypatch.setattr(audio, "_get_client", lambda: fake_client)

    pairs = extract_claims(
        "[137.4-152.4] SPEAKER_06: some transcript text",
        document_id=1,
        subject="X",
        period="FY2020-Q3",
    )

    assert len(pairs) == 1
    claim, span = pairs[0]
    assert claim.canonical_metric_key == "revenue.total"
    assert claim.value == Decimal("3080000000")
    assert claim.extraction_method == "automated_audio"
    assert claim.model_id == audio.MODEL_ID
    assert span.span_json.start_sec == 137.4
    assert span.span_json.end_sec == 152.4
    assert fake_client.messages.call_count == 1


def test_extract_claims_uses_cache_on_second_call(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.settings, "data_dir", tmp_path)
    monkeypatch.setattr(audio.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(audio, "_client", None)
    fake_client = _FakeClient([_SAMPLE_CLAIM])
    monkeypatch.setattr(audio, "_get_client", lambda: fake_client)

    transcript = "[137.4-152.4] SPEAKER_06: some transcript text"
    extract_claims(transcript, document_id=1, subject="X", period="FY2020-Q3")
    extract_claims(transcript, document_id=1, subject="X", period="FY2020-Q3")

    assert fake_client.messages.call_count == 1


def test_extract_claims_skips_out_of_scope_canonical_key(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.settings, "data_dir", tmp_path)
    monkeypatch.setattr(audio.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(audio, "_client", None)
    off_scope_claim = {**_SAMPLE_CLAIM, "canonical_metric_key": "income.net"}
    fake_client = _FakeClient([off_scope_claim])
    monkeypatch.setattr(audio, "_get_client", lambda: fake_client)

    pairs = extract_claims(
        "[137.4-152.4] SPEAKER_06: text", document_id=1, subject="X", period="FY2020-Q3"
    )
    assert pairs == []


def test_raises_clear_error_when_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.settings, "data_dir", tmp_path)
    monkeypatch.setattr(audio.settings, "anthropic_api_key", None)
    monkeypatch.setattr(audio, "_client", None)

    with pytest.raises(LLMExtractorNotConfiguredError, match="ANTHROPIC_API_KEY"):
        extract_claims("[1.0-2.0] SPEAKER_00: x", document_id=1, subject="X", period="FY2020-Q3")
