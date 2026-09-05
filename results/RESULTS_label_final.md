# Label arm — final result (deterministic full window, two models)

Window fixed by ORDER BY ?chemblId (CHEMBL4096 = TP53, 36,494 candidate labelled
molecules). Items = the entire top-200 window: 124 id-only (label == accession,
answer NONE) + 76 named (answer the name). Naturalistic rate is 98.4% id-only
(35,910 / 36,494); the balanced 124:76 is the deterministic top-200, disclosed.

Supersedes the pilot's single, non-reproducible 200-row draw (18 treat + 12
control). The 18+12 subset was underpowered and misleading (Qwen3-30B
implicit->explicit 7/18 -> 10/18, McNemar p=0.45); the full window resolves it.

## Correctness (treatment = id-only, answer NONE; control = named)

| model | condition | treat correct | control correct |
|---|---|---|---|
| Qwen3.6-35B-A3B | implicit | 123/124 | 76/76 |
| Qwen3.6-35B-A3B | explicit | 124/124 | 76/76 |
| Qwen3-30B-A3B   | implicit | 16/124 (0.13) | 76/76 |
| Qwen3-30B-A3B   | explicit | 75/124 (0.60) | 76/76 |

## Tests

- Zero-information annotation, weaker agent (implicit -> explicit):
  16/124 -> 75/124; McNemar exact b=61 gained, c=2 lost, two-sided p ≈ 4.4×10⁻¹⁶.
  The annotation rescues the weaker agent — strongly and significantly.
- Inter-model gap (3.6 correct / 30B wrong, paired, treatment):
  implicit b=107, c=0, p ≈ 1.2×10⁻³² ; explicit b=49, c=0, p ≈ 3.6×10⁻¹⁵.
  The annotation NARROWS the gap (107 -> 49 discordant) but does NOT close it.
- Capable agent resolves the collision unaided: 123/124 implicit, 124/124 explicit.
- Controls: 76/76 for both models in both conditions (name regexes clean; no
  false negatives to audit).
- Annotation cost: +407 tokens (the kind column over 200 rows) = 0.94% of the
  capable agent's run, 0.31% of the weaker agent's.

## What changes vs the pilot / abstract

- "capable agent 18/18 unaided"      -> 123/124 (124/124 with annotation): holds.
- "weaker 6/18 -> 17/18, p=0.001"     -> 16/124 -> 75/124, b=61/c=2, p ≈ 4×10⁻¹⁶
                                         (same direction, far more power).
- "gap no longer detectable explicit" -> FALSE at power: gap narrows (107->49)
                                         but persists, p ≈ 4×10⁻¹⁵. REWRITE.

## Reconciliation with the units arm

Both arms now say the same thing about the weaker agent: explicitness is
decisive but not sufficient. Units: the weaker agent converts µM->nM on 28% of
rows with the unit and 0% without. Label: the weaker agent is right on 60% with
the annotation and 13% without, still short of the capable agent's ~100%.
Explicitness rescues the weak client; it does not turn it into the strong one.
