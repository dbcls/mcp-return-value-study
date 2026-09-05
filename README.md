# When explicitness pays in a tool's return value

A controlled study of how the explicitness of an MCP server's *return value*
affects an LLM agent's answers and its token cost, on a production life-science
server (TogoMCP over the EMBL-EBI RDF platform, ChEMBL v34). The model and the
task are held fixed; only one column of the returned payload is changed.

Central finding: whether being explicit helps depends on **which agent is asking**,
not on what the payload contains. This repository contains the code, the task
suites, and the aggregated (scored) results needed to reproduce every number in
the paper (`paper/main.tex`).

## The two experiments

**Label arm (recoverable ambiguity).** A compound's `rdfs:label` is either its
real name or a copy of its own accession, which also appears in the next column,
so the ambiguity is resolvable from the payload alone. Conditions:
`label_implicit` (native table) vs `label_explicit` (native table plus one
`moleculeLabel_kind` column marking each label as `name` or `id`; a deterministic
function of columns already present, so it adds no information).

**Units arm (genuinely absent information).** IC50 rows returned as
`chemblId, value, units`, filtered to nM/uM. Conditions: `units_on` (native
table) vs `units_off` (units column removed, so a bare value is ambiguous by a
factor of 1000). Twenty targets sampled reproducibly by
`rank = sha256(seed + ':' + target_id)`.

Both arms fix a deterministic response window with `ORDER BY` (`?chemblId` for
label, `?activity` for units), because `LIMIT` without an ordering returns a
non-reproducible subset.

## Repository layout

```
src/            pipeline code (task generation, scoring, gates)
tests/          self-tests for the scorer (run these first)
tasks/          the frozen task suites fed to the agent
  units20/      tasks_units20_ordered_ALL.yaml + per_target/*.yaml (20 targets)
                template.chembl_units_pilot.yaml (generator scaffold)
  label/        tasks.chembl_label_full.yaml (TP53, 124 id-only + 76 named)
data/           inputs and the deterministic item selection
  sample20.json                 seed, population hash, sampled targets
  post_exclusion20_ordered.json frozen per-target item lists (gate-3 reference)
  expected_windows_ordered/     deterministic window per target (gate-2 reference)
  activity_uniqueness.tsv       verification that ?activity is unique per row
  ordered_window_usability.tsv  window usability check (20/20)
results/        aggregated, scored outputs (final, v4-adjudicated)
  perrun_units20_*.csv          per-run judgments (both models)
  perrun_label_full_bothmodels.csv
  table_units_per_target.csv    paper Table (per-target b/c)
  table_noticing_mediation.csv  paper Table (noticing vs recovery)
  cmh_units20.json              McNemar b/c recomputed from the shipped CSVs
  RESULTS_*.md, *.md            narrative result summaries
paper/          main.tex (CEURART) + references.bib
docs/           RUNBOOK_units20.md (operational live-run procedure)
```

## Dependencies

Python 3.9+ and a single third-party package:

```bash
pip install -r requirements.txt   # PyYAML only
```

Everything else (task generation, scoring, gate checks, statistics) uses the
standard library.

## Quick start: verify the scorer and reproduce the headline statistics

The scorer is the load-bearing component (a broken manipulation here returns
fluent, plausible prose rather than an error, so scoring is checked against raw
bytes). Start by running its self-tests:

```bash
PYTHONPATH=src python3 tests/test_numeric_scoring.py   # extractor + log-distance judge
PYTHONPATH=src python3 tests/test_classify_answer.py   # correct / trap / neither / review
PYTHONPATH=src python3 tests/test_score_hook.py        # scoring hook wiring
```

The final McNemar counts in the paper are recomputed directly from the shipped
per-run CSVs (no raw logs needed):

```bash
python3 - <<'PY'
import csv
from collections import defaultdict
def load(p):
    r=defaultdict(dict)
    for row in csv.DictReader(open(p)):
        r[row['task_id']][row['condition']]=row['correct'].strip().lower() in ('1','true','yes')
    return r
def mc(rows,pfx):
    b=c=on=off=n=0
    for t,d in rows.items():
        if not t.startswith(pfx) or 'units_on' not in d or 'units_off' not in d: continue
        n+=1; on+=d['units_on']; off+=d['units_off']
        b+= d['units_on'] and not d['units_off']
        c+= d['units_off'] and not d['units_on']
    print(f"{pfx}: n={n} on={on} off={off} b={b} c={c}")
r=load('results/perrun_units20_qwen3.6-35b-a3b.csv')
mc(r,'t_'); mc(r,'c_')   # expect  t_: n=929 on=929 off=579 b=350 c=0   /  c_: n=308 on=308 off=307 b=1 c=0
PY
```

This matches `results/cmh_units20.json` and Table 2 of the paper.

