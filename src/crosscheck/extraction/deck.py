"""Automated Claim extraction from PPC's real investor deck PDF (page 15's financial table).

Real inspection of the deck (all 20 pages) found that pdfplumber's automatic table detection
(`page.find_tables()`) does not cleanly grid this specific table -- the deck's PDF layout wraps
some row labels across two lines (e.g. "Earnings Per Share" / "(EPS)" with the value line
in between), and the surrounding narrative bullet text bleeds into detected table cells. So this
extractor instead clusters raw word positions (`page.extract_words()`) into rows using the
Q3-20 value column's y-positions as row anchors, then attaches whichever label words fall in the
vertical band around each anchor -- a real, non-obvious wrinkle specific to this PDF's layout,
not a generic table parser.

Only the 4 rows with an existing hand-labeled PPC counterpart are mapped (see
scripts/populate_phase0_gold_labels.py) -- not every row in the table, matching Phase 3's
XBRL-extractor scope discipline.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from crosscheck.models import Claim, EvidenceSpan, PageBBoxSpan, SpanType

PAGE_NUMBER = 15  # 1-indexed; confirmed by directly reading the real deck PDF

# Region of page 15 containing the "Main Indicators ($M)" table, in PDF points -- found by
# inspecting real word positions on this exact page. Specific to this one deck's layout.
_LABEL_X_RANGE = (55.0, 210.0)
_VALUE_X_RANGE = (245.0, 310.0)  # the Q3-20 column specifically, not the Q3-19 comparative column
_TABLE_Y_RANGE = (140.0, 410.0)

# canonical_metric_key, metric label, unit, scale-to-raw-dollars
# (the deck reports in $M except EPS, which is already dollars/share)
_MILLIONS = Decimal("1000000")
ROW_LABEL_TO_CANONICAL_KEY: dict[str, tuple[str, str, str, Decimal]] = {
    "net revenue": ("revenue.total", "Net Revenue", "USD", _MILLIONS),
    "net income": ("income.net", "Net Income", "USD", _MILLIONS),
    "earnings per share (eps)": (
        "eps.diluted.gaap",
        "Earnings Per Share (EPS)",
        "USD_per_share",
        Decimal(1),
    ),
    "adjusted ebitda": ("ebitda.adjusted", "Adjusted EBITDA", "USD", _MILLIONS),
}


def _normalize_label(text: str) -> str:
    return " ".join(text.replace("*", "").split()).casefold()


@dataclass(frozen=True)
class ExtractedRow:
    label: str
    value_text: str
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom, in PDF points


def _build_claims_from_rows(
    rows: list[ExtractedRow],
    document_id: int,
    subject: str,
    period: str,
    page_width: float,
    page_height: float,
) -> list[tuple[Claim, EvidenceSpan]]:
    """Pure, unit-testable core: maps extracted rows to Claims. No PDF library involved here."""
    results: list[tuple[Claim, EvidenceSpan]] = []

    for row in rows:
        mapped = ROW_LABEL_TO_CANONICAL_KEY.get(_normalize_label(row.label))
        if mapped is None:
            continue
        canonical_key, metric_label, unit, scale = mapped

        raw_value = row.value_text.replace(",", "").replace("%", "").strip()
        try:
            value = Decimal(raw_value) * scale
        except InvalidOperation:
            # A malformed or non-numeric value cell (e.g. "N/A", a footnote marker misread as
            # the value) -- skip this row rather than crash the whole extraction on one bad cell.
            continue

        claim = Claim(
            document_id=document_id,
            subject=subject,
            metric=metric_label,
            canonical_metric_key=canonical_key,
            period=period,
            value=value,
            unit=unit,
            qualifier=None,
            speaker=None,
            extraction_method="automated_deck",
            model_id=None,
            prompt_hash=None,
            confidence=1.0,
        )
        x0, top, x1, bottom = row.bbox
        span = EvidenceSpan(
            claim_id=-1,  # placeholder; caller fills in the real claim_id after INSERT
            span_type=SpanType.PAGE_BBOX,
            span_json=PageBBoxSpan(
                page=PAGE_NUMBER,
                x0=x0 / page_width,
                y0=top / page_height,
                x1=x1 / page_width,
                y1=bottom / page_height,
            ),
        )
        results.append((claim, span))

    return results


def _cluster_rows(words: list[dict[str, Any]]) -> list[ExtractedRow]:
    """Group extract_words() output into label/value rows using the value column's y-positions
    as row anchors (see module docstring for why label text can't be grouped by matching `top`
    alone)."""
    label_words = [
        w
        for w in words
        if _LABEL_X_RANGE[0] <= w["x0"]
        and w["x1"] <= _LABEL_X_RANGE[1]
        and _TABLE_Y_RANGE[0] <= w["top"] <= _TABLE_Y_RANGE[1]
    ]
    value_words = sorted(
        (
            w
            for w in words
            if _VALUE_X_RANGE[0] <= w["x0"] <= _VALUE_X_RANGE[1]
            and _TABLE_Y_RANGE[0] <= w["top"] <= _TABLE_Y_RANGE[1]
        ),
        key=lambda w: w["top"],
    )

    # For the first/last anchor there's no neighbor to take a midpoint with -- cap the open side
    # to a fixed reach instead of leaving it unbounded, otherwise it can sweep in an unrelated
    # row's label (real bug found: without this cap, the last anchor's band swallowed the next
    # visual row's "Adjusted EBITDA Margin" label text too). All real row labels here sit within
    # a line or two of their own value's `top`, well under this reach.
    _boundary_reach = 20.0

    rows: list[ExtractedRow] = []
    for i, anchor in enumerate(value_words):
        band_lo = (
            (value_words[i - 1]["top"] + anchor["top"]) / 2
            if i > 0
            else anchor["top"] - _boundary_reach
        )
        band_hi = (
            (anchor["top"] + value_words[i + 1]["top"]) / 2
            if i + 1 < len(value_words)
            else anchor["top"] + _boundary_reach
        )
        band_labels = sorted(
            (w for w in label_words if band_lo <= w["top"] < band_hi),
            key=lambda w: (w["top"], w["x0"]),
        )
        if not band_labels:
            continue

        label_text = " ".join(w["text"] for w in band_labels)
        x0 = min(w["x0"] for w in [*band_labels, anchor])
        top = min(w["top"] for w in [*band_labels, anchor])
        x1 = max(w["x1"] for w in [*band_labels, anchor])
        bottom = max(w["bottom"] for w in [*band_labels, anchor])
        rows.append(
            ExtractedRow(label=label_text, value_text=anchor["text"], bbox=(x0, top, x1, bottom))
        )

    return rows


def extract_claims(
    pdf_path: Path, document_id: int, subject: str, period: str
) -> list[tuple[Claim, EvidenceSpan]]:
    """Extract the 4 mapped Claims from PPC's real deck PDF, page 15's financial table."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[PAGE_NUMBER - 1]
        words = page.extract_words()
        rows = _cluster_rows(words)
        return _build_claims_from_rows(rows, document_id, subject, period, page.width, page.height)
