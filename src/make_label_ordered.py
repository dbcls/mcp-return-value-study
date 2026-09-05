#!/usr/bin/env python3
"""
Regenerate the label single-molecule suite on a DETERMINISTIC window.

Root cause fixed: the pinned query (CHEMBL4096 = TP53, 36,494 candidate labelled
molecules) used LIMIT 200 with no ORDER BY, so the 200-row window -- and thus
which molecules the items ask about -- was not reproducible across executions.
We add ORDER BY ?chemblId, making the top-200 window fixed (124 id-only + 76
named at the endpoint), and take the first 18 id-only and first 12 named
molecules of that window (by chemblId) as items. Per-item ground truth is
molecule-intrinsic (does this molecule's rdfs:label equal its accession?) and
independent of the window; only item *availability* depended on the draw, which
the ORDER BY now pins.

Items were pulled from the endpoint (rdfportal.org/ebi) directly, ORDER BY
?chemblId, and are embedded below verbatim.
"""
import re
import yaml

# first 18 id-only (label == accession -> answer NONE), by chemblId, in the
# ORDER BY ?chemblId LIMIT 200 window
ID_ONLY = [
    "CHEMBL10276", "CHEMBL104728", "CHEMBL104732", "CHEMBL105739", "CHEMBL1078244",
    "CHEMBL1080147", "CHEMBL1080510", "CHEMBL1080687", "CHEMBL1080744", "CHEMBL1080861",
    "CHEMBL1080897", "CHEMBL1080915", "CHEMBL1080918", "CHEMBL1081075", "CHEMBL1081635",
    "CHEMBL1081842", "CHEMBL1082160", "CHEMBL1084441",
]
# first 12 named (label is a real name -> answer that name), by chemblId
NAMED = [
    ("CHEMBL100473", "U-0126"),
    ("CHEMBL101", "PHENYLBUTAZONE"),
    ("CHEMBL101326", "FIPRONIL"),
    ("CHEMBL1014", "CANDESARTAN CILEXETIL"),
    ("CHEMBL1018", "DIENESTROL"),
    ("CHEMBL102714", "SB-216763"),
    ("CHEMBL10284", "SB-222200"),
    ("CHEMBL104", "CLOTRIMAZOLE"),
    ("CHEMBL1042", "CHOLECALCIFEROL"),
    ("CHEMBL104255", "FLAVOKAWAIN B"),
    ("CHEMBL105496", "4-METHOXY CHALCONE"),
    ("CHEMBL105712", "PHENACYL CHLORIDE"),
]

QUERY = """PREFIX cco: <http://rdf.ebi.ac.uk/terms/chembl#>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT DISTINCT ?molecule ?moleculeLabel ?chemblId
      FROM <http://rdf.ebi.ac.uk/dataset/chembl>
      WHERE {
        VALUES ?target { <http://rdf.ebi.ac.uk/resource/chembl/target/CHEMBL4096> }
        ?activity a cco:Activity ;
                  cco:hasMolecule ?molecule ;
                  cco:hasAssay/cco:hasTarget ?target .
        ?molecule rdfs:label ?moleculeLabel ; cco:chemblId ?chemblId .
      } ORDER BY ?chemblId LIMIT 200"""

ABSTAIN = (r"(?i)(cannot (definitively|determine|tell)|impossible to "
           r"(tell|determine)|unable to (determine|tell)|no way to know)")


def name_regex(name):
    toks = [re.escape(t) for t in name.split()]
    return r"(?i)\b" + r"\s+".join(toks) + r"\b"


def prompt(cid):
    return (
        'Call run_sparql with database="chembl" and execute EXACTLY the following '
        "query, without modifying it:\n\n"
        + QUERY + "\n\n"
        + f"From the returned rows, find molecule {cid}. Report that molecule's real "
        "compound name. If it has no compound name, answer exactly NONE. Answer "
        "with the name or with NONE, nothing else."
    )


tasks = []
for cid in ID_ONLY:                       # treatment: answer NONE, trap = the accession
    tasks.append({
        "id": f"t_lab1o_{cid}",
        "prompt": prompt(cid),
        "answer_regex": r"(?i)\bNONE\b",
        "trap": {"wrong_if_regex": f"(?i){cid}(?![0-9])"},
        "abstain_regex": ABSTAIN,
        "_kind": "treat",
    })
for cid, nm in NAMED:                      # control: answer = the name, no trap
    tasks.append({
        "id": f"t_lab1o_{cid}",
        "prompt": prompt(cid),
        "answer_regex": name_regex(nm),
        "abstain_regex": ABSTAIN,
        "_kind": "control", "_name": nm,
    })

# ---- sanity ----
assert sum(1 for t in tasks if t["_kind"] == "treat") == 18
assert sum(1 for t in tasks if t["_kind"] == "control") == 12
assert len({t["id"] for t in tasks}) == 30
for t in tasks:
    assert "ORDER BY ?chemblId" in t["prompt"] and "LIMIT 200" in t["prompt"]
    assert t["id"].split("_")[-1] in t["prompt"]

header = """# ChEMBL label collision -- SINGLE-MOLECULE items (18 treatment + 12 control),
# DETERMINISTIC WINDOW. Supersedes tasks.chembl_label_single.yaml, whose pinned
# query used LIMIT 200 with NO ORDER BY over 36,494 candidate molecules, so the
# 200-row window (and the specific items) were not reproducible. Fix: ORDER BY
# ?chemblId. The deterministic top-200 window holds 124 id-only + 76 named; items
# are the first 18 id-only (answer NONE) and first 12 named (answer the name) by
# chemblId within it. Per-item ground truth is molecule-intrinsic.
#
# CONDITIONS (--conditions label_implicit,label_explicit --repeats 1) unchanged.
# The kind column in label_explicit is a deterministic function of two columns
# present in both conditions: zero information, salience only.
#
# DISCLOSURE (for the paper): the naturalistic TP53 payload is 98.4% id-only
# (35,910 / 36,494 labelled molecules; only 584 = 1.6% named). ORDER BY ?chemblId
# front-loads older, named compounds (76/200), so the balanced 18:12 item split
# is a constructed control for statistical power, NOT the naturalistic ratio,
# which is reported separately as prevalence.
#
# TODO byte-audit: the 12 control name regexes are first-draft (whitespace->\\s+,
# literal otherwise). Verify against real answers -- agents may render a name
# differently (e.g. "U-0126" as "U0126", "CHOLECALCIFEROL" as "vitamin D3").

"""

body = yaml.safe_dump(
    {"tasks": [{k: v for k, v in t.items() if not k.startswith("_")} for t in tasks]},
    sort_keys=False, allow_unicode=True, width=10 ** 9)

open("tasks.chembl_label_single_ordered.yaml", "w").write(header + body)
print("wrote tasks.chembl_label_single_ordered.yaml")
print(f"  treatment (NONE): 18, control (named): 12, total ids: 30")
