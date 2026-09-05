#!/usr/bin/env python3
"""
Phase 0d: generate the 20-target units-experiment task files from
post_exclusion20.json. NO hand-writing of items -- every id and value is read
from the frozen post-exclusion list and machine-checked back against it.

WHAT IT EMITS
  tasks.units_<TARGET>.yaml, one per usable target (20 files). Each file holds:
    * treatment items (one per items_uM row): answer_nM = value*1000,
      trap_nM = value. Reading the bare uM number as nM is the 1000x error.
    * control items (one per items_nM row): answer_nM = value, NO trap.
  Every item carries the SAME abstain_regex as the pilot suite and NO
  answer_regex / trap regex -- scoring is on the numeric path only (answer_nM /
  trap_nM), per the frozen decision. abstain_regex is text-based and orthogonal,
  so it is reused verbatim.

FAITHFULNESS TO THE PILOT PAYLOAD
  The prompt is the pilot's PARSED prompt string with exactly two substitutions:
    target/CHEMBL4072      -> target/<TARGET>   (the pinned query's target URI)
    compound CHEMBL2370193 -> compound <CID>    (the asked-for molecule)
  LIMIT 100 and the query body are otherwise byte-identical, so the window the
  agent sees is constructed the same way as the pilot's.

NUMBERS ARE COMPUTED FROM THE SOURCE STRING, NOT A FLOAT
  value comes from post_exclusion20.json as a decimal STRING (e.g. "9.45539e-05").
  We use Decimal(value_str); answer = trap*1000. Emitted in plain decimal form
  (no exponent) so a YAML parser can never mistake it for a string. The numeric
  value is identical to float() either way; plain form only removes an accident.

SANITY (all asserted before anything is written to the output dir)
  * per file: n_tasks == len(items_uM)+len(items_nM); ids unique;
    treat answer_nM/trap_nM ratio is exactly 1000; both re-parse to the source.
  * prompt round-trips: yaml.safe_load(dump(item))['prompt'] == expected prompt.
  * totals across all files: 804 treatment + 276 control == 1080.
  * a final read-back of every written file reproduces the same counts.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml


# ---- plain-decimal scalar so answer_nM/trap_nM never emit in exponent form ----
class PlainDecimal:
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


def _represent_plain_decimal(dumper, data):
    # float tag => the value is parsed as a number, not a string, on load.
    return dumper.represent_scalar("tag:yaml.org,2002:float", data.text)


def _represent_str(dumper, data):
    # multiline strings (the prompt) as literal block scalars, so a dump/load
    # round-trip reproduces the exact string the agent receives.
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(PlainDecimal, _represent_plain_decimal)
yaml.add_representer(str, _represent_str)


def fmt_decimal(d: Decimal) -> str:
    """Plain decimal string, no exponent, no trailing-zero noise, no rounding."""
    s = format(d, "f")            # never scientific notation
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def load_template(path: str, order_by: str = "?activity"):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    tasks = data["tasks"] if isinstance(data, dict) else data
    t0 = tasks[0]
    prompt0 = t0["prompt"]
    abstain = t0["abstain_regex"]
    # The pilot template must contain the two anchors we substitute on.
    assert "target/CHEMBL4072" in prompt0, "template target anchor missing"
    assert "compound CHEMBL2370193" in prompt0, "template compound anchor missing"
    assert "LIMIT 100" in prompt0, "template LIMIT 100 missing"
    # Deterministic window: the LIMIT-100 payload is not reproducible across
    # executions without an ORDER BY, so the item-selection window, the agent's
    # run, and the gate-2 capture can draw different 100-row subsets for targets
    # with >100 candidate rows. ORDER BY ?activity (unique per row -> total
    # order; index-ordered, so neutral w.r.t. nM/uM) pins the window so all
    # three agree. Must match inventory_flags.py's QUERY_TMPL and count_window.
    if order_by:
        clause = f"ORDER BY {order_by} "
        assert clause not in prompt0, "template already has this ORDER BY"
        # solution-modifier order: ORDER BY precedes LIMIT
        new = prompt0.replace("} LIMIT 100", f"}} {clause}LIMIT 100")
        assert new != prompt0, "could not inject ORDER BY (no '} LIMIT 100' found)"
        prompt0 = new
    return prompt0, abstain


def make_prompt(prompt0: str, target: str, cid: str) -> str:
    p = prompt0.replace("target/CHEMBL4072", f"target/{target}")
    p = p.replace("compound CHEMBL2370193", f"compound {cid}")
    return p


def build_items(target_block, prompt0, abstain):
    target = target_block["target"]
    items = []
    # treatment: uM rows. answer = value*1000 (nM), trap = value (bare-as-nM).
    for cid, vstr in target_block["items_uM"]:
        trap = Decimal(vstr)
        answer = trap * Decimal(1000)
        items.append({
            "id": f"t_u20_{target}_{cid}",
            "prompt": make_prompt(prompt0, target, cid),
            "answer_nM": PlainDecimal(fmt_decimal(answer)),
            "trap_nM": PlainDecimal(fmt_decimal(trap)),
            "abstain_regex": abstain,
            "_src": ("treat", cid, vstr),      # provenance for self-check; stripped before dump
        })
    # control: nM rows. answer = value, no trap.
    for cid, vstr in target_block["items_nM"]:
        answer = Decimal(vstr)
        items.append({
            "id": f"c_u20_{target}_{cid}",
            "prompt": make_prompt(prompt0, target, cid),
            "answer_nM": PlainDecimal(fmt_decimal(answer)),
            "abstain_regex": abstain,
            "_src": ("ctrl", cid, vstr),
        })
    return items


def check_item(item, prompt0):
    """Re-derive everything and compare; never trust the built dict."""
    kind, cid, vstr = item["_src"]
    target = item["id"].split("_")[2]
    # prompt faithfulness
    expected_prompt = make_prompt(prompt0, target, cid)
    assert item["prompt"] == expected_prompt, f"prompt mismatch {item['id']}"
    assert f"target/{target}" in item["prompt"], f"target URI missing {item['id']}"
    assert f"compound {cid}" in item["prompt"], f"compound missing {item['id']}"
    assert "LIMIT 100" in item["prompt"], f"LIMIT 100 missing {item['id']}"
    # numeric faithfulness, from the SOURCE string
    ans = Decimal(item["answer_nM"].text)
    if kind == "treat":
        trap = Decimal(item["trap_nM"].text)
        assert trap == Decimal(vstr), f"trap != source {item['id']}"
        assert ans == Decimal(vstr) * 1000, f"answer != source*1000 {item['id']}"
        assert ans == trap * 1000, f"answer/trap ratio != 1000 {item['id']}"
    else:
        assert "trap_nM" not in item, f"control has trap {item['id']}"
        assert ans == Decimal(vstr), f"control answer != source {item['id']}"


def strip_src(item):
    return {k: v for k, v in item.items() if k != "_src"}


def dump_tasks(items, target):
    header = (
        f"# Units experiment -- target {target}. Auto-generated by "
        f"make_units20_tasks.py from post_exclusion20.json.\n"
        f"# DO NOT hand-edit: regenerate from source. Scoring is numeric-only "
        f"(answer_nM / trap_nM);\n"
        f"# no answer_regex / trap regex. abstain_regex reused from the pilot "
        f"suite. LIMIT 100 fixed.\n"
        f"# treatment (uM): answer_nM = value*1000, trap_nM = value. "
        f"control (nM): answer_nM = value, no trap.\n\n"
    )
    body = yaml.dump({"tasks": [strip_src(i) for i in items]},
                     sort_keys=False, allow_unicode=True, width=10 ** 9)
    return header + body


def verify_written(path, items):
    """Read the file back with safe_load (what score.py uses) and reconcile."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    tasks = data["tasks"]
    assert len(tasks) == len(items), f"{path}: task count {len(tasks)} != {len(items)}"
    ids = [t["id"] for t in tasks]
    assert len(set(ids)) == len(ids), f"{path}: duplicate ids"
    by_id = {t["id"]: t for t in tasks}
    for item in items:
        t = by_id[item["id"]]
        kind, cid, vstr = item["_src"]
        assert t["prompt"] == item["prompt"], f"{path}: prompt drift {item['id']}"
        assert float(t["answer_nM"]) == float(Decimal(item["answer_nM"].text)), \
            f"{path}: answer drift {item['id']}"
        assert "answer_regex" not in t and "trap" not in t, \
            f"{path}: regex fields leaked into {item['id']}"
        if kind == "treat":
            assert float(t["trap_nM"]) == float(Decimal(item["trap_nM"].text)), \
                f"{path}: trap drift {item['id']}"
        else:
            assert "trap_nM" not in t, f"{path}: control has trap {item['id']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post-exclusion", default="post_exclusion20.json")
    ap.add_argument("--template", default="tasks.chembl_units_items18.yaml")
    ap.add_argument("--out-dir", default="tasks_units20")
    ap.add_argument("--expect-treat", type=int, default=804)
    ap.add_argument("--expect-ctrl", type=int, default=276)
    args = ap.parse_args()

    with open(args.post_exclusion, encoding="utf-8") as fh:
        post = json.load(fh)
    assert post["payload_mode"].startswith("B1"), "payload_mode is not B1"
    assert post["limit"] == 100, "limit is not 100"
    prompt0, abstain = load_template(args.template)

    per_target = post["per_target"]
    all_ids = []
    tot_treat = tot_ctrl = 0
    planned = []  # (target, path, items) -- nothing is written until all checks pass

    for tb in per_target:
        if not tb.get("usable", False):
            print(f"skip non-usable target {tb['target']}", file=sys.stderr)
            continue
        target = tb["target"]
        items = build_items(tb, prompt0, abstain)
        # per-item self-check
        for item in items:
            check_item(item, prompt0)
        # per-file count == source
        n_expected = len(tb["items_uM"]) + len(tb["items_nM"])
        assert len(items) == n_expected, \
            f"{target}: built {len(items)} != source {n_expected}"
        n_treat = sum(1 for i in items if i["_src"][0] == "treat")
        n_ctrl = len(items) - n_treat
        assert n_treat == len(tb["items_uM"])
        assert n_ctrl == len(tb["items_nM"])
        tot_treat += n_treat
        tot_ctrl += n_ctrl
        all_ids.extend(i["id"] for i in items)
        planned.append((target, Path(args.out_dir) / f"tasks.units_{target}.yaml", items))

    # global sanity BEFORE writing
    assert len(set(all_ids)) == len(all_ids), "duplicate ids across targets"
    assert tot_treat == args.expect_treat, f"treat total {tot_treat} != {args.expect_treat}"
    assert tot_ctrl == args.expect_ctrl, f"ctrl total {tot_ctrl} != {args.expect_ctrl}"

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for target, path, items in planned:
        path.write_text(dump_tasks(items, target), encoding="utf-8")
        verify_written(path, items)   # read-back reconciliation

    print(f"wrote {len(planned)} task files to {out}/")
    print(f"  treatment items: {tot_treat}")
    print(f"  control items:   {tot_ctrl}")
    print(f"  total items:     {tot_treat + tot_ctrl}")
    print(f"  unique ids:      {len(set(all_ids))}")
    print("all sanity checks passed")


if __name__ == "__main__":
    main()
