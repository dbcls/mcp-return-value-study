#!/usr/bin/env python3
"""
Phase 0c: apply the FROZEN exclusion set to the inventory windows and emit
post-exclusion item counts and item lists. Input is the inventory CSV already
in hand -- NO re-fetch.

DESIGN (all decided before this code, in the analyst dialogue):

  * B1 payload. The agent sees the raw 100-row window (pinned query, unchanged).
    Only the SCORED items are drawn from non-flagged rows. This code selects
    the scored items; it does not alter the payload. Same construction as the
    pilot (CHEMBL4072), faithful to what the server really returns, no re-fetch.

  * LIMIT 100, fixed for every target and both conditions. Never moved between
    conditions (a moved window is the silent-mismatch failure of section 4).

  * Exclusion set = {dataValidityIssue=true, potentialDuplicate=true}. Decided
    per candidate by ONE test -- does it confound the measurement of unit
    handling -- not by "is it a quality flag":
      - relation (> vs =):      NOT excluded. Orthogonal to unit conversion;
                                reading uM as nM is the same judgement whether
                                the value is ">10" or "=10". Off-target.
      - activityComment:        NOT excluded. All texts are numeric internal
                                reference ids; no "Not Active"-type text exists.
      - dataValidityIssue=true: EXCLUDED. Pathological values (91,830 uM etc.)
                                mislead the agent BEFORE any unit step, so the
                                failure cannot be attributed to unit handling.
      - potentialDuplicate=true:EXCLUDED. Item-independence: a near-duplicate
                                row lets the agent recover the answer from a
                                neighbour even with units stripped.

  * The per-stratum cap (was 14) is RE-DERIVED, not assumed. This code REPORTS
    each target's post-exclusion treatment/control counts and the stratum
    minimum. It does NOT cut to the cap -- that is an open decision. Selecting
    scored items reads NO correctness, so this is not "changing the design after
    seeing results".

EXCLUSION ORDER (fixed; order matters, so it is reported per stage):
  1. source flags: drop rows with validityIssue=true OR potentialDuplicate=true
  2. value-ambiguity: drop any chemblId that appears with >1 distinct value
     (mirrors the existing rule: "the IC50 of X" has no unique answer)
  3. id-dedup: keep first occurrence of each chemblId, in payload order

Usage:
    python3 apply_exclusions.py --invdir inv_csv/ --out post_exclusion.json
    # writes, per target, expected_window.csv (chemblId,value,units) so the
    # main run can assert the payload matches the table items were drawn from.
"""

import argparse
import csv
import io
import json
import os
import re
from collections import Counter, OrderedDict

EXPECTED_COLS = ("chemblId", "value", "units", "relation",
                 "validIssue", "validComment", "dup", "comment")


def truthy(s):
    return s.strip().lower() in ("true", "1", "1.0", "t")


def parse(text):
    rows = [r for r in csv.reader(io.StringIO(text)) if r and any(c.strip() for c in r)]
    if not rows:
        return None, []
    return rows[0], rows[1:]


