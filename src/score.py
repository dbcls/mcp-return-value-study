#!/usr/bin/env python3
"""
Score a runs.jsonl produced by headless_runner.py against a task suite.

Scoring is deliberately separate from running: runs are expensive, so we store
raw RunTrace records once and score them as often as we like (re-scoring after
changing criteria needs no re-execution).

Correctness rules (per task, first that is present wins):
  answer_contains : all listed substrings present (case-insensitive) -> correct
  answer_regex    : regex matches final answer                       -> correct
  (neither)       : correctness left as None (unjudged)

Misread rule:
  trap.wrong_if_contains : any listed substring present -> misread=True

Aggregates per condition: correctness rate, misread rate, mean tool calls,
mean retries, mean total tokens, mean latency, and the empty-answer rate.

Usage:
    python score.py --runs runs.jsonl --tasks tasks.example.yaml
    python score.py --runs runs.jsonl --tasks tasks.example.yaml --per-run out.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from numeric_scoring import extract_conclusion_number, classify, classify_answer


def numeric_verdict(task: Dict[str, Any], answer: str) -> Tuple[Optional[str], Optional[float]]:
    """Numeric-path verdict for units-experiment tasks.

    Returns (verdict, extracted_nM) where verdict is one of
    "correct"/"trap"/"neither", or (None, None) when the task is NOT a numeric
    task (no answer_nM) -- in which case the caller falls back to the regex path
    and nothing changes for the label arm.

    * treatment (answer_nM AND trap_nM): the two hypotheses are 1000x apart;
      classify picks the nearer in log10 space (frozen threshold 0.5).
    * control (answer_nM only, trap by design absent): single-sided. Correct iff
      the conclusion is within classify's 0.5-log boundary of the value. We reuse
      classify with a pseudo lower anchor (value/1000) so the SAME validated
      threshold sets the lower edge; the pseudo anchor is never reported as a
      trap -- a "trap"-side result (agent divided instead) maps to "neither",
      because on a control there is no 1000x trap to fall into.

    The extracted number is returned so a human can audit what was parsed.
    """
    if "answer_nM" not in task:
        return None, None
    x = extract_conclusion_number(answer)          # kept for the audit column
    correct = float(task["answer_nM"])
    trap = float(task["trap_nM"]) if "trap_nM" in task else correct / 1000.0
    v = classify_answer(answer, correct, trap)     # correct/trap/neither/review
    if "trap_nM" not in task and v == "trap":
        v = "neither"                              # control: no real trap side
    return v, x


def load_tasks(path: str) -> Dict[str, Dict[str, Any]]:
    if path.endswith((".yaml", ".yml")):
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        tasks = data["tasks"] if isinstance(data, dict) else data
    else:
        tasks = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return {t["id"]: t for t in tasks}


def judge_correct(task: Dict[str, Any], answer: str) -> Optional[bool]:
    """Correct = every required item present AND nothing forbidden present.

    The exclusion clause matters for set-listing tasks: `answer_contains` alone
    treats an over-inclusive answer ("here is everything, including the right
    ones") as correct, which flatters exactly the failure mode under test.
    """
    nv, _ = numeric_verdict(task, answer)
    if nv is not None:                       # numeric task: bypass regex path
        if nv == "review":
            return None                      # low-confidence: leave unjudged
        return nv == "correct"
    a = answer.lower()
    verdict: Optional[bool] = None
    if "answer_contains" in task:
        verdict = all(s.lower() in a for s in task["answer_contains"])
    elif "answer_regex" in task:
        verdict = re.search(task["answer_regex"], answer) is not None
    if verdict is None:
        return None
    if verdict and "answer_excludes_regex" in task:
        if re.search(task["answer_excludes_regex"], answer):
            return False
    if verdict and "answer_excludes" in task:
        if any(s.lower() in a for s in task["answer_excludes"]):
            return False
    return verdict


def judge_abstain(task: Dict[str, Any], answer: str) -> Optional[bool]:
    """Did the agent decline to answer, rather than assert?

    This distinction is the difference between a silent error and a detected
    failure. An agent that says "the units are missing, so I cannot tell which
    values are nM" has not misread anything — it identified the ambiguity and
    withheld a verdict.

    But the pattern must be judged against the CONCLUSION, not against any
    hedging anywhere in the text. One run said "I cannot definitively confirm
    from this query alone", went and found the unit through another tool, and
    closed with the right number. That is a recovery, not an abstention: the
    doubt was a step in the working, not the outcome. So a run whose answer is
    correct never counts as abstaining, whatever misgivings it voiced on the
    way — the same guard judge_misread applies, for the same reason.
    """
    pat = task.get("abstain_regex")
    if not pat:
        return None
    if not re.search(pat, answer):
        return False
    if judge_correct(task, answer) is True:
        return False
    return True


def judge_misread(task: Dict[str, Any], answer: str) -> Optional[bool]:
    """An ASSERTED misread: trap evidence present, answer wrong, and not hedged.

    Two guards keep the trap honest. A run that abstains has not misread — it
    identified the ambiguity and withheld a verdict. And a run whose answer is
    correct has not misread either, whatever else the text mentions: stating
    "of the 200 rows, 25 are named" cites the total, it does not claim 200. A
    trap regex fires on strings, so without this it would punish an agent for
    showing its working.
    """
    nv, _ = numeric_verdict(task, answer)
    if nv is not None:                       # numeric task: bypass regex trap
        if nv == "review":
            return None                      # low-confidence: leave unjudged
        if nv != "trap":
            return False
        if judge_abstain(task, answer):      # same guards, same order
            return False
        if judge_correct(task, answer) is True:
            return False
        return True
    trap = task.get("trap")
    if not trap:
        return None
    if "wrong_if_regex" in trap:
        hit = re.search(trap["wrong_if_regex"], answer) is not None
    elif "wrong_if_contains" in trap:
        a = answer.lower()
        hit = any(s.lower() in a for s in trap["wrong_if_contains"])
    else:
        return None
    if not hit:
        return False
    if judge_abstain(task, answer):
        return False
    if judge_correct(task, answer) is True:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--per-run", default=None, help="optional CSV of per-run judgments")
    ap.add_argument("--by-model", action="store_true",
                    help="group by (model, condition) instead of condition alone. "
                         "Runs from several models can then be scored together: "
                         "pass multiple --runs files.")
    ap.add_argument("--extra-runs", nargs="*", default=[],
                    help="additional runs JSONL files to include")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    per_cond: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
    per_run_rows: List[Dict[str, Any]] = []

    paths = [args.runs] + list(args.extra_runs)
    lines = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            lines.extend(l for l in fh if l.strip())

    for line in lines:
        if True:
            r = json.loads(line)
            task = tasks.get(r["task_id"], {})
            answer = r.get("final_text", "") or ""
            correct = judge_correct(task, answer)
            misread = judge_misread(task, answer)
            abstain = judge_abstain(task, answer)
            cond = r.get("condition", "?")
            if args.by_model:
                cond = f'{r.get("model_label", "?")}/{cond}'
            us = r.get("usage_summary") or {}

            bucket = per_cond[cond]
            if correct is not None:
                bucket["correct"].append(1 if correct else 0)
            if misread is not None:
                bucket["misread"].append(1 if misread else 0)
            if abstain is not None:
                bucket["abstain"].append(1 if abstain else 0)
            bucket["tool_calls"].append(r.get("n_tool_calls", 0))
            bucket["retries"].append(r.get("n_retries", 0))
            bucket["empty"].append(1 if r.get("answer_empty") else 0)
            if r.get("latency_total") is not None:
                bucket["latency"].append(r["latency_total"])
            if us.get("total_tokens_sum") is not None:
                bucket["total_tokens"].append(us["total_tokens_sum"])
            if us.get("finish_length") is not None:
                bucket["finish_length"].append(1 if us["finish_length"] else 0)

            # numeric-path audit fields: what the extractor parsed and the
            # targets it was compared against, so a human can eyeball each
            # verdict against the actual conclusion sentence.
            nverdict, nextracted = numeric_verdict(task, answer)
            arm = None
            if "answer_nM" in task:
                arm = "treat" if "trap_nM" in task else "control"
            tail = " ".join((answer or "").split())[-160:]

            per_run_rows.append({
                "run_id": r["run_id"], "task_id": r["task_id"],
                "model_label": r.get("model_label"), "condition": r.get("condition"),
                "correct": correct, "misread": misread, "abstain": abstain,
                "arm": arm, "numeric_verdict": nverdict,
                "extracted_nM": nextracted,
                "answer_nM": task.get("answer_nM"), "trap_nM": task.get("trap_nM"),
                "n_tool_calls": r.get("n_tool_calls"), "n_retries": r.get("n_retries"),
                "total_tokens": us.get("total_tokens_sum"),
                "latency_total": r.get("latency_total"), "answer_empty": r.get("answer_empty"),
                "answer_tail": tail,
            })

    def rate(xs: List[int]) -> Optional[float]:
        return round(mean(xs), 3) if xs else None
    def avg(xs: List[float]) -> Optional[float]:
        return round(mean(xs), 2) if xs else None

    width = 34 if args.by_model else 12
    print(f"{'condition':<{width}} {'n':>4} {'correct':>8} {'misread':>8} {'abstain':>8} "
          f"{'calls':>6} {'retry':>6} {'tokens':>8} {'lat_s':>7} {'empty':>6} {'fin=len':>8}")
    for cond in sorted(per_cond):
        b = per_cond[cond]
        n = len(b["tool_calls"])
        print(f"{cond:<{width}} {n:>4} "
              f"{str(rate(b['correct'])):>8} {str(rate(b['misread'])):>8} "
              f"{str(rate(b['abstain'])):>8} "
              f"{str(avg(b['tool_calls'])):>6} {str(avg(b['retries'])):>6} "
              f"{str(avg(b['total_tokens'])):>8} {str(avg(b['latency'])):>7} "
              f"{str(rate(b['empty'])):>6} {str(rate(b['finish_length'])):>8}")

    if args.per_run:
        with open(args.per_run, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(per_run_rows[0].keys()))
            w.writeheader()
            w.writerows(per_run_rows)
        print(f"\nper-run CSV written to {args.per_run}", file=sys.stderr)


if __name__ == "__main__":
    main()
