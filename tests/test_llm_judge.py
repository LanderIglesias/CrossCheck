import hashlib
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
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.call_count += 1
        self.calls.append(kwargs)
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


def _setup_fake(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_judge.settings, "data_dir", tmp_path)
    monkeypatch.setattr(llm_judge.settings, "anthropic_api_key", "fake-key-for-test")
    monkeypatch.setattr(llm_judge, "_client", None)
    fake_client = _FakeClient("consistent", "Values agree within rounding.")
    monkeypatch.setattr(llm_judge, "_get_client", lambda: fake_client)
    return fake_client


def test_repeat_zero_keeps_existing_cache_path(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_judge.settings, "data_dir", tmp_path)
    p = "some prompt"
    digest = hashlib.sha256(p.encode("utf-8")).hexdigest()
    expected = llm_judge.settings.raw_dir / "llm_cache" / llm_judge.MODEL_ID / f"{digest}.json"
    assert llm_judge._cache_path(p) == llm_judge._cache_path(p, 0) == expected


def test_repeat_uses_distinct_cache_and_same_prompt(monkeypatch, tmp_path):
    fake_client = _setup_fake(monkeypatch, tmp_path)
    p = "some prompt"
    paths = {llm_judge._cache_path(p, r) for r in (0, 1, 2)}
    assert len(paths) == 3

    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1001000", "USD")
    judge_pair(a, b, repeat=1)
    judge_pair(a, b, repeat=1)
    assert fake_client.messages.call_count == 1
    judge_pair(a, b, repeat=2)
    assert fake_client.messages.call_count == 2
    assert all("#repeat" not in c["messages"][0]["content"] for c in fake_client.messages.calls)


def test_judge_pair_with_usage_live_then_cached(monkeypatch, tmp_path):
    _setup_fake(monkeypatch, tmp_path)
    a = _claim(1, "revenue.total", "1000000", "USD")
    b = _claim(2, "revenue.total", "1001000", "USD")

    assert not llm_judge.is_cached(a, b)
    assert llm_judge.cached_usage(a, b) is None
    _, usage = llm_judge.judge_pair_with_usage(a, b)
    assert usage == {"input_tokens": 100, "output_tokens": 20}
    assert llm_judge.is_cached(a, b)
    _, usage = llm_judge.judge_pair_with_usage(a, b)
    assert usage is None
    assert llm_judge.cached_usage(a, b) == {"input_tokens": 100, "output_tokens": 20}
