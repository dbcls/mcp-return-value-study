#!/usr/bin/env python3
"""
Phase 0 of the multi-target extension: count what each sampled target affords
inside the LIMIT 100 window, BEFORE committing to a design.

WHY THIS STEP EXISTS. The population predicate (HAVING COUNT(DISTINCT ?units)
> 1) is a TARGET-level statement; the experiment reads a WINDOW (LIMIT 100).
A target can mix nM and uM across all its activities and still return a window
that is entirely nM. This is not hypothetical: the same pinned query on
CHEMBL4072 yields 6 uM rows at LIMIT 30 and 30 at LIMIT 100 -- same target,
same mixture, different window.

WHY COUNT FROM THE TOOL'S CSV, NOT FROM THE ENDPOINT. The experiment sees
whatever run_sparql returns. Counting by a direct endpoint query would count a
different table than the one measured. Read the bytes the apparatus reads.

FROZEN RULES (fixed before any counts were seen; do not adjust after):
  * LIMIT is 100 for every target. Never vary LIMIT per target to equalise the
    uM count: payload length would become a confound.
  * Exclusion: a compound whose ID appears with more than one distinct value in
    the window is dropped -- "the IC50 of X" has no unique answer. (Mirrors
    tasks.chembl_units_items18.yaml: CHEMBL122812, CHEMBL191881, CHEMBL336228.)
  * Treatment = every eligible uM row the window affords. No cap, no floor
    beyond >= 1. Taking all of them removes the arbitrariness of "18".
  * Control = eligible nM rows in payload order, count matched to treatment,
    or all available if fewer.
  * A target with 0 eligible uM rows is EXCLUDED: the manipulation is undefined
    there, not unfavourable. No replacement is drawn. Report how many fell out.
  * The uM:nM ratio is never a selection criterion. It is reported because with
    6 targets it is fully confounded with target identity and CANNOT be
    modelled -- say so in the limitations rather than pretending.

Usage:
    # 1. emit the pinned queries (one per sampled target)
    python3 count_window.py queries --sample sample.json --outdir queries/

    # 2. run each through run_sparql, save the CSV the tool returns verbatim
    #    as <TARGETID>.csv, then:
    python3 count_window.py count --csvdir csv/ --out window_counts.json
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict

QUERY_TMPL = """PREFIX cco: <http://rdf.ebi.ac.uk/terms/chembl#>
SELECT ?chemblId ?value ?units
FROM <http://rdf.ebi.ac.uk/dataset/chembl>
WHERE {{
  ?activity a cco:Activity ;
            cco:hasMolecule ?molecule ;
            cco:hasAssay/cco:hasTarget <http://rdf.ebi.ac.uk/resource/chembl/target/{target}> ;
            cco:standardType "IC50" ;
            cco:value ?value ;
            cco:units ?units .
  ?molecule cco:chemblId ?chemblId .
  FILTER(?units IN ("nM", "uM"))
}}
ORDER BY ?activity
LIMIT 100"""


def cmd_queries(args):
    with open(args.sample, encoding="utf-8") as fh:
        prov = json.load(fh)
    targets = prov["sample"]
    os.makedirs(args.outdir, exist_ok=True)
    for t in targets:
        path = os.path.join(args.outdir, f"{t}.rq")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(QUERY_TMPL.format(target=t) + "\n")
        print(f"wrote {path}")
    print(
        "\n# Run each through run_sparql (database=\"chembl\"), exactly as written,\n"
        "# and save the CSV the TOOL returns -- not the endpoint -- as <TARGET>.csv.\n"
        "#\n"
        "# SANITY CHECK: the 6 payload SHA-1s must all differ. If any two match,\n"
        "# the target URI is not reaching the query and you are counting one table\n"
        "# six times. count_window.py checks this for you.",
        file=sys.stderr,
    )


def parse_csv(text):
    """Parse the tool's CSV. Returns (header, rows). Refuses to guess."""
    rdr = csv.reader(io.StringIO(text))
    rows = [r for r in rdr if r and any(c.strip() for c in r)]
    if not rows:
        return None, []
    return rows[0], rows[1:]


