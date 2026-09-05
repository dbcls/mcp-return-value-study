#!/usr/bin/env python3
"""
Post-run remediation planner for the 20-target units experiment. Reads the run
logs (no re-execution) and produces the exact, minimal worklist to turn every
target green, split into the two independent problems:

  A. gate 1 holes -- items whose pinned run_sparql sha1 is missing under some
     condition. Classified so a transient endpoint outage (re-runnable) is not
     confused with the agent never querying:
        - "sparql_error": a run_sparql call exists but ok=False / no sha1
                           -> ENDPOINT/transport fault, RE-RUN fixes it.
        - "no_run_sparql": the run made no run_sparql call at all
                           -> agent behaviour; re-run may or may not change it;
                              inspect before trusting.
     Emits the set of TARGETS to re-run (whole target, deterministic at temp 0).

  B. gate 2 staging -- copies the captured units_on payloads
     (gate2_csv/<T>.csv) into the name check_run_gates expects
     (<stage>/<T>.units_on.csv), and reports which targets are still missing a
     capture. With --verify it also diffs each capture against
     expected_windows/<T>.csv right now (row-for-row, normalised), so gate 2 can
     be confirmed without waiting for the full checker.

Nothing is re-run here; this only plans and stages. Re-run the listed targets
with headless_runner, then run check_run_gates over everything.

Usage:
  python3 remediate_runs.py --runs 'runs_units20/units20.*.jsonl' \
      --post-exclusion post_exclusion20.json \
      --gate2-csv gate2_csv --stage-to captured --expected-windows expected_windows --verify
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Optional

COND = ("units_on", "units_off")


def target_of(task_id: str) -> Optional[str]:
    p = task_id.split("_")
    return p[2] if len(p) >= 4 and p[1] == "u20" and p[0] in ("t", "c") else None


def pinned_status(rec: dict):
    """(sha1, reason) for the first run_sparql call. reason in
    {ok, sparql_error, no_run_sparql}."""
    calls = rec.get("tool_calls") or []
    sparql = [c for c in calls if c.get("name") == "run_sparql"]
    if not sparql:
        return None, "no_run_sparql"
    first = sparql[0]
    sha = first.get("output_sha1")
    if sha and first.get("ok", True):
        return sha, "ok"
    return None, "sparql_error"


def load(glob_pat):
    recs = []
    for path in glob.glob(glob_pat):
        recs.extend(json.loads(l) for l in open(path, encoding="utf-8") if l.strip())
    return recs


def norm_window(path: Path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    body = [r for r in rows if r and any(c.strip() for c in r)]
    if body and body[0][0].strip().lower() in ("chemblid", "?chemblid"):
        body = body[1:]
    return [tuple(c.strip().strip('"') for c in r[:3]) for r in body]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="glob for run jsonl(s)")
    ap.add_argument("--post-exclusion", default="post_exclusion20.json")
    ap.add_argument("--gate2-csv", default="gate2_csv")
    ap.add_argument("--stage-to", default="captured")
    ap.add_argument("--expected-windows", default="expected_windows")
    ap.add_argument("--verify", action="store_true", help="diff captures vs expected now")
    args = ap.parse_args()

    post = json.load(open(args.post_exclusion, encoding="utf-8"))
    targets = [tb["target"] for tb in post["per_target"]]

    # index runs by (target, task_id, condition)
    recs = load(args.runs)
    idx = defaultdict(dict)  # (target, task_id) -> {cond: rec}
    for r in recs:
        t = target_of(r.get("task_id", ""))
        if t and r.get("condition") in COND:
            idx[(t, r["task_id"])][r["condition"]] = r

    # ---- A. gate 1 holes ----
    rerun_targets = {}   # target -> list of (task_id, cond, reason)
    for (t, tid), byc in idx.items():
        for cond in COND:
            rec = byc.get(cond)
            if rec is None:
                rerun_targets.setdefault(t, []).append((tid, cond, "missing_run"))
                continue
            sha, reason = pinned_status(rec)
            if sha is None:
                rerun_targets.setdefault(t, []).append((tid, cond, reason))

    print("=== A. gate 1 holes (targets to re-run) ===")
    if not rerun_targets:
        print("  none -- every item has a pinned sha1 under both conditions")
    else:
        for t in sorted(rerun_targets):
            items = rerun_targets[t]
            reasons = defaultdict(int)
            for _, _, why in items:
                reasons[why] += 1
            rs = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
            print(f"  {t}: {len(items)} item-condition(s) [{rs}]")
            for tid, cond, why in items:
                print(f"      {tid} [{cond}] -> {why}")
        endpoint = sorted(t for t, its in rerun_targets.items()
                          if any(w == "sparql_error" for _, _, w in its))
        other = sorted(t for t, its in rerun_targets.items()
                       if all(w != "sparql_error" for _, _, w in its))
        if endpoint:
            print("\n  RE-RUN (endpoint/transport faults, deterministic fix): "
                  + " ".join(endpoint))
        if other:
            print("  INSPECT (no_run_sparql / missing -- not a clear transport fault): "
                  + " ".join(other))

    # ---- B. gate 2 staging ----
    print("\n=== B. gate 2 staging ===")
    stage = Path(args.stage_to); stage.mkdir(parents=True, exist_ok=True)
    g2 = Path(args.gate2_csv); ew = Path(args.expected_windows)
    staged, missing_cap, g2_pass, g2_fail = [], [], [], []
    for t in targets:
        src = g2 / f"{t}.csv"
        if not src.exists():
            missing_cap.append(t); continue
        dst = stage / f"{t}.units_on.csv"
        shutil.copyfile(src, dst); staged.append(t)
        if args.verify and (ew / f"{t}.csv").exists():
            got = norm_window(dst); exp = norm_window(ew / f"{t}.csv")
            (g2_pass if got == exp else g2_fail).append(t)
    print(f"  staged {len(staged)} capture(s) into {stage}/ as <T>.units_on.csv")
    if missing_cap:
        print(f"  MISSING capture ({len(missing_cap)}): " + " ".join(missing_cap))
    if args.verify:
        print(f"  gate2 diff now: PASS {len(g2_pass)}"
              + (f" | FAIL {len(g2_fail)}: " + " ".join(g2_fail) if g2_fail else ""))

    print("\n=== next ===")
    if rerun_targets:
        print("  1) re-run the RE-RUN targets above (whole target, overwrite its jsonl)")
    print("  2) cat runs_units20/units20.*.jsonl > runs_units20/all.jsonl")
    print("  3) python3 check_run_gates.py --runs runs_units20/all.jsonl "
          "--expected-windows expected_windows/ --payload-dir captured/ | tee gate_report.txt")


if __name__ == "__main__":
    main()
