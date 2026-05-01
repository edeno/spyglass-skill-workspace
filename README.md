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

## Comparing two runs

`tools/compare_runs.py` produces an overlap-only diff between two runs and writes it under `runs/<new>/comparisons/<old>/`. The comparison is directional (`new` drifted from `old`), aggregates are computed only on evals present in both runs, and rubric drift / partial dispatches / missing transcripts flow through as explicit flags rather than silent imputations.

```bash
# Compare round-D against round-C (round-D is a 16-eval targeted rerun;
# the comparison auto-restricts to those 16 evals).
uv run python3 tools/compare_runs.py \
    --new runs/round-d-2026-04-30/ \
    --old runs/round-c-2026-04-28/

# Override the output dir (default is <new>/comparisons/<old-basename>/)
uv run python3 tools/compare_runs.py \
    --new runs/round-d-2026-04-30/ \
    --old runs/round-c-2026-04-28/ \
    --out /tmp/round-d-vs-c
```

Outputs are staged through `.data_tmp/` / `.figures_tmp/` / `.INDEX.tmp` and committed atomically alongside an `INDEX.md` and a `comparison_manifest.json`. A failed run leaves committed outputs untouched and removes the staging dirs.

**Each comparison output answers one question, mirroring the within-run `q*` pattern:**

| # | Question | Output |
| --- | --- | --- |
| — | Are we comparing the same evals? | [`overlap.json`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/overlap.json) |
| — | Did anything else drift between runs? | [`provenance_diff.json`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/provenance_diff.json) |
| — | What changed in the eval catalog? | [`catalog_diff.json`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/catalog_diff.json) |
| c01 | Did the headline improve? | [`c01_did_the_headline_improve.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c01_did_the_headline_improve.png) + [`headline_diff.json`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/headline_diff.json) |
| c02 | Did outcomes move per eval? | [`c02_did_outcomes_move_per_eval.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c02_did_outcomes_move_per_eval.png) + [`transitions.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/transitions.csv) |
| c03 | Where did evals move in the 2x2 outcome space? | [`c03_where_did_evals_move_in_2x2.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c03_where_did_evals_move_in_2x2.png) + [`outcome_2x2_shift.json`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/outcome_2x2_shift.json) |
| c04 | Did targeted edits explain the movement? | [`c04_did_targeted_edits_explain_movement.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c04_did_targeted_edits_explain_movement.png) + [`targeted_edits_summary.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/targeted_edits_summary.csv) |
| c05 | Did improvements cost more? | [`c05_did_improvements_cost_more.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c05_did_improvements_cost_more.png) + [`cost_shift.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/cost_shift.csv) |
| c06 | Did routing change? | [`c06_did_routing_change.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c06_did_routing_change.png) + [`routing_shift.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/routing_shift.csv) |
| c07 | Where does category-level pass rate drift? | [`c07_where_does_category_drift.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c07_where_does_category_drift.png) + [`category_shift.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/category_shift.csv) |
| c08 | Did the skill help differently between commits? | [`c08_did_skill_lift_change.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c08_did_skill_lift_change.png) + `headline_diff.json::skill_lift` |
| c09 | What is the root-cause distribution of regressions? | [`c09_regression_root_causes.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c09_regression_root_causes.png) + [`regression_root_cause.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/regression_root_cause.csv) |
| c10 | Is the eval set balanced for activation behavior, and is skill-lift the right sign per intent? | [`c10_is_intent_balanced.png`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/figures/c10_is_intent_balanced.png) + [`intent_balance.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/intent_balance.csv) |
| — | Which regressions need a manual review? | [`regression_review.csv`](runs/round-d-2026-04-30/comparisons/round-c-2026-04-28/data/regression_review.csv) |

**Recommended read order:**

