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