def process(target, text):
    header, rows = parse(text)
    rec = OrderedDict(target=target, n_rows_raw=len(rows))
    if header is None:
        rec["error"] = "empty"
        return rec, None

    cols = [c.strip().lstrip("?") for c in header]
    idx = {c: (cols.index(c) if c in cols else None) for c in EXPECTED_COLS}
    miss = [c for c in ("chemblId", "value", "units") if idx[c] is None]
    if miss:
        rec["error"] = f"missing required columns {miss}; header {header!r}"
        return rec, None

    def g(r, c):
        i = idx[c]
        return r[i].strip() if i is not None and i < len(r) else ""

    # Preserve payload order throughout. Each row keeps its window position.
    window = [(g(r, "chemblId"), g(r, "value"), g(r, "units"),
               g(r, "validIssue"), g(r, "dup")) for r in rows]

    # The expected payload window (what the agent will see): id,value,units in
    # payload order. Written out for the main run to assert against.
    expected_window = [(cid, val, un) for (cid, val, un, _, _) in window]

    # --- stage 1: source flags -----------------------------------------
    after1, dropped_flag = [], []
    for cid, val, un, vi, dup in window:
        if (vi and truthy(vi)) or (dup and truthy(dup)):
            dropped_flag.append((cid, val, un,
                                 "validity" if vi and truthy(vi) else "",
                                 "dup" if dup and truthy(dup) else ""))
            continue
        after1.append((cid, val, un))
    rec["stage1_dropped_flag"] = len(dropped_flag)

    # --- stage 2: value ambiguity (same id, >1 distinct value) ----------
    vals_by_id = {}
    for cid, val, un in after1:
        vals_by_id.setdefault(cid, set()).add(val)
    ambiguous = {k for k, v in vals_by_id.items() if len(v) > 1}
    after2 = [(cid, val, un) for (cid, val, un) in after1 if cid not in ambiguous]
    rec["stage2_dropped_ambiguous_ids"] = len(ambiguous)

    # --- stage 3: id dedup, keep first in payload order -----------------
    seen, after3 = set(), []
    for cid, val, un in after2:
        if cid in seen:
            continue
        seen.add(cid)
        after3.append((cid, val, un))
    rec["stage3_dropped_dup_ids"] = len(after2) - len(after3)

    # --- eligible items by unit, in payload order -----------------------
    uM = [(cid, val) for (cid, val, un) in after3 if un == "uM"]
    nM = [(cid, val) for (cid, val, un) in after3 if un == "nM"]
    rec["n_rows_after_exclusion"] = len(after3)
    rec["eligible_uM"] = len(uM)
    rec["eligible_nM"] = len(nM)
    rec["treatment_n"] = len(uM)          # ALL eligible uM (cap not yet applied)
    rec["control_n_available"] = len(nM)
    rec["usable"] = len(uM) >= 1
    if not rec["usable"]:
        rec["excluded_reason"] = "0 eligible uM after exclusion; manipulation undefined"
    # full lists in payload order; capping is a downstream, still-open decision
    rec["items_uM"] = uM
    rec["items_nM"] = nM
    return rec, expected_window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--invdir", required=True, help="dir of inventory <TARGET>.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--windowdir", default="expected_windows",
                    help="where to write per-target expected_window CSVs")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.invdir) if f.endswith(".csv"))
    if not files:
        raise SystemExit(f"no .csv in {args.invdir}")
    os.makedirs(args.windowdir, exist_ok=True)

    recs = []
    for f in files:
        target = re.sub(r"\.csv$", "", f)
        text = open(os.path.join(args.invdir, f), encoding="utf-8").read()
        rec, expected = process(target, text)
        recs.append(rec)
        if expected is not None:
            wp = os.path.join(args.windowdir, f"{target}.csv")
            with open(wp, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["chemblId", "value", "units"])
                w.writerows(expected)

    usable = [r for r in recs if r.get("usable")]

    print(f"{'target':<15} {'raw':>4} {'flag':>4} {'amb':>4} {'dupID':>5} "
          f"{'post':>4} {'uM':>4} {'nM':>4}")
    for r in recs:
        if "error" in r:
            print(f"{r['target']:<15} ERROR {r['error']}")
            continue
        print(f"{r['target']:<15} {r['n_rows_raw']:>4} "
              f"{r['stage1_dropped_flag']:>4} {r['stage2_dropped_ambiguous_ids']:>4} "
              f"{r['stage3_dropped_dup_ids']:>5} {r['n_rows_after_exclusion']:>4} "
              f"{r['eligible_uM']:>4} {r['eligible_nM']:>4}"
              + ("" if r["usable"] else "   <- DROPPED (uM=0)"))

    if usable:
        treat_counts = {r["target"]: r["treatment_n"] for r in usable}
        stratum_min = min(treat_counts.values())
        print(f"\nusable targets: {len(usable)}/{len(recs)}")
        print(f"post-exclusion treatment per target: {treat_counts}")
        print(f"stratum minimum (cap candidate if re-deriving): {stratum_min}")
        print(f"control available per target: "
              f"{ {r['target']: r['control_n_available'] for r in usable} }")
        print("\nCap NOT applied. Re-derive to stratum-min or hold at 14 is the "
              "open decision. items_uM / items_nM are full, in payload order.")
        print("expected_window CSVs written -- the main run must assert its "
              "units_on payload (chemblId,value,units) matches these row-for-row.")

    if args.out:
        summary = OrderedDict(
            exclusion_set=["dataValidityIssue=true", "potentialDuplicate=true"],
            not_excluded=["relation!=", "activityComment"],
            payload_mode="B1 (raw window shown, only scored items filtered)",
            limit=100,
            per_target=recs,
        )
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
