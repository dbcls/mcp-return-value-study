# Noticing mediation — 20-target units experiment (uM, units_off)

Whether the agent noticed the withheld unit (spent >1 run_sparql call) mediates
whether it answered correctly. Verdicts include the 5 human-adjudicated review
items (4 misread, 1 abstain). "other" = numeric 'neither'.

| group | n | correct | misread | abstain | other | mean tokens | cost vs units_on |
|---|---|---|---|---|---|---|---|
| noticed (>1 call) | 766 | 566 | 142 | 56 | 2 | 232,473 | 6.6x |
| did not notice (1 call) | 163 | 13 | 140 | 10 | 0 | 34,967 | 1.0x |

- correctness: noticed 566/766 (0.739) vs not-noticed 13/163 (0.080)
- Fisher exact, two-sided: p ≈ 3.9×10⁻⁵⁸
- units_on baseline mean tokens (uM) = 35,273

Same shape as the pilot (noticed 10/12 vs not-noticed 0/6, p = 0.0015),
reproduced at 20-target scale. Noticing is the mediator and it is expensive
(~6.6x tokens), matching the pilot's ~7x.
