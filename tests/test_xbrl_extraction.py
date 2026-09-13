from decimal import Decimal

from crosscheck.extraction.xbrl import extract_claims

ACCN = "0000802481-20-000080"

# Synthetic but structurally real companyfacts shape: same accn repeats across a 9-month-YTD
# entry (decoy) and the actual quarterly entry, distinguished only by start/end duration -- this
# is the real wrinkle the extractor's filtering logic must handle correctly.
SYNTHETIC_FACTS = {
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "start": "2019-12-30",
                            "end": "2020-09-27",
                            "val": 8974072000,
                            "accn": ACCN,
                            "fy": 2020,
                            "fp": "Q3",
                            "form": "10-Q",
                            "filed": "2020-10-29",
                        },
                        {
                            "start": "2020-06-29",
                            "end": "2020-09-27",
                            "val": 3075121000,
                            "accn": ACCN,
                            "fy": 2020,
                            "fp": "Q3",
                            "form": "10-Q",
                            "filed": "2020-10-29",
                        },
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "start": "2020-06-29",
                            "end": "2020-09-27",
                            "val": 33446000,
                            "accn": ACCN,
                            "fy": 2020,
                            "fp": "Q3",
                            "form": "10-Q",
                            "filed": "2020-10-29",
                        },
                    ]
                }
            },
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [
                        {
                            "start": "2020-06-29",
                            "end": "2020-09-27",
                            "val": 0.14,
                            "accn": ACCN,
                            "fy": 2020,
                            "fp": "Q3",
                            "form": "10-Q",
                            "filed": "2020-10-29",
                        },
                    ]
                }
            },
            # Not in TAG_TO_CANONICAL_KEY -- should never appear in results.
            "SomeUnmappedTag": {
                "units": {"USD": [{"start": "2020-06-29", "end": "2020-09-27", "val": 1}]}
            },
        }
    }
}


def _extract(facts=SYNTHETIC_FACTS, accn=ACCN):
    return extract_claims(
        facts,
        document_id=1,
        subject="Pilgrim's Pride Corporation",
        period="FY2020-Q3",
        accession_number=accn,
    )


def test_picks_quarterly_fact_not_ytd_decoy():
    pairs = _extract()
    revenue = next(c for c, _ in pairs if c.canonical_metric_key == "revenue.total")
    assert revenue.value == Decimal("3075121000")


def test_extracts_only_mapped_tags():
    pairs = _extract()
    keys = {c.canonical_metric_key for c, _ in pairs}
    assert keys == {"revenue.total", "income.net", "eps.diluted.gaap"}


def test_normalizes_eps_unit_to_gold_set_convention():
    pairs = _extract()
    eps = next(c for c, _ in pairs if c.canonical_metric_key == "eps.diluted.gaap")
    assert eps.unit == "USD_per_share"
    _, span = next((c, s) for c, s in pairs if c.canonical_metric_key == "eps.diluted.gaap")
    # The evidence span keeps the raw XBRL unit key -- normalization is a Claim-layer convention,
    # not a claim about what the source XBRL actually said.
    assert span.span_json.unit_ref == "USD/shares"


def test_evidence_span_carries_tag_and_accn():
    pairs = _extract()
    _, span = next((c, s) for c, s in pairs if c.canonical_metric_key == "income.net")
    assert span.span_json.tag == "NetIncomeLoss"
    assert span.span_json.context_ref == ACCN
    assert span.span_json.unit_ref == "USD"


def test_missing_tag_is_skipped_not_errored():
    facts = {"facts": {"us-gaap": {}}}
    pairs = _extract(facts=facts)
    assert pairs == []


def test_wrong_fy_fp_but_correct_accn_still_matches():
    """Regression for a real bug: GE's own companyfacts JSON tags its FY2020-Q1 10-Q fact with
    fy=2019/fp="Q3" even though accn and start/end dates correctly identify the Q1 2020 quarterly
    fact. Matching must key off accn, not fy/fp, or GE's real data is silently skipped."""
    ge_accn = "0000040545-20-000021"
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2020-01-01",
                                "end": "2020-03-31",
                                "val": 20524000000,
                                "accn": ge_accn,
                                "fy": 2019,  # wrong on purpose -- this is the real GE bug
                                "fp": "Q3",  # wrong on purpose -- this is the real GE bug
                                "form": "10-Q",
                                "filed": "2020-04-29",
                            },
                        ]
                    }
                }
            }
        }
    }
    pairs = _extract(facts=facts, accn=ge_accn)
    revenue = next(c for c, _ in pairs if c.canonical_metric_key == "revenue.total")
    assert revenue.value == Decimal("20524000000")


def test_duplicate_canonical_key_across_two_tags_keeps_only_first():
    """A company could plausibly report under both a legacy and current revenue tag for the same
    filing. TAG_TO_CANONICAL_KEY lists RevenueFromContractWithCustomerExcludingAssessedTax before
    Revenues, so that one should win, not produce two revenue.total claims."""
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2020-06-29",
                                "end": "2020-09-27",
                                "val": 100,
                                "accn": ACCN,
                                "form": "10-Q",
                                "filed": "2020-10-29",
                            },
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2020-06-29",
                                "end": "2020-09-27",
                                "val": 999,
                                "accn": ACCN,
                                "form": "10-Q",
                                "filed": "2020-10-29",
                            },
                        ]
                    }
                },
            }
        }
    }
    pairs = _extract(facts=facts)
    revenue_claims = [c for c, _ in pairs if c.canonical_metric_key == "revenue.total"]
    assert len(revenue_claims) == 1
    assert revenue_claims[0].value == Decimal("100")
