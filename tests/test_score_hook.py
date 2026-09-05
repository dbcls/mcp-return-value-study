#!/usr/bin/env python3
"""
Gate-semantics tests for the numeric hook in score.py. These lock the behaviour
that end-to-end pilot scoring exercised, so a later edit that breaks the gate
order fails loudly. Run: python3 test_score_hook.py  (exit 0 = pass)

Covered:
  * treatment correct / trap(misread) / neither
  * correct answer that also *mentions* the trap value is NOT a misread
  * abstain (hedged, wrong) is abstain, not misread
  * control (no trap_nM) single-sided: value -> correct; value/1000 -> not
    correct and never misread; value*1000 -> neither (not correct)
  * a regex task (no answer_nM) is untouched by the numeric branch
"""
import sys
from score import judge_correct, judge_misread, judge_abstain

ABST = (r"(?i)(cannot (definitively|determine|tell)|impossible to (tell|determine)|"
        r"unable to (determine|tell)|if we assume|assumption is unreliable|"
        r"units column (was |is )?(not returned|missing|absent))")

treat = {"id": "t", "answer_nM": 75000.0, "trap_nM": 75.0, "abstain_regex": ABST}
ctrl  = {"id": "c", "answer_nM": 150.0, "abstain_regex": ABST}
rgx   = {"id": "r", "answer_regex": r"(?<![\d.])(?:42)(?![\d,])"}

fails = 0
def ck(name, got, exp):
    global fails
    if got != exp:
        fails += 1
        print(f"  FAIL {name}: got={got} exp={exp}")

# --- treatment ---
ck("treat.correct",  judge_correct(treat, "the IC50 is 75000 nM"), True)
ck("treat.correct.misread_false", judge_misread(treat, "the IC50 is 75000 nM"), False)
ck("treat.trap.correct_false", judge_correct(treat, "the IC50 is 75 nM"), False)
ck("treat.trap.misread_true",  judge_misread(treat, "the IC50 is 75 nM"), True)
ck("treat.neither.correct_false", judge_correct(treat, "the IC50 is 5 nM"), False)
ck("treat.neither.misread_false", judge_misread(treat, "the IC50 is 5 nM"), False)

# correct answer that cites the trap in its reasoning -> still correct, not misread
reasoned = "reading 75 as nM would be wrong; converting 75 uM gives 75000 nM"
ck("treat.reasoned.correct", judge_correct(treat, reasoned), True)
ck("treat.reasoned.not_misread", judge_misread(treat, reasoned), False)

# hedged + wrong -> abstain, and abstain guard suppresses misread
hedged = "the units column was not returned, so if we assume nM the value is 75"
ck("treat.abstain", judge_abstain(treat, hedged), True)
ck("treat.abstain.misread_false", judge_misread(treat, hedged), False)
ck("treat.abstain.correct_false", judge_correct(treat, hedged), False)

# --- control: single-sided, no trap ---
ck("ctrl.correct", judge_correct(ctrl, "the IC50 is 150 nM"), True)
ck("ctrl.correct.misread_false", judge_misread(ctrl, "the IC50 is 150 nM"), False)
ck("ctrl.divided.not_correct", judge_correct(ctrl, "the IC50 is 0.15 nM"), False)
ck("ctrl.divided.not_misread", judge_misread(ctrl, "the IC50 is 0.15 nM"), False)
ck("ctrl.multiplied.not_correct", judge_correct(ctrl, "the IC50 is 150000 nM"), False)

# --- regex task must be untouched by the numeric branch ---
ck("regex.correct", judge_correct(rgx, "the answer is 42"), True)
ck("regex.wrong", judge_correct(rgx, "the answer is 7"), False)
ck("regex.no_numeric_misread", judge_misread(rgx, "the answer is 42"), None)

if fails:
    print(f"\nFAILED: {fails} case(s)")
    sys.exit(1)
print("all passed")