## Regenerating the task suites from source

The task YAMLs under `tasks/` are the frozen, canonical suites used in the paper;
they are generated, not hand-edited. To regenerate them:

```bash
# Units: from the frozen post-exclusion item lists.
#   --post-exclusion  the frozen item lists
#   --out-dir         where per-target YAMLs are written
#   --expect-treat / --expect-ctrl  assert the item counts (929 / 308 for the
#                     ordered 20-target suite; the defaults 804/276 are the pilot)
PYTHONPATH=src python3 src/make_units20_tasks.py \
    --post-exclusion data/post_exclusion20_ordered.json \
    --template tasks/units20/template.chembl_units_pilot.yaml \
    --out-dir /tmp/units20_regen \
    --expect-treat 929 --expect-ctrl 308
diff -rq /tmp/units20_regen tasks/units20/per_target   # -> identical

# Label: full deterministic TP53 window (data embedded; no arguments)
PYTHONPATH=src python3 src/make_label_full.py
```

`--template` supplies the prompt / `abstain_regex` scaffold; the generator
injects `ORDER BY ?activity` into the pinned query (see the file header). The
regenerated suite is byte-for-byte identical to `tasks/units20/per_target/`.

`src/sample_targets.py` reproduces the 20-target sample from the seed and
population hash recorded in `data/sample20.json`:

```bash
PYTHONPATH=src python3 src/sample_targets.py \
    --population targets_3629.txt --seed sample-2026-07-18 --n 20 --expect 20
```

`src/apply_exclusions.py` rebuilds `post_exclusion20_ordered.json` and the
`expected_windows_ordered/` references from the raw inventory CSVs
(`--invdir`, `--out`, `--windowdir`); it must reproduce the frozen JSON
byte-for-byte, otherwise the inventory inputs differ from what the item lists
were cut from. The raw inventory CSVs and the population file `targets_3629.txt`
are products of the live endpoint and are not distributed here.

## Full re-run (requires the model harness and a live endpoint)

Running the agents themselves is **not** reproducible from this repository alone.
It needs two things not distributed here:

1. **A live TogoMCP / SPARQL endpoint** exposing `run_sparql` over ChEMBL v34.
2. **`headless_runner.py`** — the agent driver that serves each task to a model
   (two open-weight agents via vLLM at temperature 0), applies the per-condition
   payload reshaping (`units_on/off`, `label_implicit/explicit`) to the tool
   return, and writes one JSON-lines record per run. It lived in a separate
   `mcpbench_runner/` component and is referenced by `src/rerun_failed.sh` and
   `docs/RUNBOOK_units20.md`. Supply your own driver with the same interface:

   ```
   python3 headless_runner.py --base-url URL --model-label M \
       run --tasks TASKFILE --out OUT.jsonl \
           --conditions units_on,units_off --repeats 1
   ```

   Each output record is expected to carry at least `task_id`, `condition`,
   `tool_calls[]` (each with `name`, `output_sha1`, `ok`), token counts, and the
   final answer text. The scorer and gate checker read exactly these fields.

`docs/RUNBOOK_units20.md` is the operational procedure: run targets one at a
time and clear each through three gates before its numbers enter the analysis.

### Gates (verification)

Because broken manipulations do not crash, no aggregate is trusted until, per
item: (gate 1) the first `run_sparql` output differs between conditions; (gate 2)
the table the agent received under `units_on` matches the deterministic selection
window row-for-row; (gate 3) the scored item ids match the frozen list.

```bash
cat runs_units20/units20.*.jsonl > runs_units20/all.jsonl
PYTHONPATH=src python3 src/check_run_gates.py \
    --runs runs_units20/all.jsonl \
    --expected-windows data/expected_windows_ordered/ \
    --payload-dir captured/ | tee gate_report.txt
```

`src/remediate_runs.py` and `src/rerun_failed.sh` classify endpoint faults
(`sparql_error` vs `no_run_sparql`) and auto re-run only the transiently failed
targets.

## Models

Two open-weight agents served locally with vLLM at temperature 0, thinking
disabled: **Qwen3.6-35B-A3B** (higher-performing) and **Qwen3-30B-A3B**
(lower-performing). The lower-performing model needs a YaRN rope scaling factor
of 2.0 and a 65,536 maximum context; a wrong factor silently corrupts
generation, so verify the serving command before each run (see the runbook).
The two agents differ in both size and generation, so "higher/lower-performing"
labels a specific pair, not a general capability law (paper, Limitations).

## Data provenance and licensing

Underlying facts are from ChEMBL v34 (EMBL-EBI), used here only to construct and
score tasks. The code and task specifications in this repository are released
under the MIT License (`LICENSE`). Please cite ChEMBL and TogoMCP / the RDF
portal according to their own terms when reusing the derived data.

## Citation
TBD.