1. **`INDEX.md`** for the auto-generated headline (n_overlap, skill commits, provenance drift count, subset-rerun caveat when applicable).
2. **`overlap.json`** to confirm what was actually compared. Guards against silently comparing full-old to subset-new.
3. **`provenance_diff.json`** — `causal_changed=true` is the attribution warning: when true, at least one of skill / src / model / harness / dispatch template / **grader (model / version / prompt / prompt_sha256)** / evals catalog differs and headline shifts cannot be cleanly attributed to skill changes alone. Grader drift is a real risk: a different judge model or a re-tuned grading prompt can move the headline without any skill change. `metadata_changed=true` flags label-only differences (round_label / skill_branch) and is informational only.
4. **`catalog_diff.json`** — required when `provenance_diff.json` reports the causal `evals_catalog_semantic_sha256` drifted: shows the actual added/removed evals plus per-eval field-level changes (name, eval_name, stage, tier, difficulty, prompt, expected_output, expectation count + text, assertions, files, expected refs/scripts). The `evals_snapshot_sha256_raw` field is kept as forensic metadata only — it flips on snapshot reformatting / source-path noise that doesn't change what was measured.
5. **`transitions.csv`** for per-eval moves. The `regression_interpretation` column separates `rubric_friction` (annotator-labeled) from `rubric_drift` (rubric counts changed) from `content_regression` (rubric stable). `ws_rubric_changed` / `bs_rubric_changed` are per-condition.
6. **`headline_diff.json`** for the overlap-only shift; the `skill_lift` block (rendered as `c08`) is the named answer to "did the skill help differently between commits?" — old skill-lift, new skill-lift, and the delta with 95% bootstrap CIs. McNemar p is `diagnostic_only` when `n_discordant < 25`.
7. **`c03` / `outcome_2x2_shift.json`** to see the 4-cell flow.
8. **`c04` / `targeted_edits_summary.csv`** for targeted reruns (when the new run declares `subset.edit_to_evals` in `run.json`). Many-to-many: one eval can appear under multiple edits.
9. **`c07` / `category_shift.csv`** for stage × tier drift — answers "did stage X improve while tier Y regressed?". Includes per-stage and per-tier rollups.
10. **`c05` / `cost_shift.csv`** for token + duration deltas split by `ws_transition`. Pair-completeness flags keep partial timing out of aggregates.
11. **`c06` / `routing_shift.csv`** for required-ref and required-script recall deltas (ws). Gated on transcripts being present in both runs.
12. **`c09` / `regression_root_cause.csv`** to triage the review queue: each ws regression *and* each rubric_friction stable_fail is bucketed into `rubric` / `routing` / `source_selection` / `tooling` / `synthesis` / `unknown`. `regression_root_cause_summary.json` reports `n_review_items` (queue size) plus the strict counts `n_ws_regressions` and `n_rubric_friction_stable_fail` so the rubric-friction contribution is never miscounted as content drift. The `synthesis` count is the headline "real reasoning regressions"; everything else has a more specific cause to chase.
13. **`c10` / `intent_balance.csv`** to check whether the eval set is balanced for activation *behavior* — declare an `intent` field per eval in evals.json (`should_trigger`, `should_not_trigger`, `near_miss_negative`, `destructive_operation_caution`, `setup`, `ingestion`, `debugging`, `custom_pipeline_authoring`). Restraint intents (`should_not_trigger`, `near_miss_negative`) test whether the skill stays quiet on off-topic prompts; on those, a *positive* skill-lift can mean over-eager rather than helpful. Catalog edits to `intent` are also caught by `catalog_diff.json`.
14. **`regression_review.csv`** as the per-eval drill-down: one row per ws regression or rubric_friction stable_fail, with paths to the old/new `response.md` and `grading.json` so reviewers can open both side-by-side.

**Key design choices** (verified against the round-D vs round-C overlap):

- **Aggregates use the overlap subset only.** Cumulative single-run JSON files are intentionally not consulted, so a 130-eval old run vs 16-eval new run reports `ws_full_pass` denominators of 16, not 130.
- **Rubric drift is detected per-eval and split per-condition.** ws expectation deltas are flagged `rubric_sensitive` independently from bs deltas, so a baseline-only rubric change does not contaminate the ws interpretation.
- **Missing dispatches flow through with explicit flags.** `_flatten_per_eval` uses the union of ws and bs eval ids per run; a partial dispatch produces `outcome="missing"` and `transition=None` rather than imputed-fail. headline_diff's `n_with_data` denominators report the actual cell count.
- **Token coverage labels available-timing-only deltas.** When any overlap eval has missing `timing.json` on either side, headline_diff's `tokens.<cond>.delta_total` is `null` and the note reads `available-timing-only`. The c05 figure tracks per-bucket excluded counts and labels fully-excluded buckets in a footer rather than rendering them as "no evals".
- **Routing definitions are precise.** `required_*_recall = required_opened / max(required_total, 1)`; `unexpected_*_count` is opens to refs / scripts not in `required ∪ optional`. Scripts count only when executed via Bash, not source-read.

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

0. **Pre-flight: dispatch a context probe** (cheap insurance, ~30s, ~$0.01). Before launching the full sweep, dispatch one no-op subagent that asks *"what's in your initial context?"* — list any auto-loaded files (CLAUDE.md, MEMORY.md, project memory) and cross-reference against the sweep's contamination model. Round-d's probe surfaced that `MEMORY.md` auto-loads in subagents and contains references to "graded eval sweeps" — meta-context that biases bs answers. The fix landed in `dispatch_prompts.md` as the auto-memory prohibition; without the probe, the contamination would have silently muddied 32 dispatches. Run this probe whenever the dispatch templates change OR auto-memory contents shift.

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
4. **Post-run rubric audit (NEW, gated).** Read each grader's `eval_feedback` block in `iteration-N/eval-NNN-*/<condition>/grading.json` and the per-eval expectations breakdown. Round-d found ~50% of evals had at least one rubric-friction pattern that produced false-negative grading; those patterns recur and need targeted retirement, not headline retroactive blame. See [Post-run rubric audit](#post-run-rubric-audit) below for the procedure.

