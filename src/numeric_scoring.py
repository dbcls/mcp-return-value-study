#!/usr/bin/env python3
"""
Numeric scoring for the units arm, to be wired into score.py.

WHY THIS EXISTS. The randomly sampled 20 targets carry real-world measured
values: 606/804 uM values are decimals, 246 become non-integer on nM
conversion, some are in exponential notation (9.45539e-05). The pilot
(CHEMBL4072) had only round values (75.0 -> 75000) so digit-aligned regex
(75,?000) worked there. It does not generalise. This module scores by NUMBER,
not by string.

WHAT THE EXPERIMENT ACTUALLY MEASURES. Correct and trap are ALWAYS exactly
1000x apart:
    correct = uM_value * 1000   (converted to nM)
    trap    = uM_value          (used as if already nM)
So the question is never "how precise" -- it is "did the agent multiply by 1000
or not". Judged in log10 space, the dividing line is the geometric mean of
correct and trap (sqrt(1000) ~= 31.6x from each). That boundary is not a chosen
tolerance; it is the natural midpoint between the two hypotheses. Rounding
(34347.1 -> 34000) barely moves in log space, so it does not flip the verdict.

THE WORKING PROBLEM (why extraction is the hard part). An agent's answer text
contains many numbers: the trap value it warns about, row counts, compound IDs
(CHEMBL159 has digits), intermediate arithmetic. Naively "the numbers in the
text" would pick up the trap value from an agent that REASONED CORRECTLY --
"75 would be wrong, so ... 75000 nM" -- and mark a correct answer as a misread.
score.py already guards this at the verdict level (a correct answer is never a
misread). Here we must not RE-introduce the problem: we score the CONCLUSION
number, and we let the existing judge_correct gate stay in control.

DESIGN of extraction: we do NOT try to parse free prose perfectly. We take the
LAST number in the answer that is expressed in the requested form (a bare
numeric quantity, optionally with 'nM'). Rationale: agents state the conclusion
last ("... therefore the IC50 is 34347 nM"). The last qualifying number is the
answer; earlier numbers are working. This is a heuristic and MUST be validated
on real run text before trust -- see test_numeric_scoring.py. It is not a
theorem.

This module makes NO verdict on its own about misread vs correct ordering; it
provides:
  * extract_conclusion_number(answer) -> float | None
  * classify(x, correct, trap) -> "correct" | "trap" | "neither"
score.py keeps the gating (correct wins over misread over abstain).
"""
from __future__ import annotations

import math
import re
from typing import List, Optional

# A number: optional sign, digits with optional thousands separators and/or
# decimal part, optional exponent. Thousands commas allowed; we strip them.
_NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
# The conclusion form: a number optionally followed by a unit word we expect.
# We DON'T require 'nM' (agents often give a bare number), but if a unit is
# attached we note it. We deliberately do not match numbers glued to letters
# (CHEMBL159) because \b boundaries and the surrounding-context check exclude
# identifier-embedded digits.
_NUM_RE = re.compile(_NUM)
_NUM_WITH_CTX = re.compile(
    # unit words. BOTH micro signs: µ = U+00B5 (MICRO SIGN) and μ = U+03BC
    # (GREEK SMALL LETTER MU); agents emit either, and missing one made
    # "30 μM" parse as a bare 30 (bug A).
    r"(?<![A-Za-z0-9_])(" + _NUM + r")\s*(nM|nanomolar|uM|µM|μM|micromolar|mM|M)?\b",
    re.IGNORECASE,
)


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def extract_conclusion_number(answer: str) -> Optional[float]:
    """The last qualifying numeric quantity in the answer, as a float in nM.

    If the matched number carries an explicit non-nM unit (uM/mM/M), we convert
    it to nM so classification compares like with like. A bare number is taken
    as already the agent's stated nM answer. Numbers embedded in identifiers
    (CHEMBL159) are excluded by the leading (?<![A-Za-z0-9_]) guard.
    """
    if not answer:
        return None
    matches = list(_NUM_WITH_CTX.finditer(answer))
    if not matches:
        return None

    def to_nM(val, unit):
        unit = (unit or "").lower()
        if unit in ("um", "µm", "μm", "micromolar"):  # µm=U+00B5, μm=U+03BC
            return val * 1000.0          # uM -> nM
        if unit in ("mm",):
            return val * 1_000_000.0     # mM -> nM
        if unit == "m":
            return val * 1e9             # M -> nM
        return val                       # 'nm'/'nanomolar'/none: already nM

    # The conclusion in this task is always a concentration, stated WITH a unit
    # ("250,000 nM"). A trailing version string ("ChEMBL 34.0"), activity id,
    # citation ("[ref 12]") or percent ("95%") is a BARE number that may come
    # after the real conclusion. So prefer the LAST unit-bearing number; only if
    # none carries a unit do we fall back to the last bare number. This is what
    # separated the real disagreement (CHEMBL1366: conclusion "250,000 nM",
    # trailing "ChEMBL 34.0" -> old code wrongly took 34.0) from a true misread.
    for m in reversed(matches):
        if m.group(2):                   # carries an explicit unit
            val = _to_float(m.group(1))
            if val is not None:
                return to_nM(val, m.group(2))
    for m in reversed(matches):          # no unit anywhere: last bare number
        val = _to_float(m.group(1))
        if val is not None:
            return to_nM(val, None)
    return None


