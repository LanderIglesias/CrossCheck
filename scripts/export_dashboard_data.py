"""Phase 9: export a real, live snapshot of the DB for the published dashboard (dashboard/index.html).

Read-only. Writes dashboard/data.json. Re-run any time the DB changes to keep the published
dashboard's numbers honest and current, rather than a one-time hand-typed snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

from crosscheck.db import get_connection

OUT_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "data.json"
PHASE10_RESULTS = Path(__file__).resolve().parent.parent / "eval" / "phase10" / "results.json"


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT co.ticker, co.name, q.fiscal_year, q.fiscal_period, count(d.id)
            FROM companies co
            JOIN quarters q ON q.company_id = co.id
            JOIN documents d ON d.quarter_id = q.id
            GROUP BY co.ticker, co.name, q.fiscal_year, q.fiscal_period
            ORDER BY co.ticker
            """)
        companies = [
            {
                "ticker": ticker,
                "name": name,
                "fiscal_year": fy,
                "fiscal_period": fp,
                "documents": docs,
            }
            for ticker, name, fy, fp, docs in cur.fetchall()
        ]

        cur.execute("""
            SELECT co.ticker, c.subject, c.metric, c.canonical_metric_key, c.period,
                   c.value, c.unit, c.qualifier, c.speaker, c.extraction_method, d.modality
            FROM claims c
            JOIN documents d ON d.id = c.document_id
            JOIN quarters q ON q.id = d.quarter_id
            JOIN companies co ON co.id = q.company_id
            ORDER BY co.ticker, c.canonical_metric_key, c.extraction_method
            """)
        claims = [
            {
                "ticker": ticker,
                "subject": subject,
                "metric": metric,
                "canonical_metric_key": key,
                "period": period,
                "value": str(value) if value is not None else None,
                "unit": unit,
                "qualifier": qualifier,
                "speaker": speaker,
                "extraction_method": extraction_method,
                "modality": modality,
            }
            for (
                ticker,
                subject,
                metric,
                key,
                period,
                value,
                unit,
                qualifier,
                speaker,
                extraction_method,
                modality,
            ) in cur.fetchall()
        ]

        cur.execute("SELECT verdict, count(*) FROM gold_labels GROUP BY verdict")
        gold_label_counts = {verdict: count for verdict, count in cur.fetchall()}

        cur.execute("SELECT span_type, count(*) FROM evidence_spans GROUP BY span_type")
        evidence_span_counts = {span_type: count for span_type, count in cur.fetchall()}

        cur.execute("SELECT extraction_method, count(*) FROM claims GROUP BY extraction_method")
        claims_by_method = {method: count for method, count in cur.fetchall()}

    # Phase 10 evaluation: copied as-is (the harness already computed every figure); None if not run yet.
    phase10_eval = (
        json.loads(PHASE10_RESULTS.read_text(encoding="utf-8"))
        if PHASE10_RESULTS.exists()
        else None
    )

    snapshot = {
        "companies": companies,
        "claims": claims,
        "gold_label_counts": gold_label_counts,
        "evidence_span_counts": evidence_span_counts,
        "claims_by_extraction_method": claims_by_method,
        "phase10_eval": phase10_eval,
        "totals": {
            "companies": len(companies),
            "claims": len(claims),
            "gold_labels": sum(gold_label_counts.values()),
            "evidence_spans": sum(evidence_span_counts.values()),
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(claims)} claims, {len(companies)} companies)")


if __name__ == "__main__":
    main()
