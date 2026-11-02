# CrossCheck

A multimodal disclosure-consistency engine. CrossCheck reconciles the three artifacts a public
company publishes each quarter — the **earnings call** (audio), the **investor deck** (PDF), and
the **SEC filing/XBRL** (structured facts) — into typed, source-linked claims, and flags where
they disagree.

Full project rationale, architecture, and 12-week build plan: see the design notes this repo was
scaffolded from (not checked in here — ask if you need them).

## Dashboard

A published, single-file report of this project's own real, measured results — live claims
table, the two real disagreement cases, and the Phase 0-8 timeline. Regenerated from Postgres via
`scripts/export_dashboard_data.py`, no fabricated data:

**https://landerworks.com/crosscheck/**

## Status: Phase 10 — evaluation of both checkers

Evaluated the rule-based checker and the LLM judge on real hard cases (restatements with a
filing-verified cause, plus blind-labeled pairs) and on injected errors of known size, with judge
stability and cost. Real and injected results are kept apart. See
[Evaluation (Phase 10)](#evaluation-phase-10) below and `eval/phase10/report.md`.

## Status: Phase 9 — dashboard/report published

Built `dashboard/index.html` + `dashboard/data.json`, a self-contained HTML/CSS/JS report over a
live export of the Postgres database (see `scripts/export_dashboard_data.py`). Went through a full
design critique/audit pass (accessibility contrast, mobile responsiveness, WCAG AA) before
publishing — see `.impeccable/critique/` locally for the raw findings (not checked in).

## Status: Phase 8 — multi-company XBRL extraction + consistency checking complete

### Phase 8: broadening to all 5 companies (finally found a real disagreement)

Phases 3-7 all ran as a deliberate PPC-only vertical slice. Every real gold_labels verdict found
across all 5 companies' 49 hand-labeled items had been `consistent` or `unsupported` — never
`discrepant` or `ambiguous`, a gap named back in Phase 0 and never closed. Phase 8 broadened the
one extractor that's fully portable (XBRL) to all 5 companies and reran both checkers (Phase 4
rule-based, Phase 5 LLM) — and that gap is finally closed, honestly, not manufactured.

**A real bug found and fixed before any of this ran**: GE's own XBRL data tags its FY2020-Q1 10-Q
fact `fy=2019, fp="Q3"` instead of `fy=2020, fp="Q1"` — confirmed by reading the raw fact (correct
`start`/`end` dates and accession number, wrong `fy`/`fp` labels). `xbrl.py`'s matching logic
previously trusted `fy`/`fp`, so **GE silently extracted zero claims**. Fixed by matching on the
filing's real accession number instead — strictly more authoritative than SEC's own `fy`/`fp`
metadata, which this specific filing proves can be wrong. Also added the `Revenues` tag (GE/TRV
report top-line revenue under this instead of the ASC606 tag PPC/DHR/ADTN use — confirmed by
grepping their real JSON) plus `EarningsPerShareBasic`, `IncomeLossFromContinuingOperationsPer
DilutedShare`, and `GrossProfit`.

**Measured result** (`scripts/extract_xbrl_claims.py` then `scripts/eval_xbrl_extraction.py`,
all 5 companies): **14/14 matched, 0 mismatched** (11 more are new automated claims with no manual
counterpart to check against — unscored, not guessed). GE now genuinely extracts.

**A second real bug, found by actually running the broadened checkers, not assumed away**: the
rule-based checker's `group_by_metric_and_period` grouped candidate pairs by
`(canonical_metric_key, period)` only. Period strings aren't globally unique across companies
(PPC and ADTN both use `"FY2020-Q3"`) — without company identity in the key, unrelated companies'
claims were grouped and compared as if they described the same fact, producing nonsense
predictions like "PPC's Net Revenue vs. ADTN's Total Sales -> discrepant." Fixed by adding
`subject` to the grouping key, with a regression test locking in the fix.

**With that fixed, both checkers finally produced real, non-fabricated discrepant/ambiguous
predictions** — scored against all 49 gold_labels:

| | rule-based (Phase 4) | LLM judge (Phase 5) |
|---|---|---|
| scored | 46 | 46 |
| correct | 45 | 45 |
| accuracy | 97.8% | 97.8% |
| agreement with each other (104 shared pairs) | 94.2% | |

Both checkers got exactly one real pair wrong — **different pairs, different failure modes**:

1. **Rule-based false positive** (DHR): the CEO said "sales grew 3% to $4.3 billion"; the exact
   XBRL figure is $4,343.1M — 0.99% apart, exceeding the checker's fixed 0.5% tolerance, so it
   predicted `discrepant`. The human labeler correctly judged this `consistent` ("exact value
   $4,343.1M rounds to $4.3B" — a natural spoken approximation). **The LLM judge got this one
   right**, correctly recognizing the rounding. A single fixed numeric tolerance doesn't
   distinguish an exact structured figure from a spoken approximation — a real, structural
   limitation of the rule-based approach, not a bug to patch away.
2. **LLM judge false positive** (GE): `GAAP Continuing EPS` (manual, $0.72) vs.
   `IncomeLossFromContinuingOperationsPerDilutedShare` (automated_xbrl, $0.72) — **identical
   values** — the LLM predicted `discrepant` anyway, apparently thrown by the differently-worded
   metric labels despite matching numbers. **The rule-based checker got this one right** (exact
   match, trivially `consistent`). A concrete, reproducible LLM judgment error, not smoothed over.

Real cost for this run: 82 live API calls, 99,924 input / 8,709 output tokens, **$0.2869**.

Honest limitation: this is still only 2 real disagreement cases out of 46 scored pairs — not
enough to draw broad conclusions about which method is "better," but it's the project's first
real evidence (not a synthetic unit-test fixture) that the two methods fail differently, which is
exactly the argument for building both rather than picking one.

## Status: Phase 7 — automated audio claim extraction (LLM-based) complete

### Phase 7: audio claim extraction (1 company: Pilgrim's Pride / PPC)

The last modality without an automated extractor, and the first genuinely different problem:
spoken figures in a real, imperfect ASR transcript (13% WER, Phase 2) can't be pulled out with
JSON traversal (Phase 3) or word-position clustering (Phase 6) — it takes actual language
understanding. `src/crosscheck/extraction/audio.py` reuses Phase 5's LLM-calling pattern (lazy
client, forced strict-schema tool call, disk cache by prompt hash) for extraction instead of
judging, and adds a genuinely new step: merging the separate ASR (`*.asr.txt`) and diarization
(`*.diar.txt`) outputs by timestamp overlap into one speaker-labeled transcript, so extracted
claims carry a real (if anonymized) speaker attribution — first real use of `AudioTimestampSpan`.

