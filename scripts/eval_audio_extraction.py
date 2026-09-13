"""Phase 7 eval: compare automated_audio claims against the Phase 0 hand-labeled manual audio
claims for the same company/period/canonical_metric_key.

Both sides ultimately reflect the same spoken sentence, so a mismatch here means the LLM
extractor misread the (real, imperfect) ASR transcript -- reported as measured.
"""

from __future__ import annotations

from crosscheck.db import get_connection

TICKER = "PPC"
PERIOD = "FY2020-Q3"


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.canonical_metric_key, c.value, c.unit, c.extraction_method
            FROM claims c
            JOIN documents d ON d.id = c.document_id
            JOIN quarters q ON q.id = d.quarter_id
            JOIN companies co ON co.id = q.company_id
            WHERE co.ticker = %s AND d.modality = 'audio' AND c.period = %s
            ORDER BY c.canonical_metric_key, c.extraction_method
            """,
            (TICKER, PERIOD),
        )
        rows = cur.fetchall()

    by_key: dict[str, dict[str, tuple[object, str]]] = {}
    for canonical_key, value, unit, extraction_method in rows:
        by_key.setdefault(canonical_key, {})[extraction_method] = (value, unit)

    matches = 0
    mismatches = 0
    missing = 0
    for canonical_key, by_method in sorted(by_key.items()):
        manual = by_method.get("manual")
        automated = by_method.get("automated_audio")
        if manual is None or automated is None:
            missing += 1
            print(f"{canonical_key}: MISSING ONE SIDE (manual={manual}, automated={automated})")
            continue
        if manual == automated:
            matches += 1
            print(f"{canonical_key}: MATCH ({manual[0]} {manual[1]})")
        else:
            mismatches += 1
            print(f"{canonical_key}: MISMATCH (manual={manual}, automated={automated})")

    print(f"\n{matches} matched, {mismatches} mismatched, {missing} missing a counterpart.")


if __name__ == "__main__":
    main()
