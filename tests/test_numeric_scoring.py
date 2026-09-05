#!/usr/bin/env python3
"""
Tests for numeric_scoring.py.  Run: python3 test_numeric_scoring.py  (exit 0 = pass)

Three groups:
  1. SYNTHETIC (no-regression): twelve hand-built cases covering the working
     problem (trap value cited in reasoning but conclusion correct), compound
     IDs with embedded digits, tiny/exponential values, rounding, abstain.
  2. ADVERSARIAL: cases that broke the FIRST "last number" heuristic (trap in a
     trailing parenthetical, "[ref 12]" citation, "95%" percent). With the fixed
     extractor (prefer the last UNIT-BEARING number) they resolve. If someone
     reverts the extractor these fail loudly -- the section-4 lesson as tests.
  3. REAL (pilot CHEMBL4072, from units18_qwen3_6-35b-a3b.jsonl): the two answers
     where regex and numeric scoring disagreed. CHEMBL1366 = correct answer with
     trailing "ChEMBL 34.0" (old extractor wrongly took 34.0). CHEMBL4525964 = a
     genuine misread that regex wrongly passed (matched the correct value in the
     working) and numeric correctly flags as trap.
"""
import sys
from numeric_scoring import extract_conclusion_number, classify

SYNTHETIC = [
    ("The IC50 is 34347 nM.", 34347.1, 34.3471, "correct"),
    ("If I read 34.3471 as nM that would be wrong; converting 34.3471 uM gives 34347.1 nM.",
     34347.1, 34.3471, "correct"),
    ("The value is 34.3471 nM.", 34347.1, 34.3471, "trap"),
    ("Approximately 34000 nM.", 34347.1, 34.3471, "correct"),
    ("That's 34.3471 uM, i.e. the answer.", 34347.1, 34.3471, "correct"),
    ("For CHEMBL159 the IC50 is 3.43579 nM.", 3.43579, 0.00343579, "correct"),
    ("The result is 0.0945539 nM.", 0.0945539, 0.0000945539, "correct"),
    ("The result is 9.45539e-05 nM.", 0.0945539, 0.0000945539, "trap"),
    ("The query returned 100 rows. Of these, the IC50 for the compound is 2276.84 nM.",
     2276.84, 2.27684, "correct"),
    ("The IC50 is 5 nM.", 34347.1, 34.3471, "neither"),
    ("The units are missing, so I cannot determine the value in nM.", 34347.1, 34.3471, "neither"),
    ("75 uM would misread as 75; the answer is 75000 nM.", 75000.0, 75.0, "correct"),
]

ADVERSARIAL = [
    ("The answer is 34347 nM (raw value was 34.3471).", 34347.1, 34.3471, "correct"),
    ("The IC50 is 34347 nM [ref 12].", 34347.1, 34.3471, "correct"),
    ("IC50 = 34347 nM, matching 95% of assays.", 34347.1, 34.3471, "correct"),
    ("The IC50 is 3.43e4 nM.", 34347.1, 34.3471, "correct"),
    ("Between 34000 and 35000 nM.", 34347.1, 34.3471, "correct"),
    ("Reported in 2019, the IC50 is 34347 nM.", 34347.1, 34.3471, "correct"),
]

REAL = [
    ("The IC50 of compound CHEMBL1366 against target CHEMBL4072 is 250,000 nM "
     "(250 uM). The data comes from the ChEMBL RDF database (ChEMBL 34.0), "
     "activity ID CHEMBL_ACT_1450034.",
     250000.0, 250.0, "correct"),
    ("Given the constraints, the answer is: 10000.0 nM. But I should note that "
     "the units column was not returned in the SPARQL results, so this is based "
     "on the assumption that the filter worked correctly.",
     10000000.0, 10000.0, "trap"),
]


def run(name, cases):
    fails = 0
    for i, (text, correct, trap, expected) in enumerate(cases, 1):
        x = extract_conclusion_number(text)
        got = classify(x, correct, trap)
        if got != expected:
            fails += 1
            print(f"  FAIL {name} #{i}: got={got} exp={expected} x={x}\n       :: {text[:80]}")
    print(f"{name}: {len(cases) - fails}/{len(cases)} passed")
    return fails


def main():
    total = run("synthetic", SYNTHETIC) + run("adversarial", ADVERSARIAL) + run("real", REAL)
    if total:
        print(f"\nFAILED: {total} case(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