def classify(x: Optional[float], correct: float, trap: float,
             max_log_gap: float = 0.5) -> str:
    """Is x nearer correct or trap, in log10 space?

    correct and trap are 1000x apart. The boundary is their geometric mean.
    max_log_gap: if x is farther than this (in log10) from the NEARER of the
    two, return 'neither' -- x is not credibly either value (wrong compound,
    botched arithmetic). 0.5 log10 = 3.16x, well inside the 1000x separation,
    so a value that is genuinely 'correct-ish' or 'trap-ish' still lands.
    Non-positive or missing x -> 'neither' (log undefined).
    """
    if x is None or x <= 0 or correct <= 0 or trap <= 0:
        return "neither"
    lx, lc, lt = math.log10(x), math.log10(correct), math.log10(trap)
    dc, dt = abs(lx - lc), abs(lx - lt)
    nearer = min(dc, dt)
    if nearer > max_log_gap:
        return "neither"
    return "correct" if dc <= dt else "trap"


def _unit_to_nM(val: float, unit: Optional[str]) -> float:
    unit = (unit or "").lower()
    if unit in ("um", "µm", "μm", "micromolar"):   # µ=U+00B5, μ=U+03BC
        return val * 1000.0
    if unit in ("mm",):
        return val * 1_000_000.0
    if unit == "m":
        return val * 1e9
    return val                                     # nM / nanomolar / bare


_SENT = re.compile(r"[.\n]+")
# explicit non-commitment in the final answer sentence: the agent offers both
# hypotheses without choosing. These go to human review rather than a guess.
_NONCOMMIT = re.compile(
    r"(?i)(could be|either\b|depending on the unit|it is unclear|"
    r"cannot (?:tell|determine|be determined)|ambiguous|"
    r"both interpretations|equally (?:likely|plausible))"
)


def _candidates(answer: str):
    """(value_in_nM, unit_bearing, end_pos) for every number in the answer."""
    out = []
    for m in _NUM_WITH_CTX.finditer(answer):
        v = _to_float(m.group(1))
        if v is None:
            continue
        out.append((_unit_to_nM(v, m.group(2)), bool(m.group(2)), m.end()))
    return out


def classify_answer(answer: str, correct: float, trap: float,
                    max_log_gap: float = 0.5) -> str:
    """Verdict for one answer: 'correct' | 'trap' | 'neither' | 'review'.

    Instead of guessing WHICH number is the conclusion, we ask which HYPOTHESIS
    the answer's numbers support. Every unit-bearing number is normalised to nM
    (so "30000 nM" and its equivalent "30 uM" agree) and classified as correct-
    side / trap-side / neither. A secondary measurement or a uM re-statement of
    a different value lands on the neither side, so it does not flip a clean
    answer. Bare numbers are used only when no unit-bearing number exists (this
    drops working-text integers like "75 would be wrong").

      correct-side only            -> correct
      trap-side only               -> trap
      neither only / no numbers    -> neither
      BOTH correct- and trap-side  -> genuine ambiguity: try the conclusion
                                      marker; if it isolates one side, take it,
                                      else 'review' (route to a human -- do NOT
                                      guess, per the low-confidence policy).
    """
    if not answer:
        return "neither"
    cands = _candidates(answer)
    if not cands:
        return "neither"
    unit_c = [c for c in cands if c[1]]
    pool = unit_c if unit_c else cands
    sides = [(classify(v, correct, trap, max_log_gap), pos) for v, _ub, pos in pool]
    has_c = any(s == "correct" for s, _ in sides)
    has_t = any(s == "trap" for s, _ in sides)
    if has_c and not has_t:
        return "correct"
    if has_t and not has_c:
        return "trap"
    if not has_c and not has_t:
        return "neither"
    # Conflict: the answer cites BOTH hypotheses. The committed answer is the
    # MAIN asserted value of the last sentence that states a hypothesis-bearing
    # concentration -- i.e. its FIRST correct/trap value ("X nM (or Y nM if uM)"
    # commits to X; the parenthetical is an aside). A hedged answer that flags
    # the missing unit is separately caught as an abstention by score.py's
    # abstain_regex, so it does not need to be forced here.
    for sent in reversed(_SENT.split(answer)):
        cand = _candidates(sent)
        su = [c for c in cand if c[1]] or cand
        first = None
        for v, _ub, _pos in su:
            s = classify(v, correct, trap, max_log_gap)
            if s in ("correct", "trap"):
                first = s
                break
        if first is None:
            continue                  # this sentence states no hypothesis value
        if _NONCOMMIT.search(sent):
            return "review"           # agent explicitly declined to choose
        return first                  # first hypothesis-bearing value = the commitment
    return "review"                   # no committed hypothesis value anywhere


# --- convenience wrappers mirroring score.py's verdict shape ----------------
# These are what score.py will call when a task has numeric fields
# (answer_nM and trap_nM). They return the same Optional[bool] contract as the
# existing judges, so the gating in score.py is unchanged.

def numeric_correct(task, answer) -> Optional[bool]:
    if "answer_nM" not in task or "trap_nM" not in task:
        return None
    x = extract_conclusion_number(answer)
    return classify(x, float(task["answer_nM"]), float(task["trap_nM"])) == "correct"


def numeric_misread(task, answer) -> Optional[bool]:
    if "answer_nM" not in task or "trap_nM" not in task:
        return None
    x = extract_conclusion_number(answer)
    return classify(x, float(task["answer_nM"]), float(task["trap_nM"])) == "trap"