**Measured result** (`scripts/extract_ppc_audio_claims.py` then `scripts/eval_audio_extraction.py`,
comparing against the 3 hand-labeled `manual` audio claims):

| canonical_metric_key | value | unit | match? |
|---|---|---|---|
| revenue.total | 3,080,000,000 | USD | MATCH |
| ebitda.adjusted | 305,000,000 | USD | MATCH |
| eps.diluted.adjusted | 0.66 | USD_per_share | MATCH |

3/3 matched, correctly recovering all three figures from a single sentence containing a real ASR
error ("adjusted **GAP** EPS" instead of "GAAP EPS") — the model wasn't thrown by it. Real cost:
~30.5K input / ~330 output tokens, **$0.064** for the one live call (cached after).

Like Phase 3's unit-string mismatch, this only matched 3/3 after a real fix: the first run
returned EPS with `unit="USD"` instead of the project's established `"USD_per_share"` convention —
the schema left `unit` as a free-form string with no example to anchor it. Fixed by stating the
exact two allowed unit strings in the system prompt, not by normalizing the mismatch away in code
(unlike Phase 3, where normalization was the right fix — here the model can just be told the
convention directly). Fixing it also surfaced a real gap: the disk cache was keyed only on the
transcript text, not the system prompt, so a prompt edit wouldn't have invalidated stale cached
responses — fixed by hashing both together.

Honest limitation: speaker attribution stops at the anonymized diarization label (`SPEAKER_02`),
not the real name ("Fabio Sandri") — every one of PPC's 3 audio gold claims happens to come from
a single sentence by one speaker, so this phase never needed real-name resolution to validate;
mapping diarization labels to actual identities remains unbuilt.

## Status: Phase 6 — automated deck-PDF claim extraction complete

### Phase 6: deck PDF extraction (1 company: Pilgrim's Pride / PPC)

