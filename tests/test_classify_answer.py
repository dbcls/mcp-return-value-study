#!/usr/bin/env python3
"""
Tests for classify_answer (hypothesis-support scoring with a 'review' escape).
Run: python3 test_classify_answer.py  (exit 0 = pass)

Groups:
  1. SYNTHETIC/ADVERSARIAL: same intent as test_numeric_scoring, re-checked
     through the new verdict path.
  2. REAL BUG-B: control answers where a secondary/hypothetical value made the
     old 'last unit-bearing number' rule grab the wrong number. The committed
     nM value is correct; the distractor lands on the neither side, so the
     verdict is 'correct'. (Greek-mu equivalence cases are covered by bug A.)
  3. REVIEW: an answer that genuinely commits to BOTH the correct and the trap
     value with no resolving marker -> must be 'review', never a silent guess.
"""
import sys
from numeric_scoring import classify_answer

# (text, correct, trap, expected)
CASES = [
    # --- clean ---
    ("The IC50 is 34347 nM.", 34347.1, 34.3471, "correct"),
    ("The value is 34.3471 nM.", 34347.1, 34.3471, "trap"),
    ("That's 34.3471 uM, i.e. the answer.", 34347.1, 34.3471, "correct"),
    ("The IC50 is 5 nM.", 34347.1, 34.3471, "neither"),
    # working-text integer must not flip a clean unit-bearing answer
    ("75 uM would misread as 75; the answer is 75000 nM.", 75000.0, 75.0, "correct"),
    # reasoning that cites the trap then converts correctly
    ("If I read 34.3471 as nM that would be wrong; converting 34.3471 uM gives 34347.1 nM.",
     34347.1, 34.3471, "correct"),
    # trailing identifier / version / percent are bare -> ignored when a unit number exists
    ("The IC50 is 34347 nM (raw value was 34.3471).", 34347.1, 34.3471, "correct"),
    ("IC50 = 34347 nM, matching 95% of assays.", 34347.1, 34.3471, "correct"),
    # Greek-mu equivalence (bug A): both normalise to the same nM -> correct
    ("The IC50 of CHEMBL1275709 is 30000 nM (or 30 μM).", 30000.0, 30.0, "correct"),
    ("The IC50 is 4100 nM (or 4.1 μM).", 4100.0, 4.1, "correct"),

    # --- REAL bug-B (control): committed value correct, distractor is elsewhere ---
    # correct=14, mentions an additional 2200 nM measurement (neither side)
    ("The compound has IC50 14.0 nM (appears twice); one additional measurement "
     "of 2200.0 nM in a different assay context.", 14.0, 0.014, "correct"),
    # correct=1.6, mentions '1.6 uM would also be plausible' (neither side)
    ("IC50 is 1.6 nM; 1.6 uM would also be plausible but the nM value is used.",
     1.6, 0.0016, "correct"),
    # correct=11, mentions a second 3.95 uM = 3950 nM, ends on the committed 11.0
    ("IC50 is 11.0 nM. There is a second measurement of 3.95 uM = 3950 nM, but the "
     "value directly in nM units is 11.0.", 11.0, 0.011, "correct"),

    # --- REVIEW: both hypotheses committed, no resolving marker ---
    ("The IC50 could be 75 nM, or equivalently 75000 nM depending on the unit.",
     75000.0, 75.0, "review"),
]

fails = 0
for i, (t, c, tr, exp) in enumerate(CASES, 1):
    got = classify_answer(t, c, tr)
    if got != exp:
        fails += 1
        print(f"  FAIL #{i}: got={got} exp={exp}\n       :: {t[:80]}")
print(f"classify_answer: {len(CASES)-fails}/{len(CASES)} passed")
if fails:
    sys.exit(1)
print("all passed")
