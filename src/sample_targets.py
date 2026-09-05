#!/usr/bin/env python3
"""
Draw a reproducible sample of ChEMBL targets from the enumerated population.

POPULATION. Targets with at least one IC50 activity in nM and at least one in uM:

    PREFIX cco: <http://rdf.ebi.ac.uk/terms/chembl#>
    SELECT (STRAFTER(str(?target), "/target/") AS ?targetID) WHERE {
      { SELECT ?target WHERE {
          ?activity a cco:Activity ; cco:hasAssay/cco:hasTarget ?target ;
                    cco:standardType "IC50" ; cco:units ?units .
          FILTER(?units IN ("nM", "uM"))
        } GROUP BY ?target HAVING (COUNT(DISTINCT ?units) > 1) }
    }

  Expected size: 3629 (verify with --expect; a mismatch means the endpoint or
  the query moved and the sample is not the one the paper describes).

  Note the scope this defines: unit mixture is a SCOPE CONDITION, not a
  selection on a payload property. Without mixture the manipulation is
  undefined -- stripping the unit column from an all-nM table leaves the naive
  nM reading accidentally correct on every row, and the arm measures nothing
  (cf. CHEMBL4523419 in the label arm). The uM:nM RATIO is never consulted here.

WHY NOT random.sample(). Mersenne Twister output depends on the CPython
implementation and random.sample() additionally depends on the ORDER of the
input sequence. Rank-by-hash depends on neither: rank(id) = sha256(seed:id),
take the smallest 6. Reproducible in any language, from an unordered list.

WHY --seed IS REQUIRED. A default seed is a decision nobody made. Declare it,
then draw. Re-drawing after seeing any counts is contamination; re-drawing
before is not.

Usage:
    python3 sample_targets.py --population targets_3629.txt --seed 20260718 \
        --n 6 --expect 3629 --out sample.json
"""

import argparse
import hashlib
import json
import re
import sys

ID_RE = re.compile(r"CHEMBL\d+")


def load_population(path):
    """Read target IDs from a file: one per line, or a CSV/TSV column, or
    quoted SPARQL results. Anything matching CHEMBL\\d+ is taken; everything
    else on the line is ignored. Order is irrelevant to the draw."""
    ids, malformed = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            found = ID_RE.findall(line)
            if len(found) == 1:
                ids.append(found[0])
            elif len(found) == 0:
                malformed += 1  # header line, most likely
            else:
                # More than one ID on a line is ambiguous; refuse to guess.
                sys.exit(f"ERROR: {len(found)} target IDs on one line: {line!r}")
    return ids, malformed


def rank(seed, target_id):
    """Deterministic sort key. Independent of language, runtime and input order."""
    return hashlib.sha256(f"{seed}:{target_id}".encode("utf-8")).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", required=True,
                    help="file of target IDs (the 3629 from the HAVING query)")
    ap.add_argument("--seed", required=True,
                    help="declared before drawing; recorded in the output")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--expect", type=int, default=None,
                    help="assert population size (use 3629)")
    ap.add_argument("--out", default=None, help="write provenance JSON here")
    args = ap.parse_args()

    ids, malformed = load_population(args.population)

    # --- sanity checks on the population itself -------------------------
    n_raw = len(ids)
    uniq = sorted(set(ids))
    n_uniq = len(uniq)

    if malformed:
        print(f"note: {malformed} line(s) held no target ID (header?), ignored",
              file=sys.stderr)
    if n_uniq != n_raw:
        print(f"WARNING: {n_raw - n_uniq} duplicate ID(s) in the population; "
              f"de-duplicated to {n_uniq}. The HAVING query groups by target, "
              f"so duplicates should not occur -- check the export.",
              file=sys.stderr)
    if args.expect is not None and n_uniq != args.expect:
        sys.exit(f"ERROR: population is {n_uniq}, expected {args.expect}. "
                 f"The endpoint or the query moved. Do not draw from this list.")
    if args.n > n_uniq:
        sys.exit(f"ERROR: cannot draw {args.n} from {n_uniq}.")

    # Pin the population itself, so the paper can state WHICH 3629.
    pop_digest = hashlib.sha256("\n".join(uniq).encode("utf-8")).hexdigest()

    # --- the draw --------------------------------------------------------
    ranked = sorted(uniq, key=lambda t: rank(args.seed, t))
    sample = ranked[:args.n]

    provenance = {
        "population_file": args.population,
        "population_size": n_uniq,
        "population_sha256": pop_digest,
        "seed": args.seed,
        "n": args.n,
        "method": "rank = sha256(seed + ':' + target_id), ascending, take n",
        "sample": sample,
        "sample_ranks": {t: rank(args.seed, t)[:16] for t in sample},
    }

    print(json.dumps(provenance, indent=2))
    print("\n# sample, in draw order:", file=sys.stderr)
    for i, t in enumerate(sample, 1):
        print(f"  {i}. {t}", file=sys.stderr)
    print("\n# Record population_sha256 and seed in the paper. Both are needed "
          "to reproduce the draw.", file=sys.stderr)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(provenance, fh, indent=2)
        print(f"# provenance written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