The last modality named in this project's own description without an automated extractor —
`PageBBoxSpan` had never been populated by anything until this phase. Real inspection of PPC's
actual deck (`data/raw/decks/PPC_2020Q3_f918776170ea.pdf`, all 20 pages read directly) found this
is a genuinely different problem from Phase 3's clean JSON traversal: 17 of 20 pages are
chart/image slides with no extractable figures, and even the one real data table (page 15, "Third
Quarter 2020 Financial Review") didn't grid cleanly under `pdfplumber`'s automatic table detector
— row labels wrap across lines inconsistently and narrative bullet text bleeds into detected
cells. `src/crosscheck/extraction/deck.py` instead clusters raw word positions using the value
column's y-coordinates as row anchors, then attaches whichever label words fall in the vertical
band around each anchor — documented in the module as a real, PDF-specific wrinkle, not a general
table parser.

**Measured result** (`scripts/extract_ppc_deck_claims.py` then `scripts/eval_deck_extraction.py`,
comparing the 4 automated claims against the 4 hand-labeled `manual` deck claims covering the same
`canonical_metric_key`):

| canonical_metric_key | value | unit | match? |
|---|---|---|---|
| revenue.total | 3,075,100,000 | USD | MATCH |
| income.net | 33,400,000 | USD | MATCH |
| eps.diluted.gaap | 0.14 | USD_per_share | MATCH |
| ebitda.adjusted | 305,000,000 | USD | MATCH |

4/4 matched — but only after a real bug was caught and fixed: the last row's label-clustering band
was originally unbounded on its open side, so it silently swept in the next visual row's label
text too ("Adjusted EBITDA* Adjusted EBITDA" instead of just "Adjusted EBITDA*"), which failed to
match the row map and dropped the claim entirely. Fixed by capping the boundary bands to a fixed
reach rather than leaving them open — caught by directly inspecting the real extraction output,
not assumed correct from the code alone; a regression test now covers this exact case.

Honest limitation: this extractor is intentionally narrow — one page, 4 rows, hand-picked because
they have an existing gold-labeled counterpart, with page-15-specific pixel-region constants (a
different company's deck layout would need new ones). The other 16 chart-only pages and the 2
reconciliation-table pages (real tables, but for metrics with no PPC gold label to check against)
are out of scope here, not silently ignored.

## Status: Phase 5 — LLM-as-judge consistency checker complete

### Phase 5: LLM-as-judge (1 company: Pilgrim's Pride / PPC)

The first phase to make a real, paid API call — every prior modality (embeddings, reranker, ASR,
diarization) used a local, free model. `src/crosscheck/consistency/llm_judge.py` asks **Claude
Sonnet 5** (user's cost/quality tradeoff choice over Opus 5's default and Haiku 4.5) to judge the
exact same candidate pairs Phase 4's rule-based checker judges, via a forced, strict-schema tool
call (`submit_verdict`) so the response is always valid structured JSON — no free-text parsing.
Responses are cached on disk by prompt hash (mirroring the EDGAR content-hash cache from Phase 0),
so re-running the eval script after the first pass costs nothing — confirmed by literally
re-running it and getting 0 live calls.

**Measured result** (`scripts/eval_llm_judge.py`, run against PPC's real claims):

| | count |
|---|---|
| scored against real PPC gold_labels | 10 |
| correct | 10 |
| accuracy | 100.0% |
| agreement with Phase 4's rule-based checker (18 total pairs) | 18/18 (100.0%) |
| live API calls (first run) | 12 |
| tokens (first run) | 14,835 input / 1,326 output |
| real cost (first run) | $0.0429 |

Honest limitation, stated as plainly as Phase 4's: **perfect agreement is a real number, not proof
the LLM judge is flawless** — like the rule-based checker, it's only being tested on
`consistent`/`unsupported` cases, since that's all the real PPC gold set contains. The interesting
question this setup is built to answer — does the LLM diverge from the deterministic rule on a
genuinely ambiguous or discrepant case? — still has no real example to test it against. That gap
(named in Phase 0, restated in Phase 4) is still open; this phase doesn't close it, it just adds a
second automated method that agrees with the first on the cases that do exist.

12 live calls, not 18, because two of the candidate pairs (the manual XBRL claim and Phase 3's
`automated_xbrl` claim both report the exact same field values for the same tag) produce
byte-identical prompts — the prompt-hash cache naturally deduped them within the same run, an
honest side effect of caching by content rather than by claim ID.

### Phase 4: consistency checking (1 company: Pilgrim's Pride / PPC)

Until this phase, nothing in the codebase actually compared claims across modalities — this is
the first code that does what the project is named for. `src/crosscheck/consistency/checker.py`
mechanically applies the exact tolerance rules a human labeler used
(`src/crosscheck/labeling/protocol.md`): claims sharing a `canonical_metric_key`+`period` are
candidate pairs; values within **0.5% relative difference** are `consistent`, larger is
`discrepant`; a metric with no counterpart anywhere else is `unsupported`; units with no known
conversion abstain as `ambiguous` rather than guessing. Deliberately rule-based, not LLM-based —
`protocol.md` itself frames an LLM-as-judge as a *later* phase to validate against this
deterministic baseline, not a replacement for it.

**Measured result** (`scripts/eval_consistency_checker.py`, run against PPC's real claims — 64
manual + the 3 automated_xbrl ones from Phase 3):

| | count |
|---|---|
| scored against real PPC gold_labels | 10 |
| correct | 10 |
| accuracy | 100.0% |
| unscored (no ground truth to check against) | 8 |

Honest limitation, stated plainly: 100% is a real number, not an inflated one, but it only proves
the checker gets the *easy* cases right — all 10 scored pairs are `consistent`/`unsupported`,
because that's all the real PPC gold set contains (same finding Phase 0 already surfaced: no
`discrepant`/`ambiguous` case exists yet for this company's headline metrics). The checker's
`discrepant` and `ambiguous` code paths are exercised only by the synthetic unit tests
(`tests/test_consistency_checker.py`), not by any real labeled example — that gap won't close
until a genuine restated/discrepant figure is found (Phase 0's docstring already named this as
future work) or deck PDF extraction adds a modality prone to rounding/definition mismatches.

The 8 unscored predictions are new pairs the checker generated that the human never labeled —
mostly involving the Phase 3 `automated_xbrl` claim (e.g. it wasn't compared against the deck
figure in the original hand-labeling pass) and a few manual-manual pairs the labeler simply didn't
get to (confirmed: the 10 real PPC gold_labels don't cover every possible pairwise combination).
Predictions are printed only — never written into the `gold_labels` table itself, to keep
human-verified and automated output from mixing in a table whose name implies "gold."

### Phase 3: automated claim extraction (1 company: Pilgrim's Pride / PPC)

Every claim in the DB up to this point (64 across 5 companies) was hand-typed
(`extraction_method='manual'`). Phase 3 adds the first **automated** extractor
(`src/crosscheck/extraction/xbrl.py`): it pulls typed `Claim` rows straight out of PPC's real,
already-downloaded XBRL companyfacts JSON (no NLP/LLM — pure JSON traversal) for the same
FY2020-Q3 period the hand-labeled gold set covers, and populates `EvidenceSpan`'s `XBRLFactSpan`
variant for the first time (`tag`, `context_ref`, `unit_ref`).

**Measured result** (`scripts/extract_xbrl_claims.py` — renamed and broadened to all 5 companies
in Phase 8, PPC-only at the time — then `scripts/eval_xbrl_extraction.py`, comparing the 3
automated claims against the 3 hand-labeled `manual` XBRL claims covering the same
`canonical_metric_key`):

| canonical_metric_key | value | unit | match? |
|---|---|---|---|
| revenue.total | 3,075,121,000 | USD | MATCH |
| income.net | 33,446,000 | USD | MATCH |
| eps.diluted.gaap | 0.14 | USD_per_share | MATCH |

3/3 matched — but the EPS row only matched after a real fix: the raw XBRL unit key is
`USD/shares`, not the `USD_per_share` string used throughout the hand-labeled gold set. The
extractor now normalizes unit strings to the established convention (`_normalize_unit` in
`xbrl.py`) while keeping the *unnormalized* raw unit key in the `EvidenceSpan` itself — the
evidence should reflect what the source actually said, the `Claim` should be comparable.

The real, non-obvious extraction wrinkle: companyfacts' per-tag time series repeats the identical
`fy`/`fp`/`form` across the quarter's own figure, its 9-month year-to-date figure, and the
prior-year comparative — those three fields alone don't identify the quarterly fact. The
extractor additionally filters by the fact's start/end duration (~80-100 days) to isolate the
actual quarter, confirmed against PPC's real data (`RevenueFromContractWithCustomerExcludingAssessedTax`
has 4 entries sharing fy=2020/fp=Q3/form=10-Q; only one is the quarter itself).

Honest limitation: XBRL's us-gaap taxonomy only covers strict GAAP tags. None of the gold set's
adjusted/non-GAAP keys (`ebitda.adjusted`, `income.net.adjusted`, `eps.diluted.adjusted`,
`cashflow.free`) exist as XBRL facts at all — they're deck/earnings-release-only figures. That's
real evidence for the project's own thesis (no single modality is a complete source of truth), not
a shortfall to paper over. Deck PDF extraction (a different problem — page-layout, not JSON
traversal, needs a new PDF-parsing dependency) and actual cross-modality consistency-checking
logic remain out of scope here, deferred to later phases.

### Phase 2: audio (1 company: Pilgrim's Pride / PPC)

Real VAD (faster-whisper's bundled Silero VAD) on PPC's actual ~56-minute earnings-call audio
detected 33 speech segments / 54.5 min of speech — consistent with the Earnings-21 corpus's own
recorded audio length (3,376.7s) for this file. Real ASR (`faster-whisper`, `small` model, CPU,
int8) transcribed the full call in 5.8 minutes into 699 timestamped segments
(`src/crosscheck/audio/{vad,asr}.py`, `scripts/transcribe_ppc_audio.py`).

**Measured WER** against the Earnings-21 human reference transcript
(`src/crosscheck/audio/reference.py`, `scripts/eval_asr_wer.py`), both normalized (lowercased,
punctuation stripped) before scoring:

| metric | value |
|---|---|
| WER | 0.130 |
| MER | 0.130 |
| WIL | 0.185 |
| substitutions / deletions / insertions / hits | 530 / 574 / 66 / 7862 |

13.0% WER is a plausible, honest number for Whisper `small` (not `large-v3`) on CPU against a
call full of proper nouns and financial jargon — visible directly in the ASR output, e.g. "Fabio
Sondri" for "Fabio Sandri", "Donna Muinoto" for "Dunham Winoto". Not rounded away or hidden.

**Diarization** (`pyannote.audio`'s `speaker-diarization-3.1` pipeline, `src/crosscheck/audio/
diarization.py`) is real and verified: **754 speaker turns, 11 unique speakers detected** on
PPC's full call — an exact match to the Earnings-21 corpus's own `unique_speakers=11` metadata for
this file, not a coincidence papered over (`scripts/transcribe_ppc_audio.py --diarize-only`).
Spot-checked against the reference transcript's known speaker order (operator → Dunham Winoto →
Fabio Sandri): the detected turns show the same pattern — one long single-speaker block for the
operator's ~45s opening, then a speaker change at the handoff to the first named executive.

Getting there surfaced three real, non-obvious problems, fixed and documented rather than hidden:
1. `pyannote.audio` v4's `speaker-diarization-3.1` pipeline pulls in a *third*, undocumented gated
   model internally (`pyannote/speaker-diarization-community-1`, for its PLDA scoring step) beyond
   the two named in its model card — its terms must be accepted too, or loading fails with a
   `GatedRepoError` that doesn't name `speaker-diarization-3.1` at all.
2. Audio decoding goes through `torchcodec`, which needs a "full-shared" FFmpeg build (separate
   `avutil`/`avcodec`/etc. DLLs) on PATH — a normal single-exe FFmpeg install (`ffmpeg -version`
   works fine) is not sufficient and fails with a DLL-load error.
3. Decoding the source MP3 directly hit a real upstream edge case: the container's declared
   duration and the actual decoded sample count disagree slightly (encoder padding), which crashes
   the pipeline's last audio crop near end-of-file. Fixed by transcoding to mono 16kHz WAV (exact
   PCM sample count) before diarizing, not by patching around the symptom.

See `.env.example` for the full `HF_TOKEN` + FFmpeg setup notes.

### Phase 1: text retrieval (1 company: Pilgrim's Pride / PPC)

Real 10-Q filing (289,298 chars of plaintext after paragraph-aware HTML extraction) chunked into
189 paragraph/table-row-boundary-respecting windows, each embedded with `BAAI/bge-m3` (local, CPU,
free) and stored in the new `chunks` table (`db/migrations/0002_chunks.sql`,
`scripts/ingest_and_embed_filing.py`).

A 4-query retrieval eval (`scripts/eval_retrieval.py`) compared dense-only vs. hybrid
(dense+BM25, reciprocal rank fusion) vs. hybrid+reranked (`BAAI/bge-reranker-v2-m3`), with ground
truth found mechanically (which chunk contains the exact known figure from Phase 0's
hand-verified claims — not hand-picked). **Measured results, reported as-is:**

| variant | recall@5 | recall@10 | nDCG@10 |
|---|---|---|---|
| dense only | 1.00 | 1.00 | 0.435 |
| hybrid (dense+BM25) | 0.75 | 0.75 | 0.279 |
| hybrid + reranked | 0.75 | 0.75 | 0.335 |

Honest finding: dense-only *outperformed* hybrid and hybrid+reranked here — the opposite of the
typical RAG-literature expectation. With only 4 queries this is not a statistically meaningful
result either way (see the eval script's docstring) — the likely cause is that BM25 scored these
natural-language questions poorly against terse financial-statement text (little exact lexical
overlap beyond the company name), diluting the otherwise-strong dense ranking when fused. Not
smoothed over or reframed as a success; reported as measured.

### Phase 0: data foundation (all 5 companies)

This phase built:
- the Postgres schema for claims/evidence/provenance (`db/`)
- data acquisition for SEC EDGAR + XBRL, investor decks, and the public Earnings-21 audio+transcript
  corpus (`src/crosscheck/sources/`)
- a real, hand-labeled gold set: 64 claims and 49 verdicts across all 5 companies
  (`scripts/populate_phase0_gold_labels.py`), extracted by directly reading each company's deck,
  10-Q, XBRL, and earnings-call transcript — not synthetic data
- a Streamlit tool + written protocol (`src/crosscheck/labeling/`) for labeling further items by
  hand, following the same rules used to build the initial 49

Honest limitation: every verdict found in this pass is `consistent` (41) or `unsupported` (8,
genuine GAAP-vs-adjusted qualifier mismatches) — no real `discrepant` or `ambiguous` case turned
up in these 5 companies' headline metrics. That's a real finding, not a shortfall to paper over;
see the docstring in `scripts/populate_phase0_gold_labels.py` for detail. A future pass digging
into segment-level or restated figures is more likely to surface genuine discrepancies.

Everything downstream (retrieval, ASR, multi-agent adjudication, eval harness) depends on this
gold set existing first — it now does.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env   # fill in SEC_USER_AGENT with a real contact email
make db-up
make migrate
make seed   # seeds data, downloads all 4 modalities' documents, chunks+embeds PPC's filing
```

`make seed`'s last step downloads `BAAI/bge-m3` (~2.2GB) and, the first time `eval_retrieval.py`
runs, `BAAI/bge-reranker-v2-m3` (~1.1GB) to the local HuggingFace cache — a real one-time cost on
CPU hardware, not hidden here. Re-running `make seed` afterwards reuses the cached models.

`make seed` must be re-run after `make test` — the DB migration test drops and recreates the
schema (that's intentional, it's what proves the migration is idempotent), which wipes the seeded
rows. Re-downloads are cache hits or content-hash dedupes, so re-running `make seed` is cheap
(except the chunk-embedding step, which re-embeds all 189 chunks — ~1 minute on CPU).

## Data scouting — done

5 companies × 1 quarter each (Earnings-21 only has one call per company, not 4 quarters — see
`db/data_scouting.md` for why), each with a real, downloaded-and-verified investor deck, matching
10-Q, and CIK, AND a transcript independently confirmed to actually be that company's earnings
call (one original pick, AXP, turned out to be a *different* company's analyst conference —
caught by actually reading the transcript, not by trusting the corpus's own metadata): **PPC**
(Q3'20), **DHR** (Q1'20), **GE** (Q1'20), **TRV** (Q2'20), **ADTN** (Q3'20). Seeded via
`db/seed_companies.sql`; deck URLs live in `src/crosscheck/sources/decks.py`'s `DECK_MANIFEST`.
Full verification trail (including rejected candidates) in `db/data_scouting.md`.

All 4 modalities' raw artifacts are downloaded and recorded in the `documents` table for all 5
companies (`scripts/populate_phase0_documents.py`): the Earnings-21 audio + human-reference
transcript, the investor deck PDF, the 10-Q filing HTML, and the XBRL companyfacts JSON.

## Retrieval eval (Phase 1)

```bash
python scripts/eval_retrieval.py
```

Re-runs the dense vs. hybrid vs. hybrid+reranked comparison over PPC's 189 chunks and prints the
ablation table shown above. `scripts/ingest_and_embed_filing.py` must have populated `chunks`
first (done by `make seed`).

## Audio: ASR + WER (Phase 2)

```bash
python scripts/transcribe_ppc_audio.py --vad-only      # quick VAD sanity check
python scripts/transcribe_ppc_audio.py                  # full ASR (~6 min on CPU), writes .asr.txt
python scripts/eval_asr_wer.py                           # real WER against the human reference
python scripts/transcribe_ppc_audio.py --diarize-only   # diarization (~15 min on CPU), writes .diar.txt
```

Diarization needs `HF_TOKEN` in `.env` and a "full-shared" FFmpeg build on PATH — see
`.env.example` for both.

## Automated claim extraction (Phase 3, broadened to all 5 companies in Phase 8)

```bash
python scripts/extract_xbrl_claims.py   # inserts automated_xbrl claims + evidence_spans, all 5 cos
python scripts/eval_xbrl_extraction.py   # compares them against the hand-labeled xbrl claims
```

Requires `make seed` to have run first (needs each company's `xbrl` document row and the manual
gold claims already in the DB).

## Automated deck-PDF extraction (Phase 6)

```bash
python scripts/extract_ppc_deck_claims.py   # inserts automated_deck claims + evidence_spans
python scripts/eval_deck_extraction.py       # compares them against the hand-labeled deck claims
```

Requires `make seed` to have run first (needs PPC's `deck` document row and the manual gold claims
already in the DB).

## Consistency checking (Phase 4, broadened to all 5 companies in Phase 8)

```bash
python scripts/eval_consistency_checker.py   # predicts verdicts, scores against all 49 gold_labels
```

Read-only — doesn't write anything to the DB. Requires `make seed` (which also runs
`extract_xbrl_claims.py`) to have populated all companies' claims first.

## LLM-as-judge (Phase 5, broadened to all 5 companies in Phase 8)

```bash
python scripts/eval_llm_judge.py   # real Anthropic API calls on cache miss; free on cache hit
```

Requires `ANTHROPIC_API_KEY` in `.env` (see `.env.example`) — makes real, paid Claude Sonnet 5
calls the first time each candidate pair is judged (~$0.29 across all 5 companies' full pair set),
then reuses `data/raw/llm_cache/` on every subsequent run at no cost. Read-only against the DB.

## Evaluation (Phase 10)

Phases 4 and 5 scored both checkers on the 49 hand-labeled pairs. Phase 10 asks a harder question:
what do the **rule-based checker** (`consistency/checker.py`, deterministic, `TOLERANCE_PCT = 0.5%`)
and the **LLM judge** (`consistency/llm_judge.py`, Claude Sonnet 5) do on real hard cases and on
errors of a known size? Every number below comes from the artifacts in `eval/phase10/` (report,
results, predictions, candidates and causes), the design spec or the project ledger (seed 20261030, `partial: false`, 0 errors in every cell). Identical judge prompts are
deduplicated within each source (same cache key counts once), so the n below are distinct prompts. Source A
(real) and source B (injected) are never combined in one table or one figure. Intervals are 95%
Wilson intervals. The dashboard shows the same results.

Neither checker, the judge prompt nor the judge model was changed for this evaluation. Where they
fail, the failure is reported, not patched (see "What the judge gets wrong").

### Method

**A. Real hard cases.** Same metric, subject and period but different values across filings, none
of them extraction errors.

- *Restatements.* `scripts/eval_phase10_detect_restatements.py` scans EDGAR companyfacts for
  (tag, unit, period) durations ending in 2019-2020, reported in 10-Q/10-K filings, with at least two
  distinct values across accessions. It found 58 candidates (DHR 28, GE 30; PPC, TRV and ADTN 0). The
  exploratory count in the design spec was DHR 39 and GE 30; the DHR gap is unexplained and the
  filters were not tuned to match it. The candidates are frozen in
  `eval/phase10/restatement_candidates.json` because `data/raw/` is gitignored and companyfacts keeps
  growing (frozen 2026-10-30).
- *Cause verified by quote.* A candidate only enters if the later filing states why the value
  changed (exception: `rounding`, whose quote only fixes the unit, not a reason for the change). `eval/phase10/restatement_causes.json` holds 16 root causes (10
  `recast_discontinued_ops`, 2 `stock_split`, 4 `rounding`), each with a literal quote from the filing
  text and the (tag, period, accession) pairs it covers: 63 pairs in total. Quotes were checked as
  substrings of the extracted filing text, and the user reviewed all 16 causes (`user_reviewed:
  true`). This file is what lets the evaluation say *why* two values differ. A checker sees two
  numbers; the filing's own context is what shows whether the difference is an error.
- *Gold.* `recast_discontinued_ops`: `discrepant` (the figure changed, and flagging it is the
  product's job). `rounding` (18 DHR pairs where only presentation rounding differs, relative
  difference at most 0.0566%): `consistent`. `stock_split` (GE's 1-for-8 reverse split changes
  per-share data while no fact changes): not an error and not comparable without adjusting (stored
  as `ambiguous`), so a `discrepant` verdict counts as a false alarm.
- *Blind labeling.* `scripts/eval_phase10_export_blind.py` exports the candidate pairs nobody had
  labeled, without the checkers' predictions, to `eval/phase10/blind_pairs.csv`. The user (Lander)
  labeled 42 pairs following `src/crosscheck/labeling/protocol.md`: all 42 are `consistent` (38
  distinct judge prompts, 4 duplicates dropped).
- *Controls.* 41 real `consistent` pairs from the gold set, unmutated, measure false alarms (39
  distinct judge prompts).

**B. Injected errors.** In-memory copies of the 41 controls with a known error (`Claim` objects;
nothing is written to `claims` or `gold_labels`). Gold is always `discrepant`. Types: value changes
of 0.3%, 0.49%, 0.51%, 1%, 2%, 5% and 10% (0.49% and 0.51% sit either side of the rules' 0.5%
tolerance), a unit change by x1000, and a period shift (previous quarter, or year-to-date). 377
mutations generated, seeded; 351 distinct judge prompts after deduplication.

**Stability.** 30 real and 30 injected pairs judged 5 times each (the cache key includes the
repetition index, so repeats are real calls and the existing cache is untouched).

### Results A: real hard cases

Precision and recall of `discrepant`. 63 restatement pairs plus 38 blind pairs make 101 real pairs.

#### rules (16 root causes)

| Subset | n | Precision | Recall |
|---|---|---|---|
| restatements | 63 | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| blind | 38 | 0.0% [0.0%, 56.2%] | n/a n/a |
| together (real only) | 101 | 56.2% [42.3%, 69.3%] | 100.0% [87.5%, 100.0%] |
| cause: recast_discontinued_ops | 27 | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| cause: rounding | 18 | n/a n/a | n/a n/a |
| cause: stock_split | 18 | 0.0% [0.0%, 17.6%] | n/a n/a |

#### llm (16 root causes)

| Subset | n | Precision | Recall |
|---|---|---|---|
| restatements | 63 | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| blind | 38 | 0.0% [0.0%, 79.3%] | n/a n/a |
| together (real only) | 101 | 58.7% [44.3%, 71.7%] | 100.0% [87.5%, 100.0%] |
| cause: recast_discontinued_ops | 27 | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| cause: rounding | 18 | n/a n/a | n/a n/a |
| cause: stock_split | 18 | 0.0% [0.0%, 17.6%] | n/a n/a |

How to read it:

- **Both checkers behave the same on restatements.** All 27 `recast_discontinued_ops` pairs are
  flagged (the figure really changed) and none of the 18 `rounding` pairs are. Overall precision is
  60.0% for both because of the next point.
- **`stock_split` is a limitation, not correct behaviour.** All 18 pairs are false alarms for both
  checkers: a reverse split changes the per-share figure while the facts stay the same, and neither
  checker knows about splits. Recall is n/a (the subset has no positives), not 100%. The
  human-verified cause is what shows these pairs are not errors.
- **The blind subset only measures false alarms.** It has 38 pairs, all `consistent`, so there are no
  positives and recall is n/a. Precision 0.0% means everything a checker flagged was a false alarm:
  3 of 38 pairs for rules, 1 of 38 for the LLM. It is not "0 of (0+1)" and not a meaningless
  artifact; the wide intervals ([0.0%, 56.2%] and [0.0%, 79.3%]) reflect how few pairs were flagged.

### Results B: injected errors

Recall of `discrepant`, by type and size. Source B only; no real pairs here.

**The rules curve is a step by construction** (tolerance 0.5%): they detect 0% at 0.3% and 0.49%
and 100% from 0.51%. The misses below the tolerance are expected by design, not a finding, and
"100% recall of the deterministic layer" would be wrong without that qualification.

#### rules

| Type | Size | n | Recall | 95% CI |
|---|---|---|---|---|
| period_prev_quarter | n/a | 27 | 100.0% | [87.5%, 100.0%] |
| period_ytd | n/a | 18 | 100.0% | [82.4%, 100.0%] |
| unit_x1000 | n/a | 38 | 100.0% | [90.8%, 100.0%] |
| value | 0.003 | 39 | 0.0% | [0.0%, 9.0%] |
| value | 0.0049 | 38 | 0.0% | [0.0%, 9.2%] |
| value | 0.0051 | 38 | 100.0% | [90.8%, 100.0%] |
| value | 0.01 | 39 | 100.0% | [91.0%, 100.0%] |
| value | 0.02 | 38 | 100.0% | [90.8%, 100.0%] |
| value | 0.05 | 38 | 100.0% | [90.8%, 100.0%] |
| value | 0.10 | 38 | 100.0% | [90.8%, 100.0%] |

#### llm

| Type | Size | n | Recall | 95% CI |
|---|---|---|---|---|
| period_prev_quarter | n/a | 27 | 100.0% | [87.5%, 100.0%] |
| period_ytd | n/a | 18 | 100.0% | [82.4%, 100.0%] |
| unit_x1000 | n/a | 38 | 50.0% | [34.8%, 65.2%] |
| value | 0.003 | 39 | 51.3% | [36.2%, 66.1%] |
| value | 0.0049 | 38 | 65.8% | [49.9%, 78.8%] |
| value | 0.0051 | 38 | 65.8% | [49.9%, 78.8%] |
| value | 0.01 | 39 | 76.9% | [61.7%, 87.4%] |
| value | 0.02 | 38 | 84.2% | [69.6%, 92.6%] |
| value | 0.05 | 38 | 97.4% | [86.5%, 99.5%] |
| value | 0.10 | 38 | 100.0% | [90.8%, 100.0%] |

- **Rules:** 100% on unit x1000 and on both period shifts; the step sits exactly at 0.5%.
- **LLM:** a smooth curve, 100% on period shifts and at 10%. It flags 51.3% of the 0.3% differences
  and 65.8% of the 0.49% ones, stricter than the 0.5% tolerance written in its own prompt.

#### What the judge gets wrong (reported, not patched)

The judge detects only 50.0% of x1000 unit errors (19 of 38). Where it misses, its rationale treats
the slip as a typo: "after converting units they match exactly, and a unit conversion alone is not
evidence of discrepancy". The design spec leaves improving the checkers out of scope, and changing
the prompt would invalidate the live calls already made, so the prompt was not touched. Mitigation
already in the product: the rule-based checker caught 38 of 38 injected unit errors (95% CI [90.8%, 100.0%]), so the two checkers
complement each other.

### False alarms (real `consistent` controls, unmutated)

| Checker | n | `discrepant` rate | 95% CI |
|---|---|---|---|
| rules | 39 | 2.6% | [0.5%, 13.2%] |
| llm | 39 | 2.6% | [0.5%, 13.2%] |

One of 39 for each checker. With n = 39 the interval reaches 13.2%, so this is not evidence that the
false-alarm rate is acceptable for production.

### Judge stability

5 repetitions, 0 errors. The judge does not set `temperature` (`llm_judge.py` uses the API default),
so stability is an empirical result, not a configuration guarantee. Real and injected are reported
separately.

| Source | Pairs | Change rate | Agreement with the mode |
|---|---|---|---|
| real | 30 | 0.0% | 100.0% |
| injected | 30 | 3.3% | 99.3% |

### Cost

The evaluation cost is **2.8933 $**: every judge call the evaluation uses, including those served
from the on-disk cache, at the price paid when they were made (controls 0.1001 $, stability
1.1037 $). Each cache key is counted once. 0.2189 $ of that was paid in Phase 8 (2026-09-11) and
reused from the cache; 2.6744 $ was paid in Phase 10 (pilot 0.0371 $, first run 1.3035 $, second run
1.3338 $; table in `eval/phase10/runs.md`). The 5 $ cap was cumulative across runs and was enforced
by hand: each run got `--cap-usd` = 5 minus what was already spent.

| Source | Cost | Detected | Cost per detected inconsistency |
|---|---|---|---|
| real | 0.3667 $ | 27 | 0.0136 $ |
| injected | 1.3228 $ | 271 | 0.0049 $ |

"Detected" counts the LLM judge's `discrepant` verdicts on gold-`discrepant` pairs of that source;
the two sources are never mixed.

### What the judge says (qualitative, not scored)

Rationales from `eval/phase10/predictions.jsonl`, on real cases:

- Restatement (DHR, Envista split-off): "Same metric, subject, and period but values differ by about
  $660M (over 15%), far beyond rounding tolerance, indicating a genuine conflict in reported
  revenue." The verdict is right, but nothing in the reasoning says the figure was recast.
- Presentation rounding (DHR): "The values ($9,640.5M vs $9,640.0M) differ by less than 0.01%, well
  within rounding tolerance for the same metric and period."
- Reverse split (GE): "Both claims report GAAP diluted EPS for GE FY2019 with no qualifier
  differences, yet the values (-0.62 vs -4.99) differ far beyond rounding tolerance, indicating a
  genuine conflict." A false alarm: the judge does not know about the 1-for-8 split.
- The false alarm on a control: "Wait, both values are identical (0.72) and same metric key, so they
  are actually consistent." The reasoning reaches the right conclusion and the verdict still says
  `discrepant`.

### Limitations

- **Small n, wide intervals.** 16 root causes, 63 restatement pairs (pairs that share a cause are not
  independent), 38 distinct blind pairs, 41 base pairs for injected errors. Most intervals span tens of points.
- **Causes reviewed by one person.** The 16 causes and the 42 blind labels come from a single
  reviewer (the project author); there is no second opinion.
- **SDK retries are not counted.** The Anthropic SDK retries internally and the budget guard does not
  see those retries, so spend may be slightly understated if any was billed.
- **Candidates frozen on one date** (2026-10-30). EDGAR companyfacts keeps growing, so re-running the
  detector later can find more.
- **Fiscal period = calendar period for DHR and GE.** The period labels (FY2019-Q2 and so on) assume
  it, so the detector is not valid for companies with other fiscal calendars.
- **Narrow source A.** DHR gives 28 candidates against 39 in the spec's exploratory count
  (unexplained, filters not tuned), and PPC, TRV and ADTN give none: real hard cases cover only DHR
  and GE.
- **Controls and blind pairs overlap.** 11 of the 39 control prompts are also blind pairs, so the
  judge's false alarm on blind and on controls is the same entry (GE 0.72 vs 0.72); the rules' false
  alarms follow the same pattern (DHR 4.3 B vs 4,343.1 M). The two are different metrics and are never
  added together; the overlap between sources is kept on purpose, only duplicates inside a source were
  removed.
- **The 5 $ cap was controlled by hand**, not by the code: `--cap-usd` limits one run, so the
  cumulative cap relied on passing 5 minus the amount already spent.
- **Stock splits are an open gap.** Neither checker handles them (18 of 18 false alarms).
- **Out of scope, not done:** changes to the checkers, the prompt or the model; split-adjusted
  comparison; a second reviewer for causes and blind labels.

### Reproduce

Run from the repo root. Only `eval_phase10_run.py` can spend money.

```bash
python scripts/eval_phase10_detect_restatements.py       # EDGAR companyfacts cache -> restatement_candidates.json  (already done; overwrites frozen artifacts)
python scripts/eval_phase10_fetch_restating_filings.py [TICKER]   # prints filing passages used to write restatement_causes.json; writes nothing
python scripts/eval_phase10_export_blind.py              # DB claims + gold_labels -> blind_pairs.csv (to label by hand; already done; overwrites blind_pairs.csv, which holds the human labels)
python scripts/eval_phase10_run.py --count               # planned calls and cost, no API calls
python scripts/eval_phase10_run.py --pilot 10            # at most 10 live calls, prints the cost per call
python scripts/eval_phase10_run.py --full --cap-usd 5    # whole plan (cap = 5 minus what was already spent); also --skip-stability, --seed N
```

`eval_phase10_run.py` reads `restatement_candidates.json`, `restatement_causes.json`,
`blind_pairs.csv` (with your labels) and the claims in Postgres (`make seed` first), and writes
`mutations.json`, `predictions.jsonl`, `results.json` and `report.md` in `eval/phase10/`. The judge
cache `data/raw/llm_cache/` is gitignored: a fresh clone makes live calls (needs `ANTHROPIC_API_KEY`),
while with the cache present the report and its costs regenerate at no cost. The committed artifacts
are the results of the runs described above.

## Automated audio claim extraction (Phase 7)

```bash
python scripts/extract_ppc_audio_claims.py   # merges ASR+diarization, extracts via Claude Sonnet 5
python scripts/eval_audio_extraction.py       # compares against the hand-labeled audio claims
```

Requires `ANTHROPIC_API_KEY` in `.env` and both `scripts/transcribe_ppc_audio.py` (plain and
`--diarize-only`) to have already produced PPC's real `.asr.txt`/`.diar.txt` files. ~$0.06 for the
one live call (cached after).

## Labeling

The initial 49-item gold set is seeded by `make seed` (see above). To label additional
claim pairs (e.g. once Phase 1+ starts extracting claims automatically):

```bash
make label
```

Read `src/crosscheck/labeling/protocol.md` before labeling — it defines the four verdict classes
and tolerance rules.

## Development

```bash
make lint
make test
```
