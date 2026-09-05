#!/usr/bin/env python3
"""
Pre-flight / post-run gate checker for the 20-target units experiment.

The three gates are from HANDOVER_units_extension.md section 5.5. A target is
CLEARED only when all three pass; run targets one at a time and do not proceed
past a red gate -- a broken manipulation here returns fluent prose, not an error
(HANDOVER.md section 4).

  (1) PAYLOAD IDENTITY. For each item, the FIRST run_sparql output_sha1 under
      units_on must DIFFER from units_off. Identical hashes mean the unit column
      was not actually dropped/added -- the manipulation never reached the
      payload and the run measures nothing. (Extra hashes further down a
      trajectory are the agent's own follow-up queries and are fine; we compare
      the pinned query only, which is the first run_sparql call.)

  (3) ITEM COUNT / IDENTITY. The task ids actually scored for a target must be
      exactly the ids post_exclusion20.json defines for it (t_u20_<T>_<CID> for
      each items_uM row, c_u20_<T>_<CID> for each items_nM row), under BOTH
      conditions. Catches a truncated run or a stale task file.

  (2) WINDOW MATCH is only partially checkable here. runs.jsonl stores
      output_sha1 / output_len, NOT the payload bytes, so "units_on payload ==
      expected_window row-for-row" cannot be reconstructed from a run alone. It
      must be asserted against a SEPARATELY CAPTURED units_on payload (the pinned
      query is deterministic). If --payload-dir holds <T>.units_on.csv this tool
      diffs it against expected_windows/<T>.csv; otherwise gate 2 is reported
      SKIPPED with instructions, never silently passed.

Target is taken from the task id (t_u20_<TARGET>_<CID>), so a single combined
runs.jsonl or one-file-per-target both work.

Usage:
  python3 check_run_gates.py --runs units20.$M.jsonl \
      --post-exclusion post_exclusion20.json \
      [--expected-windows expected_windows/] [--payload-dir captured/] \
      [--only CHEMBL3112376]
Exit 0 iff every checked target clears every checkable gate.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

COND = ("units_on", "units_off")


def target_of(task_id: str) -> Optional[str]:
    # t_u20_<TARGET>_<CID> or c_u20_<TARGET>_<CID>
    parts = task_id.split("_")
    if len(parts) >= 4 and parts[1] == "u20" and parts[0] in ("t", "c"):
        return parts[2]
    return None


def first_sparql_sha1(rec: dict) -> Optional[str]:
    for c in rec.get("tool_calls") or []:
        if c.get("name") == "run_sparql":
            return c.get("output_sha1")
    return None


def expected_ids(post: dict) -> Dict[str, set]:
    """target -> set of task ids the run must contain (per condition)."""
    out: Dict[str, set] = {}
    for tb in post["per_target"]:
        t = tb["target"]
        ids = {f"t_u20_{t}_{cid}" for cid, _ in tb["items_uM"]}
        ids |= {f"c_u20_{t}_{cid}" for cid, _ in tb["items_nM"]}
        out[t] = ids
    return out


def load_runs(path: str) -> List[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def read_window_csv(path: Path):
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    body = [r for r in rows if r and any(c.strip() for c in r)]
    # tolerate an optional header row (chemblId,value,units)
    if body and body[0][:1] and body[0][0].strip().lower() in ("chemblid", "?chemblid"):
        body = body[1:]
    return [tuple(c.strip().strip('"') for c in r[:3]) for r in body]


def gate1(recs_by_cond) -> (bool, str):
    """per-item pinned-query sha1 must differ on vs off."""
    bad = []
    ids = set(recs_by_cond["units_on"]) & set(recs_by_cond["units_off"])
    for tid in sorted(ids):
        on = first_sparql_sha1(recs_by_cond["units_on"][tid])
        off = first_sparql_sha1(recs_by_cond["units_off"][tid])
        if on is None or off is None:
            bad.append(f"{tid}: missing run_sparql sha1 (on={on}, off={off})")
        elif on == off:
            bad.append(f"{tid}: identical sha1 {on} -> manipulation NOT in payload")
    if bad:
        return False, f"{len(bad)} item(s) failed:\n      " + "\n      ".join(bad[:6]) + \
                      ("" if len(bad) <= 6 else f"\n      ...(+{len(bad)-6})")
    return True, f"all {len(ids)} items have distinct on/off pinned sha1"


def gate3(recs_by_cond, exp_ids) -> (bool, str):
    msgs = []
    ok = True
    for cond in COND:
        got = set(recs_by_cond[cond])
        missing = exp_ids - got
        extra = got - exp_ids
        if missing or extra:
            ok = False
            msgs.append(f"{cond}: got {len(got)}/{len(exp_ids)}"
                        + (f", missing {len(missing)}" if missing else "")
                        + (f", extra {len(extra)}" if extra else ""))
        else:
            msgs.append(f"{cond}: {len(got)}/{len(exp_ids)} ids exact")
    return ok, "; ".join(msgs)


def gate2(target, exp_windows: Optional[Path], payload_dir: Optional[Path]) -> (Optional[bool], str):
    if exp_windows is None:
        return None, "SKIPPED: no --expected-windows (regenerate via apply_exclusions.py)"
    ew = exp_windows / f"{target}.csv"
    if not ew.exists():
        return None, f"SKIPPED: expected window {ew} not found"
    if payload_dir is None:
        return None, (f"SKIPPED: expected_window present but no captured payload. "
                      f"Run the pinned units_on query, save {target}.units_on.csv "
                      f"in --payload-dir; row-for-row diff needs the actual bytes "
                      f"(runs.jsonl has none).")
    pj = payload_dir / f"{target}.units_on.csv"
    if not pj.exists():
        return None, f"SKIPPED: captured payload {pj} not found"
    exp = read_window_csv(ew)
    got = read_window_csv(pj)
    if exp == got:
        return True, f"units_on payload matches expected_window row-for-row ({len(exp)} rows)"
    # ordered mismatch: distinguish a benign REORDER (same row multiset) from a
    # real WINDOW DRIFT (different rows -- LIMIT 100 without ORDER BY drew a
    # different subset). Only the latter can move a scored item out of the
    # payload the agent saw.
    from collections import Counter
    ce, cg = Counter(exp), Counter(got)
    if ce == cg:
        return "setonly", (f"set-equal, order differs ({len(exp)} rows) -- benign; "
                           f"becomes row-for-row once the pinned query is ORDER BY'd")
    only_e = sum((ce - cg).values())
    only_g = sum((cg - ce).values())
    n = min(len(exp), len(got))
    where = next((i for i in range(n) if exp[i] != got[i]), n)
    detail = (f"exp_only={only_e} got_only={only_g}; len exp={len(exp)} got={len(got)}; "
              f"first order diff at row {where}")
    if where < n:
        detail += f": exp={exp[where]} got={got[where]}"
    return False, "WINDOW DRIFT -- " + detail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--post-exclusion", default="post_exclusion20.json")
    ap.add_argument("--expected-windows", default=None)
    ap.add_argument("--payload-dir", default=None)
    ap.add_argument("--only", default=None, help="check a single target")
    args = ap.parse_args()

    post = json.load(open(args.post_exclusion, encoding="utf-8"))
    exp_ids = expected_ids(post)
    ew_dir = Path(args.expected_windows) if args.expected_windows else None
    pl_dir = Path(args.payload_dir) if args.payload_dir else None

    recs = load_runs(args.runs)
    by_target = defaultdict(lambda: {c: {} for c in COND})
    unknown = 0
    for r in recs:
        t = target_of(r.get("task_id", ""))
        if t is None:
            unknown += 1
            continue
        cond = r.get("condition")
        if cond in COND:
            by_target[t][cond][r["task_id"]] = r
    if unknown:
        print(f"note: {unknown} run(s) had non-units20 task ids (ignored)", file=sys.stderr)

    targets = [args.only] if args.only else sorted(exp_ids)
    all_ok = True
    cleared = 0
    for t in targets:
        if t not in exp_ids:
            print(f"[{t}] UNKNOWN target (not in post_exclusion20)"); all_ok = False; continue
        rc = by_target.get(t)
        if not rc or not (rc["units_on"] or rc["units_off"]):
            print(f"[{t}] no runs found -- not yet executed"); continue
        g1, m1 = gate1(rc)
        g3, m3 = gate3(rc, exp_ids[t])
        g2, m2 = gate2(t, ew_dir, pl_dir)
        clear = g1 and g3 and (g2 is not False)
        all_ok = all_ok and clear
        cleared += 1 if clear else 0
        tag = "CLEARED" if clear else "BLOCKED"
        g2label = {True: "PASS", "setonly": "PASS*", None: "SKIP", False: "FAIL"}[g2]
        print(f"[{t}] {tag}")
        print(f"   gate1 payload-identity : {'PASS' if g1 else 'FAIL'}  {m1}")
        print(f"   gate2 window-match     : {g2label}  {m2}")
        print(f"   gate3 item-count/ids   : {'PASS' if g3 else 'FAIL'}  {m3}")

    print(f"\nsummary: {cleared} target(s) cleared of {len(targets)} checked; "
          f"{'ALL GREEN' if all_ok else 'ACTION NEEDED'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
