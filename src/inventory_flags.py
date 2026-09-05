#!/usr/bin/env python3
"""
Phase 0b: INVENTORY the quality flags present in each target's window, before
deciding what to exclude. One pass, all flags, instead of discovering them one
at a time.

WHY. Two quality flags have already surfaced by reading the RDF source that the
aggregated CSV cannot show:
  * cco:dataValidityIssue = true    (e.g. CHEMBL5705, a 10000 uM "Outside
                                     typical range" measurement)
  * cco:potentialDuplicate = true   (e.g. CHEMBL3646217, the SAME compound at
                                     the SAME 52300 nM across four activities --
                                     invisible to a same-value dedup on the CSV)
There is no guarantee a third does not exist. So we stop picking flags off one
by one and inventory the window instead.

CRITICAL -- SAME WINDOW AS THE EXPERIMENT. Quality flags live on the Activity.
The task file selects items from exactly the 100 rows the pinned query returns.
The inventory MUST look at that same window, or it cleans a different table than
the one measured. So this query is the pinned query with quality columns bolted
on as OPTIONAL -- identical WHERE, identical LIMIT 100, identical implicit order.

WHY OPTIONAL. Most rows carry no flag. A non-optional triple pattern for a flag
would drop unflagged rows and SHRINK the 100-row window -- a different window.
OPTIONAL keeps all 100 rows; the flag columns are bound only where the flag
exists, empty elsewhere. Window preserved, flags counted.

This query reads NO correctness and makes NO judgement about value magnitude. It
answers one question: what quality markers stand on which rows of the window.

Candidate exclusion signals inventoried (final set decided AFTER seeing counts):
  1. dataValidityIssue = true        -- source flags the measurement as suspect
  2. potentialDuplicate = true       -- source flags a likely duplicate
  3. activityComment                 -- free text; may say "Not Active" etc.
  4. standardRelation != "="         -- ">10uM" is not a unique IC50
     (relation is inventoried too: an inequality gives no unique answer, so it
      cannot be a valid units-arm item regardless of any flag.)

Usage:
    python3 inventory_flags.py --sample sample.json --outdir inv_queries/
    # run each through run_sparql (database="chembl"), save as <TARGET>.csv
    python3 inventory_flags.py summarise --csvdir inv_csv/ --out flag_inventory.json
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import Counter, OrderedDict

# The pinned query, extended. The base pattern is IDENTICAL to count_window.py's
# QUERY_TMPL (same WHERE, same FILTER, same LIMIT) so the window matches. Quality
# properties are added as OPTIONAL so no row is dropped. ?activity, ?value,
# ?units carry over from the base; the added columns describe the same rows.
QUERY_TMPL = """PREFIX cco: <http://rdf.ebi.ac.uk/terms/chembl#>
SELECT ?chemblId ?value ?units ?relation ?validIssue ?validComment ?dup ?comment
FROM <http://rdf.ebi.ac.uk/dataset/chembl>
WHERE {{
  ?activity a cco:Activity ;
            cco:hasMolecule ?molecule ;
            cco:hasAssay/cco:hasTarget <http://rdf.ebi.ac.uk/resource/chembl/target/{target}> ;
            cco:standardType "IC50" ;
            cco:value ?value ;
            cco:units ?units .
  ?molecule cco:chemblId ?chemblId .
  OPTIONAL {{ ?activity cco:standardRelation ?relation }}
  OPTIONAL {{ ?activity cco:dataValidityIssue ?validIssue }}
  OPTIONAL {{ ?activity cco:dataValidityComment ?validComment }}
  OPTIONAL {{ ?activity cco:potentialDuplicate ?dup }}
  OPTIONAL {{ ?activity cco:activityComment ?comment }}
  FILTER(?units IN ("nM", "uM"))
}}
ORDER BY ?activity
LIMIT 100"""


def cmd_queries(args):
    with open(args.sample, encoding="utf-8") as fh:
        prov = json.load(fh)
    os.makedirs(args.outdir, exist_ok=True)
    for t in prov["sample"]:
        path = os.path.join(args.outdir, f"{t}.rq")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(QUERY_TMPL.format(target=t) + "\n")
        print(f"wrote {path}")
    print(
        "\n# Run each through run_sparql (database=\"chembl\") exactly as written.\n"
        "# Save the CSV the TOOL returns as <TARGET>.csv.\n"
        "#\n"
        "# The row COUNT must still be <=100 and match the count_window.py window\n"
        "# for that target. If a target that returned 100 rows there returns a\n"
        "# different number here, the OPTIONALs changed the window -- STOP and\n"
        "# tell the analyst; do not summarise a different table.",
        file=sys.stderr,
    )


def parse_csv(text):
    rdr = csv.reader(io.StringIO(text))
    rows = [r for r in rdr if r and any(c.strip() for c in r)]
    if not rows:
        return None, []
    return rows[0], rows[1:]


def col(header):
    return [c.strip().lstrip("?") for c in header]


def truthy(s):
    return s.strip().lower() in ("true", "1", "1.0", "t")


def summarise(target, text):
    sha1 = hashlib.sha1(text.encode("utf-8")).hexdigest()
    header, rows = parse_csv(text)
    rec = OrderedDict(target=target, sha1=sha1, n_rows=len(rows))
    if header is None:
        rec["error"] = "empty payload"
        return rec

    cols = col(header)
    idx = {name: (cols.index(name) if name in cols else None)
           for name in ("chemblId", "value", "units", "relation",
                        "validIssue", "validComment", "dup", "comment")}
    missing = [k for k, v in idx.items() if v is None]
    if missing:
        rec["error"] = f"missing columns {missing}; header was {header!r}"
        return rec

    def get(r, name):
        i = idx[name]
        return r[i].strip() if i is not None and i < len(r) else ""

    n_valid = n_dup = n_relation_ne = n_comment = 0
    relation_values = Counter()
    comment_values = Counter()
    validcomment_values = Counter()
    # rows hit by ANY candidate signal (union), for a headline number
    hit_rows = 0
    # how many rows each signal UNIQUELY removes (only signal on that row)
    for r in rows:
        rel = get(r, "relation")
        vi = get(r, "validIssue")
        dup = get(r, "dup")
        com = get(r, "comment")
        vc = get(r, "validComment")

        sig = False
        if vi and truthy(vi):
            n_valid += 1; sig = True
        if dup and truthy(dup):
            n_dup += 1; sig = True
        if rel and rel != "=":
            n_relation_ne += 1; sig = True
            relation_values[rel] += 1
        elif rel:
            relation_values[rel] += 1
        if com:
            n_comment += 1
            comment_values[com] += 1
            # comment counts toward "has comment" but whether it EXCLUDES
            # depends on its text -- decided after inspection, so don't set sig
        if vc:
            validcomment_values[vc] += 1
        if sig:
            hit_rows += 1

    rec["n_dataValidityIssue_true"] = n_valid
    rec["n_potentialDuplicate_true"] = n_dup
    rec["n_relation_not_equals"] = n_relation_ne
    rec["n_with_activityComment"] = n_comment
    rec["rows_hit_by_flag_union_excl_comment"] = hit_rows
    rec["relation_values"] = dict(relation_values)
    rec["activityComment_values"] = dict(comment_values)
    rec["dataValidityComment_values"] = dict(validcomment_values)
    return rec


def cmd_summarise(args):
    files = sorted(f for f in os.listdir(args.csvdir) if f.endswith(".csv"))
    if not files:
        raise SystemExit(f"no .csv in {args.csvdir}")

    recs = [summarise(re.sub(r"\.csv$", "", f),
                      open(os.path.join(args.csvdir, f), encoding="utf-8").read())
            for f in files]

    # sanity: distinct payloads (same check as everywhere else)
    shas = Counter(r["sha1"] for r in recs)
    dupes = [s for s, n in shas.items() if n > 1]
    if dupes:
        print("*** STOP: identical inventory payloads across targets; target URI "
              "not reaching the query. ***", file=sys.stderr)

    print(f"{'target':<15} {'rows':>4} {'valid':>5} {'dup':>4} {'rel!=':>5} "
          f"{'cmnt':>4}  relation_values")
    for r in recs:
        if "error" in r:
            print(f"{r['target']:<15} ERROR {r['error']}")
            continue
        print(f"{r['target']:<15} {r['n_rows']:>4} "
              f"{r['n_dataValidityIssue_true']:>5} {r['n_potentialDuplicate_true']:>4} "
              f"{r['n_relation_not_equals']:>5} {r['n_with_activityComment']:>4}  "
              f"{r['relation_values']}")

    # collect distinct comment texts across all targets -- these need eyeballs
    all_comments = Counter()
    all_validcomments = Counter()
    for r in recs:
        for k, v in r.get("activityComment_values", {}).items():
            all_comments[k] += v
        for k, v in r.get("dataValidityComment_values", {}).items():
            all_validcomments[k] += v
    if all_comments:
        print("\nDistinct activityComment texts (inspect before deciding "
              "which exclude):")
        for txt, n in all_comments.most_common():
            print(f"  {n:>4}x  {txt!r}")
    if all_validcomments:
        print("\nDistinct dataValidityComment texts:")
        for txt, n in all_validcomments.most_common():
            print(f"  {n:>4}x  {txt!r}")

    out = OrderedDict(
        targets=len(recs),
        identical_payload=bool(dupes),
        distinct_activityComment_texts=list(all_comments),
        distinct_dataValidityComment_texts=list(all_validcomments),
        per_target=recs,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
        print(f"\nwritten to {args.out}")
    print("\nNext: decide the exclusion set from these counts + comment texts, "
          "then re-run count_window.py with the chosen filters applied to the "
          "window query. Do NOT write task files until the exclusion set is fixed.")


def main():
    import sys
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queries")
    q.add_argument("--sample", required=True)
    q.add_argument("--outdir", default="inv_queries")
    q.set_defaults(func=cmd_queries)
    s = sub.add_parser("summarise")
    s.add_argument("--csvdir", required=True)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_summarise)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    import sys
    main()
