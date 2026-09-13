from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, model_validator


class Modality(StrEnum):
    AUDIO = "audio"
    DECK = "deck"
    FILING = "filing"
    XBRL = "xbrl"


class SpanType(StrEnum):
    AUDIO_TS = "audio_ts"
    PAGE_BBOX = "page_bbox"
    CHAR_OFFSET = "char_offset"
    XBRL_FACT = "xbrl_fact"


class Verdict(StrEnum):
    CONSISTENT = "consistent"
    DISCREPANT = "discrepant"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class Company(BaseModel):
    id: int | None = None
    ticker: str
    cik: str
    name: str


class Quarter(BaseModel):
    id: int | None = None
    company_id: int
    fiscal_year: int
    fiscal_period: str
    call_date: date | None = None


class Document(BaseModel):
    id: int | None = None
    quarter_id: int
    modality: Modality
    source_url: str
    content_hash: str
    local_path: str
    retrieved_at: datetime | None = None


class Claim(BaseModel):
    id: int | None = None
    document_id: int
    subject: str
    metric: str
    canonical_metric_key: str
    period: str
    value: Decimal | None = None
    unit: str | None = None
    qualifier: str | None = None
    speaker: str | None = None
    extraction_method: str
    model_id: str | None = None
    prompt_hash: str | None = None
    confidence: float | None = None


class AudioTimestampSpan(BaseModel):
    """span_json shape for SpanType.AUDIO_TS. See db/schema.md."""

    start_sec: float
    end_sec: float


class PageBBoxSpan(BaseModel):
    """span_json shape for SpanType.PAGE_BBOX. Coordinates normalized 0-1. See db/schema.md."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class CharOffsetSpan(BaseModel):
    """span_json shape for SpanType.CHAR_OFFSET, into the filing's extracted plaintext."""

    start: int
    end: int


class XBRLFactSpan(BaseModel):
    """span_json shape for SpanType.XBRL_FACT."""

    tag: str
    context_ref: str
    unit_ref: str


_SPAN_PAYLOAD_BY_TYPE: dict[SpanType, type[BaseModel]] = {
    SpanType.AUDIO_TS: AudioTimestampSpan,
    SpanType.PAGE_BBOX: PageBBoxSpan,
    SpanType.CHAR_OFFSET: CharOffsetSpan,
    SpanType.XBRL_FACT: XBRLFactSpan,
}


class EvidenceSpan(BaseModel):
    id: int | None = None
    claim_id: int
    span_type: SpanType
    span_json: AudioTimestampSpan | PageBBoxSpan | CharOffsetSpan | XBRLFactSpan

    @model_validator(mode="after")
    def _span_json_matches_span_type(self) -> EvidenceSpan:
        expected = _SPAN_PAYLOAD_BY_TYPE[self.span_type]
        if not isinstance(self.span_json, expected):
            raise ValueError(
                f"span_type={self.span_type!r} requires span_json to be {expected.__name__}, "
                f"got {type(self.span_json).__name__}"
            )
        return self


class GoldLabel(BaseModel):
    id: int | None = None
    claim_a_id: int
    claim_b_id: int | None = None
    verdict: Verdict
    rationale: str
    labeled_by: str
    labeled_at: datetime | None = None
