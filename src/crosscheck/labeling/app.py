"""Minimal Streamlit UI for hand-labeling the CrossCheck gold set.

Candidate pairs are claims sharing the same canonical_metric_key + period, sourced from
different documents. This app shows both pieces of evidence side by side and writes the human
verdict + rationale into `gold_labels`. No model calls happen here — pure human labeling.
"""

from __future__ import annotations

import streamlit as st

from crosscheck.db import get_connection

st.set_page_config(page_title="CrossCheck Labeling", layout="wide")
st.title("CrossCheck gold-set labeling")


@st.cache_data(ttl=5)
def load_candidate_pairs() -> list[dict]:
    query = """
        SELECT
            a.id AS claim_a_id, a.subject AS a_subject, a.metric AS a_metric,
            a.value AS a_value, a.unit AS a_unit, a.qualifier AS a_qualifier,
            da.modality AS a_modality,
            b.id AS claim_b_id, b.subject AS b_subject, b.metric AS b_metric,
            b.value AS b_value, b.unit AS b_unit, b.qualifier AS b_qualifier,
            db_.modality AS b_modality
        FROM claims a
        JOIN documents da ON da.id = a.document_id
        JOIN claims b ON b.canonical_metric_key = a.canonical_metric_key
            AND b.period = a.period AND b.id > a.id
        JOIN documents db_ ON db_.id = b.document_id
        WHERE NOT EXISTS (
            SELECT 1 FROM gold_labels g
            WHERE g.claim_a_id = a.id AND g.claim_b_id = b.id
        )
        ORDER BY a.id
        LIMIT 50
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query)
        # Type-narrowing, not a security control: description is only None for statements that
        # return no rows (e.g. INSERT), never for the SELECT this function always runs.
        assert cur.description is not None  # nosec B101
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def save_label(claim_a_id: int, claim_b_id: int | None, verdict: str, rationale: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gold_labels (claim_a_id, claim_b_id, verdict, rationale, labeled_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (claim_a_id, claim_b_id, verdict, rationale, "solo-labeler"),
        )


pairs = load_candidate_pairs()
st.caption(f"{len(pairs)} unlabeled candidate pairs loaded (batch of up to 50).")

for pair in pairs:
    with st.container(border=True):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**A · {pair['a_modality']}**")
            st.write(f"{pair['a_subject']} — {pair['a_metric']}")
            st.write(
                f"value: {pair['a_value']} {pair['a_unit'] or ''} ({pair['a_qualifier'] or 'no qualifier'})"
            )
        with col_b:
            st.markdown(f"**B · {pair['b_modality']}**")
            st.write(f"{pair['b_subject']} — {pair['b_metric']}")
            st.write(
                f"value: {pair['b_value']} {pair['b_unit'] or ''} ({pair['b_qualifier'] or 'no qualifier'})"
            )

        verdict = st.radio(
            "Verdict",
            ["consistent", "discrepant", "unsupported", "ambiguous"],
            key=f"verdict_{pair['claim_a_id']}_{pair['claim_b_id']}",
            horizontal=True,
        )
        rationale = st.text_input(
            "Rationale (required)", key=f"rationale_{pair['claim_a_id']}_{pair['claim_b_id']}"
        )
        if st.button("Save", key=f"save_{pair['claim_a_id']}_{pair['claim_b_id']}"):
            if not rationale.strip():
                st.error("Rationale is required.")
            else:
                claim_b = None if verdict == "unsupported" else pair["claim_b_id"]
                save_label(pair["claim_a_id"], claim_b, verdict, rationale)
                st.success("Saved.")
                st.rerun()