def analyse(target, text):
    sha1 = hashlib.sha1(text.encode("utf-8")).hexdigest()
    header, rows = parse_csv(text)
    rec = OrderedDict(target=target, payload_sha1=sha1, payload_bytes=len(text))

    if header is None:
        rec["error"] = "empty payload"
        return rec

    cols = [c.strip().lstrip("?") for c in header]
    try:
        i_id, i_val, i_un = cols.index("chemblId"), cols.index("value"), cols.index("units")
    except ValueError:
        rec["error"] = f"unexpected header: {header!r}"
        return rec

    rec["n_rows"] = len(rows)
    if len(rows) != 100:
        # Not an error -- the target may simply afford fewer -- but it changes
        # payload length, which is a confound the frozen rules assume constant.
        rec["note_short_window"] = f"{len(rows)} rows, not 100"

    # --- exclusion: an ID with more than one distinct value is ambiguous ---
    vals_by_id = {}
    for r in rows:
        vals_by_id.setdefault(r[i_id].strip(), set()).add(r[i_val].strip())
    ambiguous = {k for k, v in vals_by_id.items() if len(v) > 1}
    rec["excluded_ambiguous_ids"] = sorted(ambiguous)

    unit_counts = Counter(r[i_un].strip() for r in rows)
    rec["rows_by_unit"] = dict(unit_counts)

    # --- eligible items, in payload order, deduplicated by ID ---
    seen = set()
    elig = {"uM": [], "nM": []}
    for r in rows:
        cid, unit = r[i_id].strip(), r[i_un].strip()
        if cid in ambiguous or cid in seen:
            continue
        if unit in elig:
            seen.add(cid)
            elig[unit].append((cid, r[i_val].strip()))

    n_um, n_nm = len(elig["uM"]), len(elig["nM"])
    rec["eligible_uM"] = n_um
    rec["eligible_nM"] = n_nm
    rec["treatment_n"] = n_um
    rec["control_n"] = min(n_um, n_nm)
    rec["usable"] = n_um >= 1
    if not rec["usable"]:
        rec["excluded_reason"] = (
            "0 eligible uM rows in the window: the manipulation is undefined "
            "here (stripping units leaves the naive nM reading correct on every "
            "row). Scope condition, not selection on outcome."
        )
    if n_um and n_nm < n_um:
        rec["note_unbalanced"] = f"control capped at {n_nm} (< treatment {n_um})"
    # Reported, never used to select.
    rec["uM_share_of_window"] = round(unit_counts.get("uM", 0) / max(len(rows), 1), 4)
    rec["items_uM"] = elig["uM"]
    rec["items_nM"] = elig["nM"][: rec["control_n"]]
    return rec


def cmd_count(args):
    files = sorted(f for f in os.listdir(args.csvdir) if f.endswith(".csv"))
    if not files:
        sys.exit(f"no .csv files in {args.csvdir}")

    recs = []
    for f in files:
        target = re.sub(r"\.csv$", "", f)
        with open(os.path.join(args.csvdir, f), encoding="utf-8") as fh:
            recs.append(analyse(target, fh.read()))

    # --- SANITY CHECK: distinct payloads --------------------------------
    shas = Counter(r["payload_sha1"] for r in recs)
    dupes = {s: [r["target"] for r in recs if r["payload_sha1"] == s]
             for s, n in shas.items() if n > 1}
    if dupes:
        print("\n*** STOP. Identical payloads across targets: ***", file=sys.stderr)
        for s, ts in dupes.items():
            print(f"  {s[:12]}  {', '.join(ts)}", file=sys.stderr)
        print("The target URI is not reaching the query. These counts measure "
              "nothing. Fix before proceeding.\n", file=sys.stderr)

    usable = [r for r in recs if r.get("usable")]
    dropped = [r for r in recs if not r.get("usable")]

    summary = OrderedDict(
        targets_counted=len(recs),
        targets_usable=len(usable),
        targets_dropped_uM_zero=[r["target"] for r in dropped],
        total_treatment_items=sum(r["treatment_n"] for r in usable),
        total_control_items=sum(r["control_n"] for r in usable),
        identical_payload_sha1=bool(dupes),
        per_target=recs,
    )

    # --- human-readable table -------------------------------------------
    print(f"{'target':<16} {'rows':>5} {'uM':>4} {'nM':>4} {'excl':>5} "
          f"{'treat':>6} {'ctrl':>5} {'sha1':>10}")
    for r in recs:
        if "error" in r:
            print(f"{r['target']:<16} ERROR: {r['error']}")
            continue
        print(f"{r['target']:<16} {r['n_rows']:>5} "
              f"{r['rows_by_unit'].get('uM', 0):>4} {r['rows_by_unit'].get('nM', 0):>4} "
              f"{len(r['excluded_ambiguous_ids']):>5} "
              f"{r['treatment_n']:>6} {r['control_n']:>5} {r['payload_sha1'][:10]:>10}"
              + ("   <- DROPPED (uM=0)" if not r["usable"] else ""))

    print(f"\nusable targets: {len(usable)}/{len(recs)}; "
          f"treatment items total: {summary['total_treatment_items']}; "
          f"control items total: {summary['total_control_items']}")
    print("\nCost note: units_off uM runs ran ~263K tokens each on CHEMBL4072. "
          "Multiply by the treatment total before committing.")
    print("The uM share is reported per target but is fully confounded with "
          "target identity at n=6 and cannot be modelled. Do not select on it.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\nwritten to {args.out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("queries", help="emit one pinned query per sampled target")
    q.add_argument("--sample", required=True, help="sample.json from sample_targets.py")
    q.add_argument("--outdir", default="queries")
    q.set_defaults(func=cmd_queries)

    c = sub.add_parser("count", help="count uM/nM items from the tool's CSVs")
    c.add_argument("--csvdir", required=True, help="dir of <TARGET>.csv as returned by run_sparql")
    c.add_argument("--out", default=None)
    c.set_defaults(func=cmd_count)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
