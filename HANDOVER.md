# HANDOVER — continuing this project in a new session/device

This file lets a fresh Cowork/Claude session (on any device, same or different
account) pick up where the last one left off. Cowork desktop sessions are stored
locally and do NOT sync across devices, so read this file first to restore context.
Project memory (account-level) and this git repository are what carry over.

## What this project is

An empirical study: does making an MCP server's *return value* more explicit help
an LLM agent, and at what token cost? Central finding: **the value of explicitness
depends on which agent is asking, not on what the payload contains.** Venue target:
**SWAT4HCLS 2026** (CEUR-WS / CEURART format, long paper, 10–12 pages plus
references). Manuscript is written dash-free (no em/en dashes) by author preference.

Two experiments (note: call them "experiments", never "arms"):
- **Label experiment** (recoverable ambiguity): TP53 (CHEMBL4096) window; a
  molecule's `rdfs:label` is either a real name or a copy of its own accession,
  which also appears in the next column. Adding a zero-information `moleculeLabel_kind`
  column (id/name) is the manipulation. Real data at measured prevalence (97.7% of
  ChEMBL molecules are accession-as-label).
- **Units experiment** (genuinely absent information): 20 random targets; remove the
  units column so a bare value is ambiguous by 1000x (nM vs uM). A controlled
  reconstruction, not a claim about how often units are dropped in practice.

Two open-weight agents via vLLM at temperature 0: **Qwen3.6-35B-A3B**
(higher-performing) and **Qwen3-30B-A3B** (lower-performing).

## Headline numbers (all verified against the scored CSVs in results/)

Label (Table 1): 3.6 implicit 123/124, explicit 124/124; 30B implicit 16/124,
explicit 75/124; controls 76/76 throughout. Annotation = +407 tokens (0.94% of the
3.6 run at 43,189 tokens; 0.31% of the 30B run at 129,146).

Units (Table 2): 3.6 units_on 929/929 uM, 308/308 nM; units_off 579/929 uM (350
lost, McNemar p < 1e-77), 307/308 nM. 30B units_on 260/929 uM (28%); units_off
0/929. Between-model gap under units_on = 669 uM items.

Cost (units_off, 3.6): uM 35,273 -> 197,819 tokens (5.6x); nM 34,983 -> 143,120
(4.1x). Noticing (Table 4): second call 766 rows, correct 566 (73.9%); one call 163
rows, correct 13 (8.0%); Fisher p ~ 4e-58; second-call mean 232,473 vs 34,967 tokens
(6.6x). Note: Table 4 misread counts (142/140) include 4 human-adjudicated review
items scored as misread; the raw boolean `misread` column alone gives 139/139.

Prevalence: accession-as-label for 1,876,910/1,920,603 ChEMBL molecules (97.7%);
35,910/36,494 TP53 molecules (98.4%); 27,066/275,237 HomoloGene genes (9.8%, second
example only, no agents run on it).

## Repository layout (this repo)

- `paper/main.tex` — the manuscript (CEURART). `paper/references.bib` — 21 entries.
- `src/` — pipeline code (task generation, scoring, gates). `tests/` — scorer self-tests.
- `tasks/` — frozen task suites (units20 + per_target + template; label full + single).
- `data/` — sample20.json, post_exclusion20_ordered.json, expected_windows_ordered/, checks.
- `results/` — scored per-run CSVs (both models), per-target and mediation tables,
  cmh_units20.json, RESULTS_*.md.
- `docs/RUNBOOK_units20.md` — operational live-run procedure.

The canonical manuscript source outside this repo is `outputs/main_revised.tex` plus
`outputs/references.bib` in the last session's working folder; `paper/main.tex` and
`paper/references.bib` here are kept in sync with those. If they ever diverge, treat
`paper/` in this repo as authoritative going forward.

## Reproduce / verify

`pip install -r requirements.txt` (PyYAML only). Run the three scorer tests in
`tests/`. Headline McNemar counts recompute directly from `results/perrun_units20_*.csv`
(see README). Full model re-run needs a live TogoMCP/SPARQL endpoint and an external
`headless_runner.py` (not distributed; interface documented in README).

## Style rules the authors enforce (apply to all edits)

- Dash-free prose. Avoid Japanese financial words; the English cost metaphor was
  changed from insurance/premium to "safeguard/precaution" + "fixed cost/extra cost".
- Avoid out-of-field jargon. Already removed: "arm" (-> experiment), "ecological
  validity" (-> grounded in real data at a measured prevalence), "the frontier"/
  "budget tier" (-> models improve / low-cost deployments), "ships for free"
  (-> incurs for free), "fleet" (-> set).
- No sentence-initial "And/But/So". Keep sentences short; a comma-heavy or 45+ word
  sentence is a candidate to split.
- Every numeric claim must match the scored CSVs. Read the bytes; do not trust
  aggregates (a broken manipulation returns fluent but wrong prose).
- Statistics as LaTeX math ($p < 10^{-77}$). Units as text ($\mu$M, nM). booktabs tables.

## Bibliography notes

All 21 keys used in main.tex are defined in references.bib; none missing, none
unused. TogoMCP = `kinjo2026togomcp` (Database 2026:baag042, DOI 10.1093/database/
baag042). Other keys: zdrazil2024chembl, jupp2014ebirdf, kwon2023vllm,
qwen3technical, peng2023yarn, ncbi2013resources, mcp2024spec, dbcls2026remotemcp,
lewis2020rag, schick2023toolformer, mialon2023augmented, srinivasan2026bridging,
gao2025mcpradar, hasan2026smelly, zhou2026beyondmaxtokens, sun2026llmagentsknowtools,
everton2026marrvelmcp, wang2025mcpbenchbenchmarkingtoolusingllm,
fan2025mcptoolbenchlargescaleai, xiao2026reducingcostllmagents.

## Open items / possible next steps

- Confirm final page count in Overleaf (target: body 10–12 pages plus references).
  If over 12, first lever: move Table 3 (per-target, 20 rows) to Online Resources.
- Optional: add a parenthetical percentage to the "neither" column of Table 4 for
  consistency (currently counts only).
- Overleaf: upload paper/main.tex + paper/references.bib, compile pdfLaTeX + BibTeX
  (need ceurart.cls from the CEURART bundle / Overleaf template).
- Repo published at https://github.com/dbcls/mcp-return-value-study (main branch).
