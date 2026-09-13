from decimal import Decimal

from crosscheck.extraction.deck import ExtractedRow, _build_claims_from_rows, _cluster_rows

PAGE_WIDTH = 792.0
PAGE_HEIGHT = 612.0


def test_maps_known_rows_to_claims():
    rows = [
        ExtractedRow("Net Revenue", "3,075.1", (66.7, 196.9, 300.8, 208.9)),
        ExtractedRow("Net Income", "33.4", (66.7, 321.2, 290.6, 333.2)),
        ExtractedRow("Earnings Per Share (EPS)", "0.14", (66.7, 343.2, 290.6, 374.4)),
        ExtractedRow("Adjusted EBITDA*", "305.0", (66.7, 384.2, 294.8, 396.2)),
    ]
    pairs = _build_claims_from_rows(
        rows,
        document_id=1,
        subject="X",
        period="FY2020-Q3",
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    by_key = {c.canonical_metric_key: c for c, _ in pairs}

    assert by_key["revenue.total"].value == Decimal("3075100000")
    assert by_key["income.net"].value == Decimal("33400000")
    assert by_key["eps.diluted.gaap"].value == Decimal("0.14")
    assert by_key["ebitda.adjusted"].value == Decimal("305000000")


def test_eps_is_not_scaled_to_millions_unlike_dollar_rows():
    rows = [ExtractedRow("Earnings Per Share (EPS)", "0.14", (66.7, 343.2, 290.6, 374.4))]
    pairs = _build_claims_from_rows(
        rows,
        document_id=1,
        subject="X",
        period="FY2020-Q3",
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    claim, _ = pairs[0]
    assert claim.unit == "USD_per_share"
    assert claim.value == Decimal("0.14")  # not 140000.0


def test_malformed_value_cell_is_skipped_not_errored():
    rows = [
        ExtractedRow("Net Revenue", "N/A", (66.7, 196.9, 300.8, 208.9)),
        ExtractedRow("Net Income", "33.4", (66.7, 321.2, 290.6, 333.2)),
    ]
    pairs = _build_claims_from_rows(
        rows,
        document_id=1,
        subject="X",
        period="FY2020-Q3",
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    # The malformed "N/A" row is dropped; the well-formed row after it still extracts fine.
    assert len(pairs) == 1
    assert pairs[0][0].canonical_metric_key == "income.net"


def test_unmapped_row_is_skipped_not_errored():
    rows = [
        ExtractedRow("Gross Profit", "313.8", (66.7, 220.6, 294.8, 232.6)),
        ExtractedRow("SG&A", "219.5", (66.7, 249.1, 294.8, 261.1)),
    ]
    pairs = _build_claims_from_rows(
        rows,
        document_id=1,
        subject="X",
        period="FY2020-Q3",
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    assert pairs == []


def test_page_bbox_span_normalized_0_to_1():
    rows = [ExtractedRow("Net Revenue", "3,075.1", (66.7, 196.9, 300.8, 208.9))]
    pairs = _build_claims_from_rows(
        rows,
        document_id=1,
        subject="X",
        period="FY2020-Q3",
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    _, span = pairs[0]
    assert span.span_json.page == 15
    assert 0.0 <= span.span_json.x0 < span.span_json.x1 <= 1.0
    assert 0.0 <= span.span_json.y0 < span.span_json.y1 <= 1.0


def test_cluster_rows_uses_value_column_as_row_anchor():
    # Regression fixture for the real bug found: without a bounded reach on the last anchor's
    # band, its label swept in the next visual row's label text too.
    words = [
        {"text": "Adjusted", "x0": 66.7, "x1": 124.3, "top": 384.2, "bottom": 396.2},
        {"text": "EBITDA*", "x0": 127.8, "x1": 183.0, "top": 384.2, "bottom": 396.2},
        {"text": "305.0", "x0": 258.5, "x1": 294.8, "top": 384.2, "bottom": 396.2},
        {"text": "Adjusted", "x0": 66.7, "x1": 123.4, "top": 406.2, "bottom": 418.2},
        {"text": "EBITDA", "x0": 127.1, "x1": 174.3, "top": 406.2, "bottom": 418.2},
    ]
    rows = _cluster_rows(words)
    assert len(rows) == 1
    assert rows[0].label == "Adjusted EBITDA*"
    assert rows[0].value_text == "305.0"
