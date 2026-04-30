# spyglass-skill-workspace

Eval sweep artifacts for [edeno/spyglass-skill](https://github.com/edeno/spyglass-skill). Each sweep measures whether the Spyglass skill helps an LLM agent answer Spyglass questions correctly — it dispatches each eval prompt twice (with the skill loaded vs without), grades both, and bundles the per-batch artifacts plus a cross-batch narrative under `runs/<run-id>/`. Run-agnostic analysis scripts live at the repo root under `tools/`.

This repo is intentionally separate from `spyglass-skill` because eval sweeps are large (~20 MB / ~1300 files per sweep) and scale with sweep count. Decoupling keeps the skill repo's clone size small while preserving full reproducibility for any sweep.

## Quick start

You're a new user. Pick what you want to do:

**See the round-C results.** Read [`runs/round-c-2026-04-28/summary/SUMMARY.md`](runs/round-c-2026-04-28/summary/SUMMARY.md) — it cites every headline number with links to the figures.

**Cite a number from round-C.** Open [`cumulative_summary.json`](runs/round-c-2026-04-28/summary/data/cumulative_summary.json) for the headline ws/bs/Δ + McNemar p-value + outcome cross-tab; [`batch_summary.csv`](runs/round-c-2026-04-28/summary/data/batch_summary.csv) for per-batch numbers; [`stage_x_difficulty.csv`](runs/round-c-2026-04-28/summary/data/stage_x_difficulty.csv) for cells of the stage x difficulty heatmap; [`top_skill_wins.csv`](runs/round-c-2026-04-28/summary/data/top_skill_wins.csv) for per-eval Δ rankings; [`per_eval_routing.csv`](runs/round-c-2026-04-28/summary/data/per_eval_routing.csv) for "what did the agent reach for on this eval"; [`transcript_stats.json`](runs/round-c-2026-04-28/summary/data/transcript_stats.json) for tool-call totals, error counts, source-assistance, contamination.

**Decide what to change next.** Start with [`fix_priority.csv`](runs/round-c-2026-04-28/summary/data/fix_priority.csv) and [`q08_what_should_we_fix_next.png`](runs/round-c-2026-04-28/summary/figures/q08_what_should_we_fix_next.png) for the combined next-action view, [`headroom_evals.csv`](runs/round-c-2026-04-28/summary/data/headroom_evals.csv) for failed/weak evals, [`outcome_by_category.csv`](runs/round-c-2026-04-28/summary/data/outcome_by_category.csv) for where the skill uniquely helps vs where everything still fails, and [`cost_effectiveness_per_eval.csv`](runs/round-c-2026-04-28/summary/data/cost_effectiveness_per_eval.csv) / [`cost_by_outcome.csv`](runs/round-c-2026-04-28/summary/data/cost_by_outcome.csv) for token spend. Use [`routing_diagnosis.csv`](runs/round-c-2026-04-28/summary/data/routing_diagnosis.csv) as the canonical routing-vs-synthesis split for ws failures. [`baseline_source_split.json`](runs/round-c-2026-04-28/summary/data/baseline_source_split.json) tests whether the skill's value is source-delivery or routing/workflow. [`eval_coverage.csv`](runs/round-c-2026-04-28/summary/data/eval_coverage.csv) flags under-tested stage × tier cells.

**Annotate failure modes by hand.** [`failure_taxonomy.csv`](runs/round-c-2026-04-28/summary/data/failure_taxonomy.csv) is auto-generated as a stub with one row per ws-failed eval. Fill in the `failure_type` column (suggested values: `wrong_factual`, `omitted_step`, `over_skeptical`, `wrong_tool`, `right_ref_no_verify`, `rubric_friction`, `eval_issue`) and re-run `make_plots.py` — `appendix_failure_taxonomy_placeholder.png` will render the distribution. Existing annotations are preserved across re-runs.

**Annotate expected references per eval.** Add an `expected_refs` block per eval in `skills/spyglass/evals/evals.json`:

```json
{"id": 100, "expected_refs": {"required": ["decoding_pipeline.md"], "optional": ["common_tables.md"], "distractor": ["spyglassmixin_methods.md"]}}
```

`make_plots.py` will then render `reference_expected_used.csv` plus `q09_how_well_are_expected_references_used.png` — separating routing failures (expected ref not opened) from reference weakness (opened but answer still failed) from overuse (distractor opened) from eval mismatch (expected ref not needed). Skipped if no eval has the field.

**Annotate expected references/scripts for confusion matrices.** The same
`required` / `optional` / `distractor` shape also supports bundled-script
annotations:

```json
{"id": 29, "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": ["db_graph.py"]}}
```

`make_plots.py` renders `data/reference_call_confusion.csv`,
`data/script_call_confusion.csv`, and `q06_are_reference_routes_working.png` / `q07_are_script_routes_working.png` when annotations exist. The unit
is a with_skill eval-resource pair: `required` entries are positives,
`distractor` entries and unlabeled resources are negatives, and `optional`
entries are tracked but neutral. Scripts count as "called" only when executed
via Bash, not merely source-read.

**Read outputs by decision family.** [`summary_manifest.json`](runs/round-c-2026-04-28/summary/data/summary_manifest.json)
labels each output as `primary`, `secondary`, or `appendix`, and tags figures as
`presentation`, `analyst`, or `appendix`. Treat headline,
outcome-by-category, cost-effectiveness, routing, and fix-priority outputs as
primary evidence. Treat batch plots as run-health diagnostics, difficulty and
coverage plots as secondary structure, and raw reference/script utilization as
appendix/debug evidence. Reference/script routing metrics measure whether the
agent reached for the expected resource; they do not replace grading.

**Regenerate figures from scratch.** Clone this repo and `spyglass-skill` as siblings (see "Sibling-clone convention" below), then:

```bash
uv run python3 tools/make_plots.py \
    --run runs/round-c-2026-04-28/
```

All summary PNG outputs regenerate to `runs/round-c-2026-04-28/summary/figures/`; CSV/JSON outputs regenerate to `runs/round-c-2026-04-28/summary/data/`.
Start with [`summary/INDEX.md`](runs/round-c-2026-04-28/summary/INDEX.md)
when browsing the generated files directly.

**Run a fresh sweep.** See "Adding a new sweep" below for the dispatch → snapshot → analyze → write-up flow.

## Glossary

Terms used throughout SUMMARY.md / BATCHES.md / findings.md:

- **with_skill / ws** vs **without_skill / bs (baseline)** — the two conditions each eval is dispatched under.
- **eval** — a single prompt + grading rubric in `skills/spyglass/evals/evals.json`.
- **batch / iteration** — a stratified group of evals dispatched together (round-C had 7 batches of ~14-30 evals each).
- **expectation** — one rubric criterion that an eval's response must satisfy. Each eval has 5-15 expectations.
- **behavioral check** — an LLM-judge expectation (vs an exact-substring expectation).
- **full pass / evals_full_pass** — eval where ALL expectations passed.
- **expectation pass rate** — fraction of individual expectations that passed (more granular than full pass).
- **stage / tier / difficulty** — categorical metadata on each eval (`evals.json`); used to slice the results.
- **transcript** — JSONL log of a single subagent's tool calls during one dispatch. Snapshotted from the live Claude Code session that ran the sweep.
- **agent_map** — `iteration-N/.agent_map.json` mapping subagent IDs to their (eval_dir, condition); lets the analysis scripts join transcripts back to evals.

## Layout

```
tools/                                 run-agnostic analysis scripts
├── make_plots.py                      regenerates all figures for a given run
├── snapshot_transcripts.py            captures a live Claude Code session's transcripts into a run
└── tests/smoke.py                     synthetic regression smoke test for tools/

runs/
└── <run-id>/                          e.g., round-c-2026-04-28
    ├── run.json                       metadata: skill commit, source pin, headline numbers, batch labels
    ├── BATCHES.md                     per-batch ledger
    ├── findings.md                    cross-batch qualitative narrative
    ├── transcripts_snapshot/          raw *.jsonl per-subagent transcripts (~14 MB per sweep)
    ├── iteration-{1..N}/              per-batch artifacts
    │   ├── benchmark.json             per-batch aggregated stats
    │   ├── grader_summary.md          behavioral grader's report
    │   ├── codex_grade_summary.md     (optional) independent codex re-grade for this batch
    │   ├── .agent_map.json            agent_id -> (eval_dir, condition) map; consumed by tools/
    │   └── eval-NNN-<name>/
    │       ├── with_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    │       └── without_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    └── summary/                       derived analysis bundle (outputs only — no scripts or raw data)
        ├── INDEX.md                   generated guide to summary outputs by priority
        ├── SUMMARY.md                 final analysis + recommendations
        ├── figures/                   generated PNG figures
        │   └── q*.png / appendix_*.png question-first and appendix figures
        └── data/                      generated CSV/JSON data behind the figures and narrative
            ├── summary_manifest.json  output family/priority/purpose index
            ├── cumulative_summary.json headline ws/bs/Δ + outcome cross-tab + McNemar p-value
            ├── batch_summary.csv      per-batch full-eval, expectation, behavioral, token, duration metrics
            ├── fix_priority.csv       combined next-action table: outcome, cost, routing misses
            ├── routing_diagnosis.csv  canonical ws-failure routing-vs-synthesis diagnosis
            ├── reference_* / script_* expected-vs-called and utilization tables
            ├── cost_* / outcome_*     cost and outcome-split tables
            └── transcript_stats.json  tool-call totals, source-assistance, SKILL.md activation
```

## Sibling-clone convention

The analysis scripts read metadata from the **spyglass-skill** repo (`skills/spyglass/evals/evals.json` for category breakdowns; the encoded skill-repo path is used to auto-detect the live session's `tasks/` directory). The default convention is that this repo and `spyglass-skill` are cloned as siblings:

```
~/Documents/GitHub/
├── spyglass-skill/                ← the skill itself
└── spyglass-skill-workspace/      ← this repo
```

When that's the case, the scripts work with just `--run`. Otherwise, override via:

- `--skill-root /path/to/spyglass-skill` CLI flag, or
- `SPYGLASS_SKILL=/path/to/spyglass-skill` environment variable

Resolution order: `--skill-root` → `SPYGLASS_SKILL` → sibling-clone default.

## Running the analysis scripts

The scripts in `tools/` are run-agnostic — pass `--run <run-dir>` to point them at a specific sweep:

```bash
# Regenerate all figures + CSV + JSONs for round-C
uv run python3 tools/make_plots.py \
    --run runs/round-c-2026-04-28/

# Same for any other run
uv run python3 tools/make_plots.py \
    --run runs/round-d-2026-07-XX/

# Refresh transcripts_snapshot from a live Claude Code session
# (only useful if the live session's tasks dir still exists)
uv run python3 tools/snapshot_transcripts.py --run runs/<run-id>/

# Override skill-root if the sibling-clone default doesn't apply
uv run python3 tools/make_plots.py --run runs/<run-id>/ \
    --skill-root /custom/path/to/spyglass-skill

# Synthetic tools smoke test
uv run python3 tools/tests/smoke.py
```

`make_plots.py` is idempotent for the CSV/JSON data outputs. PNG bytes can differ across matplotlib versions, so compare figures visually when the plotting environment changes.

### Per-run configuration

`runs/<run-id>/run.json` carries an optional `batches` block consumed by `make_plots.py` for figure labels. The script auto-discovers batch IDs from `iteration-N/` directories; the `batches` block lets each run customize its labels:

```json
"batches": {
  "1": {"label": "B1\nkey hygiene\n+ merge"},
  "2": {"label": "B2\nhallucination"}
}
```

Missing entries fall back to `f"B{i}"`, so a fresh sweep can be plotted before labels are authored.

### Partial sweeps

Partial sweeps are supported. `make_plots.py` discovers whichever
`iteration-N/` directories exist and counts only the evals present in their
`benchmark.json` files. This makes it safe to analyze a smaller dry run before a
full sweep, as long as each included eval has both `with_skill` and
`without_skill` grading outputs.

For reproducibility, copy the current eval catalog into the run before the first
analysis pass:

```bash
cp ../spyglass-skill/skills/spyglass/evals/evals.json runs/<run-id>/evals_snapshot.json
uv run python3 tools/make_plots.py --run runs/<run-id>/
```

If transcripts have not been snapshotted yet, transcript-derived plots and
routing/utilization tables are skipped or limited. Run
`uv run python3 tools/snapshot_transcripts.py --run runs/<run-id>/` while the
dispatch session is still active if you need reference/script utilization.

## Per-run metadata

Each `runs/<run-id>/run.json` carries:

- `skill_commit_at_sweep_start` / `skill_commit_at_sweep_end` — which spyglass-skill commits were measured
- `spyglass_src_commit` — which upstream Spyglass commit the eval agents had access to (pinned for reproducibility)
- `n_evals_run`, `n_dispatches`, `n_transcripts_snapshotted`
- `headline_results` — full-pass and expectation pass rates, total tokens
- Notes on contamination caveats and data-integrity issues observed during the sweep

See `runs/round-c-2026-04-28/run.json` for the canonical example.

## Adding a new sweep

End-to-end flow for each new sweep:

1. **Dispatch.** Create `runs/<run-id>/iteration-N/` and dispatch the eval subagents from a Claude Code session rooted at the `spyglass-skill` repo (orchestrator-side; the canonical prompt templates live in `skills/spyglass/evals/dispatch_prompts.md`). Each batch produces:
   - `iteration-N/eval-NNN-<name>/{with_skill,without_skill}/{eval_metadata.json,grading.json,timing.json,outputs/response.md}`
   - `iteration-N/.agent_map.json` (orchestrator-written: agent_id → eval-dir/condition)
   - `iteration-N/benchmark.json` (per-batch aggregated stats)
   - `iteration-N/grader_summary.md`
2. **Snapshot transcripts — TIME-CRITICAL.** Run while the same Claude Code session is still active:

   ```bash
   uv run python3 tools/snapshot_transcripts.py --run runs/<run-id>/
   ```

   The harness wipes `/private/tmp/claude-<uid>/<workspace-hash>/` on session change or reboot, and there is **no recovery path** afterward. The script reports expected vs found transcript counts and warns loudly if any mapped agent IDs are missing on disk. If you forget this step, the per-reference and per-script utilization plots cannot be reproduced — you'd need to re-dispatch.

3. **Generate figures and exports.**

   ```bash
   uv run python3 tools/make_plots.py \
       --run runs/<run-id>/
   ```

   Writes the generated Markdown index to `runs/<run-id>/summary/`, PNG figures to `summary/figures/`, and CSV/JSON data to `summary/data/`. CSV/JSON outputs are idempotent; PNG bytes can differ across matplotlib versions.
4. **Author narrative.** Write `BATCHES.md` (per-batch ledger), `findings.md` (cross-batch narrative), and `summary/SUMMARY.md` (analysis + recommendations). Cite numbers directly from the JSON/CSV exports rather than reading them off the figures — every headline number in round-c's SUMMARY.md is in `summary/data/cumulative_summary.json`, `data/batch_summary.csv`, `data/top_skill_wins.csv`, or `data/transcript_stats.json`.
5. **Fill `run.json`.** Include `skill_commit_at_sweep_start/end`, `spyglass_src_commit`, `n_evals_run`, `headline_results`, contamination notes, and the optional `batches` block for per-batch figure labels.
6. **Commit and push.**

## Why a separate repo

The round-C 130-eval sweep added ~21 MB to spyglass-skill's git history, doubling its clone size. With recurring sweeps every few months, the skill repo's clone size would grow without bound, making it unpleasant to clone for users who only want the skill.

Decoupling to this repo means:
- `spyglass-skill` stays small for users.
- Reproducibility is preserved here — every sweep's full data is available for re-analysis.
- Re-running `make_plots.py` against any sweep regenerates all figures with no upstream dependency on a specific spyglass-skill commit (the metadata in `run.json` records what was measured).

The trade-off is slightly more friction when running fresh sweeps: orchestrators clone both repos as siblings. The dispatch templates in `spyglass-skill` document this.
