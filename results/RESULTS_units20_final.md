# Units experiment — 20-target result (final, ordered window, scoring bugs fixed)

Fully adjudicated: all 1,237 items scored, 0 unjudged. Deterministic window
(`ORDER BY ?activity`), gate-1/2/3 all green, numeric scoring with bugs A (Greek
mu) and B (secondary-value / equivalence capture) fixed, and the 5 residual
low-confidence answers resolved by human review.

## Primary — treatment (uM), manipulation units_on vs units_off

| | value |
|---|---|
| treatment items (uM) | 929 across 20 targets |
| units_on correct | 929 / 929 (1.000) |
| units_off correct | 579 / 929 (0.623) |
| discordant B (on-correct, off-wrong) | 350 |
| discordant C (off-correct, on-wrong) | 0 |
| both correct / neither | 579 / 0 |
| stratified McNemar → CMH (1 df, two-sided) | χ² = 350, p ≈ 4.2×10⁻⁷⁸ |
| exact sign test (C = 0) | 2·0.5³⁵⁰ ≈ 8.7×10⁻¹⁰⁶ |
| per-target | all 20 targets: b > 0 and c = 0 |

The effect is present, monotone (no reversal), and unanimous across all 20
independent targets — the multi-target extension's goal (the effect is not one
table's quirk) is met.

## Control (nM) and specificity

| | value |
|---|---|
| control items (nM) | 308 |
| units_off correct | 307 / 308 (0.997) |
| specificity: uM off-fail vs nM off-fail | 350/929 (0.377) vs 1/308 (0.003) |
| between-molecule (Yates χ²) | χ² = 157, p ≈ 5.3×10⁻³⁶, OR = 186 |

The directional prediction holds strongly: stripping units harms uM rows and
essentially not nM rows. Control is not perfectly immune (1 genuine failure),
so state it as the asymmetry 37.7% vs 0.3%, not "nM never fails".

## Provenance / integrity notes for §9

- **Deterministic window.** `ORDER BY ?activity` (activity URI is unique per
  row — verified n = COUNT(DISTINCT ?activity) for all 20 targets), so the
  item-selection window, the agent's run, and the gate-2 capture all return the
  identical 100 rows. Fixed the LIMIT-100 non-reproducibility found in the
  un-ordered run.
- **Item weighting.** cap removed (path A); large targets contribute more items
  to B. But every target independently shows b > 0 / c = 0, so the effect is not
  a large-target artifact — it is unanimous.
- **Control composition.** ordering changed which rows fall in the window:
  6 targets now have 0 controls (was 3); 8 targets have ≥8 controls for
  specificity. usable 20/20 (every target keeps ≥1 uM).
- **Scoring integrity.** two extractor bugs were found by reading the bytes of
  the 11 apparent control failures: (A) Greek mu μ (U+03BC) absent from the unit
  regex made "30 μM" parse as bare 30; (B) the "last unit-bearing number" rule
  grabbed a secondary measurement or a µM equivalence. Both fixed; verdict is
  now by which hypothesis the answer's numbers support, with the committed value
  taken from the final concentration sentence and genuine non-commitment routed
  to human review. After the fix, apparent control failures fell 11 → 1
  (≈10 were scoring artifacts), and 5 items were adjudicated by hand
  (4 misread, 1 abstain).

## Files

- `perrun_ordered_v4.csv` — per-run audit (arm, numeric_verdict, extracted_nM,
  answer_nM, trap_nM, answer_tail).
- `review_worklist.csv` — the 5 human-reviewed items (resolved: 4 misread,
  1 abstain).
- `post_exclusion20_ordered.json`, `expected_windows_ordered/`,
  `tasks_units20_ordered/` — the frozen ordered artifacts.
- `activity_uniqueness.tsv` — n == COUNT(DISTINCT ?activity) per target.
