from dataclasses import dataclass
from decimal import Decimal

import pytest

from crosscheck.consistency import llm_judge
from crosscheck.consistency.llm_judge import LLMJudgeNotConfiguredError, judge_pair
from crosscheck.models import Claim, Verdict


def _claim(document_id: int, canonical_metric_key: str, value, unit: str, period="FY2020-Q3"):
    return Claim(
        document_id=document_id,
        subject="X",
        metric=canonical_metric_key,
        canonical_metric_key=canonical_metric_key,
        period=period,
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        extraction_method="manual",
    )


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
    def __init__(self, verdict: str, rationale: str):
        self.verdict = verdict
        self.rationale = rationale
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _FakeResponse(
            content=[
                _FakeToolUseBlock(
                    "tool_use", {"verdict": self.verdict, "rationale": self.rationale}
                )
            ],
            usage=_FakeUsage(input_tokens=100, output_tokens=20),
        )


class _FakeClient:
    def __init__(self, verdict: str, rationale: str):
        self.messages = _FakeMessages(verdict, rationale)


def test_build_prompt_includes_tolerance_and_both_claims():
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1001000", "USD")
    prompt = llm_judge._build_prompt(a, b)
    assert "revenue.total" in prompt
    assert "1000000" in prompt and "1001000" in prompt
    assert "0.5%" in llm_judge._SYSTEM_PROMPT


def test_build_prompt_handles_no_claim_b():
    a = _claim(1, "cashflow.free", "694000000", "USD")
    prompt = llm_judge._build_prompt(a, None)
    assert "none" in prompt.lower()


def test_judge_pair_parses_mocked_response(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_judge.settings, "data_dir", tmp_path)
    monkeypatch.setattr(llm_judge.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(llm_judge, "_client", None)
    fake_client = _FakeClient("consistent", "Values agree within rounding.")
    monkeypatch.setattr(llm_judge, "_get_client", lambda: fake_client)

    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1001000", "USD")
    prediction = judge_pair(a, b)

    assert prediction.verdict == Verdict.CONSISTENT
    assert prediction.rationale == "Values agree within rounding."
    assert fake_client.messages.call_count == 1


def test_judge_pair_uses_cache_on_second_call(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_judge.settings, "data_dir", tmp_path)
    monkeypatch.setattr(llm_judge.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(llm_judge, "_client", None)
    fake_client = _FakeClient("discrepant", "Values differ materially.")
    monkeypatch.setattr(llm_judge, "_get_client", lambda: fake_client)

    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "2000000", "USD")

    judge_pair(a, b)
    judge_pair(a, b)

    assert fake_client.messages.call_count == 1


def test_raises_clear_error_when_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_judge.settings, "data_dir", tmp_path)
    monkeypatch.setattr(llm_judge.settings, "anthropic_api_key", None)
    monkeypatch.setattr(llm_judge, "_client", None)

    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1001000", "USD")

    with pytest.raises(LLMJudgeNotConfiguredError, match="ANTHROPIC_API_KEY"):
        judge_pair(a, b)
