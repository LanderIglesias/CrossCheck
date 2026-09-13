# CrossCheck data model — field-by-field rationale

This describes `db/migrations/0001_init.sql`. Worked examples use placeholder figures until the
data-scouting step picks the actual 5 companies — replace with real numbers once real filings are
loaded (never leave a placeholder in reports/labels, only in this design doc pre-data).

## `companies` / `quarters`

Straightforward dimension tables. `cik` is SEC's Central Index Key (zero-padded to 10 digits,
e.g. `0000320193` for Apple) — required to hit the EDGAR/XBRL APIs. `quarters.call_date` is the
earnings call date, distinct from the filing date (a 10-Q is often filed a few days after the
call).

## `documents`

The provenance root. Every claim traces back to exactly one `document`. `content_hash` (sha256 of
the raw downloaded bytes) is what makes re-running an acquisition script idempotent — if the hash
already exists for a `(quarter_id, modality)` pair, skip the insert. `modality` is one of
`audio | deck | filing | xbrl` — note `filing` (the 10-Q/10-K narrative text) and `xbrl`
(structured facts) are stored as *separate* documents even though they come from the same SEC
submission, because they're extracted completely differently (chunked text vs. typed facts table)
and a claim should point at whichever one it actually came from.

## `claims`

The central table. Key design choices:

- **`canonical_metric_key`** is the join key that lets a claim extracted from the call ("revenue
  was up 12% to about a billion two") be compared against a claim extracted from the deck ("Total
  Revenue: $1,203M") and a claim extracted from XBRL (`us-gaap:Revenues = 1203000000`). Building
  the actual taxonomy (e.g. `revenue.total`, `revenue.segment.<name>`, `margin.gross`,
  `margin.operating.adjusted`, `guidance.revenue.next_quarter`) is deliberately deferred until
  after the data-scouting step picks real companies, so the taxonomy is built against real XBRL
  tag names (`us-gaap:Revenues`, `us-gaap:GrossProfit`, etc.) instead of guessed ones.
- **`value` / `unit` / `qualifier`** are kept separate rather than folding qualifier into the
  metric name, because "adjusted EBITDA" vs "EBITDA" vs "EBITDA excluding stock comp" is exactly
  the kind of definitional drift CrossCheck exists to catch — collapsing it into the metric name
  would hide the very discrepancy we want to surface.
- **`speaker`** is nullable and only populated for `audio` claims (from diarization, in Phase 2).
  A claim made by the CFO in prepared remarks carries different weight than a premise embedded in
  an analyst's question during Q&A — this field is what lets later phases distinguish them.
- **`extraction_method`** is `'manual'` for every Phase 0 gold-set row (a human read the source and
  typed the claim in via the labeling app). From Phase 2 onward it holds the model/pipeline name
  (e.g. `'whisper-large-v3-turbo+ner-v1'`), so gold-set rows and model-extracted rows live in the
  same table and can be directly compared.
- **`embedding vector(1024)`** matches bge-m3's output dimension. It's created now (not added via a
  later migration) specifically so Phase 1 doesn't need a schema-breaking change — it stays NULL
  until Phase 1 actually populates it.

## `evidence_spans`

One claim can have one or more evidence spans (usually exactly one in Phase 0, since gold-set
claims are hand-typed from a single source location). `span_json` shape by `span_type`:

- `audio_ts`: `{"start_sec": 412.3, "end_sec": 418.9}`
- `page_bbox`: `{"page": 7, "x0": 0.12, "y0": 0.44, "x1": 0.61, "y1": 0.52}` (normalized 0-1 coords)
- `char_offset`: `{"start": 10422, "end": 10488}` (into the filing's extracted plaintext)
- `xbrl_fact`: `{"tag": "us-gaap:Revenues", "context_ref": "FD2024Q3", "unit_ref": "USD"}`

Deliberately a loose `JSONB` column rather than one column per possible field — the four
modalities have genuinely incompatible evidence shapes, and forcing them into one rigid schema
would mean mostly-NULL columns for three out of four rows.

## `gold_labels`

`claim_a_id` / `claim_b_id`: a labeled pair. `claim_b_id` is nullable specifically for the
`unsupported` verdict, meaning "claim A makes an assertion with no counterpart anywhere else to
compare it against" (e.g. a metric only ever mentioned once, on the call, never in the deck or
filing). `rationale` is required on every row, even `consistent` ones — Phase 0's labeling
protocol (`src/crosscheck/labeling/protocol.md`) requires a one-sentence justification for every
verdict, both to force careful labeling and because the eval harness (Phase 5) will report
inter-rater-style spot checks against these rationales.

## What's NOT in this schema yet (by design)

No `agent_runs`, `retrieval_results`, or `eval_scores` tables — those belong to Phase 1+
(retrieval) and Phase 5 (eval harness), and adding them now would mean designing them without any
real data to validate against.