5. **Author narrative.** Write `BATCHES.md` (per-batch ledger), `findings.md` (cross-batch narrative), and `summary/SUMMARY.md` (analysis + recommendations). **Cite numbers via path-to-CSV/JSON, not paraphrase.** Every claim of the form *"X happened on N runs"* should cite the specific summary CSV/JSON that proves it (e.g., *"3/16 ws runs invoked code_graph.py per [`script_utilization.json`](summary/data/script_utilization.json)"* — not *"agents reliably invoked the script"*). Paraphrase drifts; path citations don't. This is the discipline that prevents the round-d-style *"tool invocations confirmed in all four"* error that contradicted the underlying CSV. Every headline number is in `summary/data/cumulative_summary.json`, `batch_summary.csv`, `top_skill_wins.csv`, `routing_diagnosis.csv`, `script_utilization.json`, or `transcript_stats.json`.

6. **External reviewer pass.** Hand `findings.md`, the per-eval `grading.json` files, and any post-run rubric edits to an external reviewer (a fresh Claude session, a teammate, or both). The orchestrator self-review systematically misses three things round-d caught only via external review: derived `expectations` arrays not regenerated after `assertions` edits; stale comments in scripts touched during the run; and rubric-friction in evals beyond the obvious ws-worse-than-bs cases. Address the reviewer's findings before commit.

7. **Fill `run.json`.** Include `skill_commit_at_sweep_start/end`, `spyglass_src_commit`, `n_evals_run`, `headline_results`, contamination notes, and the optional `batches` block for per-batch figure labels. Document any post-run `evals.json` changes in `skill_commit_note` (round-c precedent: *"evals.json received in-flight substring relaxations (commits ...); for 'what skill version was being measured' interpret as the X state."*).

8. **Commit and push.**

## Post-run rubric audit

After every graded sweep, before authoring `findings.md` or claiming any headline, work through this checklist on each `iteration-N/eval-NNN-*/<condition>/grading.json`:

1. **Read every grader's `eval_feedback.suggestions` block.** Graders flag rubric-friction unsolicited; the suggestions are the load-bearing signal. Cross-reference against [skills/spyglass/evals/README.md § Anti-patterns to avoid in eval authoring](https://github.com/edeno/spyglass-skill/blob/master/skills/spyglass/evals/README.md) for the canonical shapes.
2. **Identify the three known rubric-friction shapes** (each documented in evals/README.md):
   - Literal reference-filename substrings (`required_substrings: ["destructive_operations.md"]`) — fail responses that correctly applied the pattern without typing the filename.
   - Compound assertions bundling unrelated content (one `behavioral_checks` string asking for two independent claims joined by `and`) — half-credit responses lose the whole point and the signal becomes noisy.
   - Forbidden-substrings firing on legitimate disambiguation mentions (`forbidden_substrings: ["SpikeSortingV1"]` fires on responses that mention the trap pedagogically).
3. **Apply targeted rubric corrections** by editing `skills/spyglass/evals/evals.json`. Remove brittle substrings, split compound assertions, replace forbidden-substring + content-recommendation hybrids with recommend-vs-show behavioral checks.
4. **Regenerate derived expectations**: `python3 skills/spyglass/evals/scripts/flatten_expectations.py`. The skill-side validator (`./skills/spyglass/scripts/validate_all.sh`) gates on `flatten_expectations.py --check`.
5. **Document the post-run corrections** in this run's `findings.md` as an explicit "Post-run rubric corrections" section. Each correction names the eval, the friction pattern it retired, and the substantive content the response delivered (rubric-friction ≠ content failure; the writeup should make this distinction explicit).
6. **Headline numbers stay measured against the OLD rubric.** The corrections take effect on the *next* sweep. The current sweep's `findings.md` should note: *"Re-grading the existing N responses against the corrected rubric would likely raise ws scores on evals X / Y / Z."*
7. **Don't apply rubric corrections that change what the eval tests** — only retire shapes that produce false negatives. If a substring requirement is a real test (the eval IS asking for that exact identifier), keep it. If a compound is genuinely conjunctive (the eval requires BOTH halves to be valid), keep it.

Empirical record: round-d found 8/16 evals (50%) had rubric-friction. The post-run audit identified 18 corrections across 8 evals; without it, the next sweep would have continued under-counting skill effectiveness on those evals. See [`runs/round-d-2026-04-30/findings.md`](runs/round-d-2026-04-30/findings.md) § "Post-run rubric corrections" for the round-d worked example.

## Why a separate repo

The round-C 130-eval sweep added ~21 MB to spyglass-skill's git history, doubling its clone size. With recurring sweeps every few months, the skill repo's clone size would grow without bound, making it unpleasant to clone for users who only want the skill.

Decoupling to this repo means:
- `spyglass-skill` stays small for users.
- Reproducibility is preserved here — every sweep's full data is available for re-analysis.
- Re-running `make_plots.py` against any sweep regenerates all figures with no upstream dependency on a specific spyglass-skill commit (the metadata in `run.json` records what was measured).

The trade-off is slightly more friction when running fresh sweeps: orchestrators clone both repos as siblings. The dispatch templates in `spyglass-skill` document this.
