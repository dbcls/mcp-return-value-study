#!/usr/bin/env bash
# Auto re-run every target that has a gate-1 hole caused by a SPARQL-endpoint
# fault (sparql_error), one after another, retrying each until its pinned sha1s
# are all present or a retry budget is exhausted. Deterministic at temperature 0,
# so a clean re-run reproduces the valid payloads; only the transient endpoint
# failures change.
#
# It re-runs ONLY targets whose holes are sparql_error. Targets whose holes are
# no_run_sparql / missing are reported and SKIPPED (re-running a deterministic
# agent choice changes nothing -- inspect those by hand).
#
# Usage:
#   ./rerun_failed.sh                 # auto-detect targets from runs, fix all
#   ./rerun_failed.sh CHEMBL1875 ...  # only these targets
set -u

# ---- config (edit to your environment) ----
M=${M:-qwen3.6-35b-a3b}
BASE_URL=${BASE_URL:-http://localhost:8080}
TASKS_DIR=${TASKS_DIR:-tasks_units20}
RUNS_DIR=${RUNS_DIR:-runs_units20}
POST=${POST:-post_exclusion20.json}
MAX_TRIES=${MAX_TRIES:-5}
SLEEP=${SLEEP:-30}            # seconds between retries (endpoint recovery)
LOG=${LOG:-rerun.log}

runs_glob="$RUNS_DIR/units20.*.jsonl"

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# ---- returns the count of sparql_error item-conditions for one target ----
# prints "<sparql_error> <no_run_sparql> <missing>"
holes_for(){ # $1 = target, $2 = runs glob
python3 - "$1" "$POST" $2 <<'PY'
import json,sys,glob
T=sys.argv[1]; post=sys.argv[2]; globs=sys.argv[3:]
p=json.load(open(post))
tb=[x for x in p['per_target'] if x['target']==T][0]
ids={f"t_u20_{T}_{c}" for c,_ in tb['items_uM']}|{f"c_u20_{T}_{c}" for c,_ in tb['items_nM']}
by={}
for g in globs:
    for path in glob.glob(g):
        for l in open(path):
            r=json.loads(l)
            if r.get('task_id') in ids and r.get('condition') in ('units_on','units_off'):
                by.setdefault((r['task_id'],r['condition']),r)
def status(r):
    sp=[c for c in (r.get('tool_calls') or []) if c.get('name')=='run_sparql']
    if not sp: return 'no_run_sparql'
    f=sp[0]
    return 'ok' if (f.get('output_sha1') and f.get('ok',True)) else 'sparql_error'
se=nr=miss=0
for tid in ids:
    for cond in ('units_on','units_off'):
        r=by.get((tid,cond))
        if r is None: miss+=1
        else:
            s=status(r)
            if s=='sparql_error': se+=1
            elif s=='no_run_sparql': nr+=1
print(f"{se} {nr} {miss}")
PY
}

# ---- pick targets ----
if [ "$#" -gt 0 ]; then
    targets=("$@")
else
    mapfile -t targets < <(python3 - "$POST" $runs_glob <<'PY'
import json,sys,glob
post=sys.argv[1]; globs=sys.argv[2:]
p=json.load(open(post))
def tof(t):
    a=t.split('_'); return a[2] if len(a)>=4 and a[1]=='u20' and a[0] in('t','c') else None
def status(r):
    sp=[c for c in (r.get('tool_calls') or []) if c.get('name')=='run_sparql']
    if not sp: return 'no_run_sparql'
    f=sp[0]; return 'ok' if (f.get('output_sha1') and f.get('ok',True)) else 'sparql_error'
bad=set()
for g in globs:
    for path in glob.glob(g):
        for l in open(path):
            r=json.loads(l); t=tof(r.get('task_id',''))
            if t and r.get('condition') in('units_on','units_off') and status(r)=='sparql_error':
                bad.add(t)
print('\n'.join(sorted(bad)))
PY
)
fi

if [ "${#targets[@]}" -eq 0 ] || [ -z "${targets[0]:-}" ]; then
    log "no targets with sparql_error holes -- nothing to re-run."; exit 0
fi

log "targets to re-run (sparql_error): ${targets[*]}"
green=(); still=()

for T in "${targets[@]}"; do
    [ -z "$T" ] && continue
    tfile="$TASKS_DIR/tasks.units_$T.yaml"
    out="$RUNS_DIR/units20.$T.$M.jsonl"
    if [ ! -f "$tfile" ]; then log "SKIP $T: task file $tfile not found"; still+=("$T"); continue; fi

    ok=0
    for try in $(seq 1 "$MAX_TRIES"); do
        log "$T: attempt $try/$MAX_TRIES -- running headless_runner"
        rm -f "$out"                       # force a fresh run (avoid resume-skip)
        python3 headless_runner.py --base-url "$BASE_URL" --model-label "$M" \
            run --tasks "$tfile" --out "$out" \
                --conditions units_on,units_off --repeats 1 >>"$LOG" 2>&1

        read se nr miss < <(holes_for "$T" "$out")
        log "$T: after attempt $try -> sparql_error=$se no_run_sparql=$nr missing=$miss"
        if [ "$se" -eq 0 ] && [ "$miss" -eq 0 ]; then
            if [ "$nr" -eq 0 ]; then
                log "$T: CLEAN (all pinned sha1 present)"; ok=1; break
            else
                log "$T: no sparql_error left, but no_run_sparql=$nr remains -- INSPECT (agent behaviour, not endpoint)"; ok=2; break
            fi
        fi
        [ "$try" -lt "$MAX_TRIES" ] && { log "$T: retrying in ${SLEEP}s"; sleep "$SLEEP"; }
    done

    if [ "$ok" -eq 1 ]; then green+=("$T")
    else still+=("$T"); log "$T: STILL NOT CLEAN after $MAX_TRIES tries"; fi
done

log "==== summary ===="
log "green (re-run fixed): ${green[*]:-none}"
log "needs attention:      ${still[*]:-none}"
log "next: cat $RUNS_DIR/units20.*.jsonl > $RUNS_DIR/all.jsonl && \
python3 check_run_gates.py --runs $RUNS_DIR/all.jsonl \
--expected-windows expected_windows/ --payload-dir captured/ | tee gate_report.txt"
[ "${#still[@]}" -eq 0 ]
