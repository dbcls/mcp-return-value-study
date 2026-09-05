# RUNBOOK — 20-target units experiment (section 5.5)

Executes the frozen 20-target units experiment and clears every target through
the three gates before its numbers enter the analysis. **Run targets one at a
time. Do not proceed past a red gate.** A broken manipulation here does not
crash; it returns fluent prose that looks like a finding (HANDOVER.md section 4).

This runbook covers the live-run steps that must happen on the machine with the
vLLM server and TogoMCP. The task files, scorer, and gate checker are already
built and self-tested in this directory.

---

## 0. Preconditions (files in this directory)

| file | role | status |
|---|---|---|
| `tasks_units20/tasks.units_CHEMBL*.yaml` (20) | per-target task files, numeric scoring | built, cross-checked (804 treat + 276 ctrl) |
| `post_exclusion20.json` | frozen item lists; gate 3 reference | given |
| `score.py` | scorer, numeric hook wired | built, regression-checked |
| `numeric_scoring.py` | extractor + log-distance judge | frozen, 12/12 + 6/6 + 2/2 |
| `check_run_gates.py` | gate 1 / 3 auto, gate 2 if payloads captured | built, self-tested |
| `headless_runner.py` | run driver | **from mcpbench_runner/** (not in this dir) |
| `expected_windows/CHEMBL*.csv` (20) | gate 2 reference | **regenerate — see step 1** |

If `expected_windows/` is absent, regenerate from the inventory CSVs:

```bash
python3 apply_exclusions.py --invdir inv_csv/ --out post_exclusion20.json \
    --windowdir expected_windows/
# Must reproduce post_exclusion20.json byte-for-byte (it is frozen); if it does
# not, STOP — the inventory inputs differ from what the item lists were cut from.
```

---

## 1. Environment — verify BEFORE any run (HANDOVER.md section 3)

Model switch = vLLM restart. After `docker compose up -d --force-recreate vllm flask-chat`:

```bash
docker compose logs vllm | grep -m1 "entrypoint] vllm serve"
```

Confirm the serve line matches the model you intend. The two profiles:

| | Qwen3.6-35B-A3B | Qwen3-30B-A3B |
|---|---|---|
| `TOOL_CALL_PARSER` | `qwen3_coder` | `hermes` |
| `REASONING_PARSER` | `qwen3` | (empty) |
| `MAX_MODEL_LEN` | `131072` | `65536` |
| `HF_OVERRIDES` (YaRN `factor`) | **empty** | `factor:2.0` (NEVER 4.0 — landmine 4) |

Held fixed both: `TEMPERATURE=0.0`, `MAX_TOKENS=16384`, `DISABLE_THINKING=true`,
`RECURSION_LIMIT=60`, `TRIM_MAX_TOKENS=48000`, single worker, sequential.
`HF_OVERRIDES` must be in `compose.yaml`'s `environment:`, not just `.env`.

---

## 2. Per-target loop (one target at a time)

```bash
M=qwen3.6-35b-a3b            # primary model; Qwen3-30B floors on uM (report separately)
mkdir -p runs_units20 captured

for f in tasks_units20/tasks.units_*.yaml; do
  T=$(basename "$f" .yaml | sed 's/tasks.units_//')
  OUT=runs_units20/units20.$T.$M.jsonl

  # --- run (do NOT pipe through head; SIGPIPE kills the sweep) ---
  python3 headless_runner.py --base-url http://localhost:8080 --model-label $M \
      run --tasks "$f" --out "$OUT" \
          --conditions units_on,units_off --repeats 1

  # --- gate 2 capture: the pinned units_on payload is deterministic. Run the
  #     pinned query once through run_sparql (units_on reshaping) and save the
  #     tool's CSV as captured/$T.units_on.csv. (Gate 2 needs the bytes; the
  #     run log stores only a hash.) ---
  #   ... capture step here (via your run_sparql client) ...

  # --- gates 1 & 3 (auto) + gate 2 (if captured) ---
  python3 check_run_gates.py --runs "$OUT" \
      --post-exclusion post_exclusion20.json \
      --expected-windows expected_windows/ --payload-dir captured/ \
      --only $T
  # exit 0 = CLEARED. Non-zero = BLOCKED; stop and read the bytes before rerun.
done
```

**The three gates** (all must pass per target):

1. **Payload identity** — first `run_sparql` `output_sha1` differs between
   `units_on` and `units_off` for every item. Identical hash = the unit column
   was not really dropped/added; the run measures nothing. (Auto.)
2. **Window match** — the captured `units_on` payload equals
   `expected_windows/<T>.csv` row-for-row. Requires the captured CSV (step
   above); the run log has no payload bytes. (Auto if captured, else SKIP.)
3. **Item count / ids** — the scored ids equal exactly what
   `post_exclusion20.json` defines for the target, under both conditions. (Auto.)

Manual cross-check of gate 1 (matches the auto-check):

```bash
jq -r '.condition + " " + ([.tool_calls[]|select(.name=="run_sparql")|.output_sha1]|.[0] // "FAILED")' \
   runs_units20/units20.$T.$M.jsonl | sort | uniq -c
# expect one distinct hash per condition, and the two conditions must differ.
```

---

## 3. Score (after all targets cleared)

Score per target with its own task file, collect one combined per-run CSV:

```bash
for f in tasks_units20/tasks.units_*.yaml; do
  T=$(basename "$f" .yaml | sed 's/tasks.units_//')
  python3 score.py --by-model --tasks "$f" \
      --runs runs_units20/units20.$T.$M.jsonl \
      --per-run runs_units20/perrun.$T.csv
done
# concat per-run CSVs (single header)
{ head -1 runs_units20/perrun.$(ls runs_units20 | grep perrun | head -1 | sed 's/perrun.//;s/.csv//').csv; \
  for c in runs_units20/perrun.*.csv; do tail -n +2 "$c"; done; } > runs_units20/perrun.all.csv
```

The per-run CSV carries the audit columns (`arm`, `numeric_verdict`,
`extracted_nM`, `answer_nM`, `trap_nM`, `answer_tail`) so each verdict can be
eyeballed against the conclusion sentence.

---

## 4. Statistics (frozen design, section 1.5)

- **Primary**: stratified McNemar pooled by **CMH (1 df, two-sided)** across the
  20 targets. Effective sample = 20 targets (within-stratum paired, strata
  independent). Same-sign only; do NOT assume or claim homogeneity.
- **Specificity**: stratified Fisher/CMH on control-bearing targets
  (control_n >= 8: 8 targets). Prediction: control (nM) failures concentrate in
  uM-dominant targets.
- **Breslow–Day is NOT tested** (untestable at this n); describe per-target
  (b, c) in a table and say so.
- Per-target b/c from `perrun.all.csv` (pair on `task_id` across conditions;
  the pairing, not the marginals, gives b and c — HANDOVER.md).

---

## 5. What must be true before writing numbers

- Every target CLEARED (all three gates). Targets not cleared are excluded and
  the reason logged; do not quietly drop them.
- `output_sha1` distinct per condition on every item (gate 1) — the single
  cheapest guard against measuring nothing.
- Model profile verified against the serve line (section 1) — a wrong YaRN
  factor corrupts generation while still returning plausible text.
- If the `neither` verdict rate is high, DO NOT move the 0.5-log threshold after
  seeing results; if changed, state the reason and report both before and after
  (section 6, open decision).
