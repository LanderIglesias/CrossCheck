"""Phase 8 eval: compare automated_xbrl claims against the Phase 0 hand-labeled manual xbrl claims
for the same company/period/canonical_metric_key, across all 5 companies (broadened from Phase 3's
PPC-only version).

Both sides ultimately read the same source XBRL file, so a mismatch here means the automated
extractor's period-matching logic (or the original hand-label) picked the wrong fact — reported
as measured, not assumed to be a clean match.
"""

from __future__ import annotations

from crosscheck.db import get_connection


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT co.ticker, c.canonical_metric_key, c.period, c.value, c.unit,
                   c.extraction_method
            FROM claims c
            JOIN documents d ON d.id = c.document_id
            JOIN quarters q ON q.id = d.quarter_id
            JOIN companies co ON co.id = q.company_id
            WHERE d.modality = 'xbrl'
            ORDER BY co.ticker, c.canonical_metric_key, c.extraction_method
            """)
        rows = cur.fetchall()

    by_key: dict[tuple[str, str, str], dict[str, tuple[object, str]]] = {}
    for ticker, canonical_key, period, value, unit, extraction_method in rows:
        by_key.setdefault((ticker, canonical_key, period), {})[extraction_method] = (value, unit)

    matches = 0
    mismatches = 0
    missing = 0
    for (ticker, canonical_key, period), by_method in sorted(by_key.items()):
        manual = by_method.get("manual")
        automated = by_method.get("automated_xbrl")
        label = f"{ticker} {canonical_key} ({period})"
        if manual is None or automated is None:
            missing += 1
            print(f"{label}: MISSING ONE SIDE (manual={manual}, automated={automated})")
            continue
        if manual == automated:
            matches += 1
            print(f"{label}: MATCH ({manual[0]} {manual[1]})")
        else:
            mismatches += 1
            print(f"{label}: MISMATCH (manual={manual}, automated={automated})")

    print(f"\n{matches} matched, {mismatches} mismatched, {missing} missing a counterpart.")


if __name__ == "__main__":
    main()
