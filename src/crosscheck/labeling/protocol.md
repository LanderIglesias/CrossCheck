# Gold-set labeling protocol

Written as if handing this off to a second labeler, even though Phase 0 is labeled solo — a
written protocol is what makes the gold set defensible later (Phase 5 validates the LLM judge
against these labels and reports agreement).

## What you're labeling

A **candidate pair**: two claims about the same `canonical_metric_key` and `period`, sourced from
different documents (e.g. one from the call transcript, one from the deck, one from XBRL). For
each pair, assign exactly one verdict:

- **`consistent`** — the two claims describe the same fact within reasonable tolerance. Rounding
  differences that don't change the substance (e.g. "$1.2 billion" spoken vs. "$1,203M" on a
  slide) are `consistent`. Note the tolerance you used in the rationale.
- **`discrepant`** — the two claims conflict in a way a reader would care about: different
  numbers for the same metric/period, a metric definition that silently changed (e.g. "adjusted
  EBITDA" excludes a different set of items between the call and the 10-Q footnote), or a
  qualifier dropped/added that changes the meaning.
- **`unsupported`** — claim A asserts something with no counterpart anywhere else to compare
  against (only mentioned once, in only one modality). Use `claim_b_id = NULL`.
- **`ambiguous`** — you genuinely cannot tell from the source text whether it's the same fact
  (e.g. vague phrasing, unclear period boundary, unclear whether a segment total includes or
  excludes an item). Don't force a verdict here — `ambiguous` is a legitimate, useful label, not
  a cop-out. The system in later phases is explicitly designed to abstain rather than guess.

## Required for every row

A one-sentence `rationale`, even for `consistent` verdicts ("both state $1.2B total revenue,
deck rounds to nearest million"). This is not busywork — it's what lets you (or anyone) audit the
gold set later, and it's the basis for validating the automated LLM-as-judge in Phase 5.

## Tolerance rules (apply consistently across all 150 items)

- Rounding: values within 0.5% of each other, where the difference is plausibly explained by
  rounding precision, are `consistent`. Anything larger, or explained by a different underlying
  number, is `discrepant`.
- Units: always convert to a common unit before comparing (e.g. bps vs. percent) — a unit
  conversion is not itself evidence of a discrepancy.
- Qualifiers: a claim with a qualifier (`adjusted`, `non-GAAP`, `constant currency`) is only
  comparable to another claim with the *same* qualifier. Comparing GAAP EBITDA to adjusted EBITDA
  and calling it `discrepant` is a labeling error — they're not the same metric; if the deck
  cites only one, the filing's other-context number is `unsupported`, not `discrepant`.
- Speaker attribution: an analyst's premise stated during Q&A ("you said revenue would be
  around a billion...") is not a company claim — do not treat it as a claim source at all.

## Target distribution

150 items across the 5 companies × 4 quarters. Don't force an even split, but ensure all four
verdicts are represented with at least ~15 examples each, and deliberately seek out at least a
few real `discrepant` examples found during data scouting (e.g. a segment number that was
restated between the original filing and next quarter's comparative figures) rather than relying
only on naturally-occurring ones in a single quarter's documents.

## Real restatement cases (Phase 10): cause taxonomy and gold

Pairs of "original vs restated" XBRL values (the same fact published with a different value by two
SEC filings) are labeled by **cause**, and the cause decides the gold verdict:

| `cause` | Meaning | Gold |
|---|---|---|
| `restatement` | The company restated or reclassified the figure (correction or presentation change) | `discrepant` |
| `recast_discontinued_ops` | Prior periods recast because a business moved to discontinued operations | `discrepant` |
| `stock_split` | Per-share data restated for a split; the pair differs by a base change | `ambiguous` |
| `error` | The change comes from an error in one of the filings | `discrepant` |

- `stock_split` -> `ambiguous`: the two figures are not comparable without adjusting for the split,
  so a checker that marks them `discrepant` fails the case. If a split pair also carries a small
  restatement, it stays `stock_split` (decision of the user); say so in the root cause `notes`.
- A cause enters the evaluation only with a **literal quote** from the restating filing, copied
  from the text `extract_text` produces from that filing, plus its accession. The quote is
  checked against that text, never paraphrased and never inferred from the numbers alone.
- A cause counts only once the user has reviewed the quote and set `user_reviewed: true` in
  `eval/phase10/restatement_causes.json`. Pairs with no cause, or with an unreviewed one, are
  excluded and counted (`excluded_no_cause`, `excluded_unreviewed`); the cause is never defaulted.
- A pair whose difference is only a change in rounding or number format (e.g. $ millions with one
  decimal vs whole millions) is not a restatement and has no cause: leave it uncovered.
