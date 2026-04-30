# spyglass-skill-workspace

Eval sweep artifacts for [edeno/spyglass-skill](https://github.com/edeno/spyglass-skill). Each sweep measures whether the Spyglass skill helps an LLM agent answer Spyglass questions correctly — it dispatches each eval prompt twice (with the skill loaded vs without), grades both, and bundles the per-batch artifacts plus a cross-batch narrative under `runs/<run-id>/`. Run-agnostic analysis scripts live at the repo root under `tools/`.

This repo is intentionally separate from `spyglass-skill` because eval sweeps are large (~20 MB / ~1300 files per sweep) and scale with sweep count. Decoupling keeps the skill repo's clone size small while preserving full reproducibility for any sweep.

## Quick start

You're a new user. Pick what you want to do:

**See the round-C results.** Read [`runs/round-c-2026-04-28/summary/SUMMARY.md`](runs/round-c-2026-04-28/summary/SUMMARY.md) — it cites every headline number with links to the figures.

**Cite a number from round-C.** Open [`cumulative_summary.json`](runs/round-c-2026-04-28/summary/cumulative_summary.json) for the headline ws/bs/Δ + McNemar p-value + outcome cross-tab; [`batch_summary.csv`](runs/round-c-2026-04-28/summary/batch_summary.csv) for per-batch numbers; [`stage_x_difficulty.csv`](runs/round-c-2026-04-28/summary/stage_x_difficulty.csv) for cells of plot 08's heatmap; [`top_skill_wins.csv`](runs/round-c-2026-04-28/summary/top_skill_wins.csv) for per-eval Δ rankings; [`per_eval_routing.csv`](runs/round-c-2026-04-28/summary/per_eval_routing.csv) for "what did the agent reach for on this eval"; [`transcript_stats.json`](runs/round-c-2026-04-28/summary/transcript_stats.json) for tool-call totals, error counts, source-assistance, contamination.

**Decide what to change next.** Start with [`fix_priority.csv`](runs/round-c-2026-04-28/summary/fix_priority.csv) and [`22_fix_priority_actions.png`](runs/round-c-2026-04-28/summary/22_fix_priority_actions.png) for the combined next-action view, [`headroom_evals.csv`](runs/round-c-2026-04-28/summary/headroom_evals.csv) for failed/weak evals, [`outcome_by_category.csv`](runs/round-c-2026-04-28/summary/outcome_by_category.csv) for where the skill uniquely helps vs where everything still fails, and [`cost_effectiveness_per_eval.csv`](runs/round-c-2026-04-28/summary/cost_effectiveness_per_eval.csv) / [`cost_by_outcome.csv`](runs/round-c-2026-04-28/summary/cost_by_outcome.csv) for token spend. Use [`routing_diagnosis.csv`](runs/round-c-2026-04-28/summary/routing_diagnosis.csv) as the canonical routing-vs-synthesis split for ws failures. [`baseline_source_split.json`](runs/round-c-2026-04-28/summary/baseline_source_split.json) tests whether the skill's value is source-delivery or routing/workflow. [`eval_coverage.csv`](runs/round-c-2026-04-28/summary/eval_coverage.csv) flags under-tested stage × tier cells.

**Annotate failure modes by hand.** [`failure_taxonomy.csv`](runs/round-c-2026-04-28/summary/failure_taxonomy.csv) is auto-generated as a stub with one row per ws-failed eval. Fill in the `failure_type` column (suggested values: `wrong_factual`, `omitted_step`, `over_skeptical`, `wrong_tool`, `right_ref_no_verify`, `rubric_friction`, `eval_issue`) and re-run `make_plots.py` — plot 18 will render the distribution. Existing annotations are preserved across re-runs.

**Annotate expected references per eval.** Add an `expected_refs` block per eval in `skills/spyglass/evals/evals.json`:

```json
{"id": 100, "expected_refs": {"required": ["decoding_pipeline.md"], "optional": ["common_tables.md"], "distractor": ["spyglassmixin_methods.md"]}}
```

`make_plots.py` will then render `reference_expected_used.csv` plus plot 19 — separating routing failures (expected ref not opened) from reference weakness (opened but answer still failed) from overuse (distractor opened) from eval mismatch (expected ref not needed). Skipped if no eval has the field.

**Annotate expected references/scripts for confusion matrices.** The same
`required` / `optional` / `distractor` shape also supports bundled-script
annotations:

```json
{"id": 29, "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": ["db_graph.py"]}}
```

`make_plots.py` renders `reference_call_confusion.csv`,
`script_call_confusion.csv`, and plots 20/21 when annotations exist. The unit
is a with_skill eval-resource pair: `required` entries are positives,
`distractor` entries and unlabeled resources are negatives, and `optional`
entries are tracked but neutral. Scripts count as "called" only when executed
via Bash, not merely source-read.

**Read outputs by decision family.** [`summary_manifest.json`](runs/round-c-2026-04-28/summary/summary_manifest.json)
labels each output as `primary`, `secondary`, or `appendix`. Treat headline,
outcome-by-category, cost-effectiveness, routing, and fix-priority outputs as
primary evidence. Treat batch plots as run-health diagnostics, difficulty and
coverage plots as secondary structure, and raw reference/script utilization as
appendix/debug evidence. Reference/script routing metrics measure whether the
agent reached for the expected resource; they do not replace grading.

**Regenerate figures from scratch.** Clone this repo and `spyglass-skill` as siblings (see "Sibling-clone convention" below), then:

```bash
uv run --with matplotlib --with numpy python3 tools/make_plots.py \
    --run runs/round-c-2026-04-28/
```

All summary PNG/CSV/JSON outputs regenerate to `runs/round-c-2026-04-28/summary/`.
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
└── _smoketest.py                      synthetic regression smoke test for tools/

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
        ├── 01..22_*.png               summary figures (plot 18 is a placeholder until annotated)
        ├── category_breakdown.csv     per stage/tier/difficulty: ws/bs/Δ pass counts
        ├── batch_summary.csv          per-batch row: full-eval, expectation, behavioral, tokens, duration
        ├── stage_x_difficulty.csv     flat plot-08 matrix: ws/bs/Δ per (stage, difficulty) cell
        ├── top_skill_wins.csv         per-eval Δ-pp ranking, sorted desc
        ├── per_eval_routing.csv       per-eval × per-condition: pass, refs opened, scripts run, errors
        ├── reference_effectiveness.csv  per-reference: loads, pass-rate-when-loaded, failed-eval samples
        ├── cost_effectiveness_per_eval.csv  per-eval: extra ws tokens vs expectation Δ
        ├── outcome_by_category.csv    per stage/tier outcome cross-tab (both/ws-only/bs-only/none)
        ├── eval_coverage.csv          stage × tier eval-count matrix
        ├── failure_taxonomy.csv       auto-stub of ws-failed evals; maintainer fills failure_type
        ├── reference_expected_used.csv  optional: rendered if evals.json has `expected_refs` annotations
        ├── reference_call_confusion.csv optional: expected-vs-called matrix if `expected_refs` exists
        ├── script_call_confusion.csv  optional: expected-vs-called matrix if `expected_scripts` exists
        ├── reference_expected_by_eval.csv optional: per-eval expected-vs-opened reference table
        ├── script_expected_by_eval.csv optional: per-eval expected-vs-executed script table
        ├── routing_diagnosis.csv       optional: canonical ws-failure routing-vs-synthesis diagnosis
        ├── cost_by_outcome.csv        extra ws tokens split by both-pass / skill-only / bs-only / both-fail
        ├── skip_gate_candidates.csv   high-cost categories where baseline already performs strongly
        ├── ws_regressions.csv         full-pass or expectation-level regressions vs baseline
        ├── fix_priority.csv           combined next-action table: outcome, cost, routing misses
        ├── 22_fix_priority_actions.png likely-action distribution from fix_priority.csv
        ├── summary_manifest.json      output family/priority/purpose index
        ├── cumulative_summary.json    headline ws/bs/Δ + outcome cross-tab + McNemar p-value
        ├── baseline_source_split.json 3-way split: bs-no-source / bs-source / ws full-pass rates
        ├── ref_utilization.json       per-reference open count (transcript-level)
        ├── script_utilization.json    per-bundled-script execution + source-read counts
        └── transcript_stats.json      tool-call totals (incl errors), source-assistance, SKILL.md activation
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
# Regenerate all figures + CSV + JSONs for round-C (only matplotlib + numpy needed)
uv run --with matplotlib --with numpy python3 tools/make_plots.py \
    --run runs/round-c-2026-04-28/

# Same for any other run
uv run --with matplotlib --with numpy python3 tools/make_plots.py \
    --run runs/round-d-2026-07-XX/

# Refresh transcripts_snapshot from a live Claude Code session
# (only useful if the live session's tasks dir still exists)
python3 tools/snapshot_transcripts.py --run runs/<run-id>/

# Override skill-root if the sibling-clone default doesn't apply
python3 tools/make_plots.py --run runs/<run-id>/ \
    --skill-root /custom/path/to/spyglass-skill

# Synthetic tools smoke test
uv run --with matplotlib --with numpy python3 tools/_smoketest.py
```

`make_plots.py` is idempotent — re-running produces byte-identical PNGs (modulo matplotlib non-determinism on some systems).

### Per-run configuration

`runs/<run-id>/run.json` carries an optional `batches` block consumed by `make_plots.py` for figure labels. The script auto-discovers batch IDs from `iteration-N/` directories; the `batches` block lets each run customize its labels:

```json
"batches": {
  "1": {"label": "B1\nkey hygiene\n+ merge"},
  "2": {"label": "B2\nhallucination"}
}
```

Missing entries fall back to `f"B{i}"`, so a fresh sweep can be plotted before labels are authored.

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
   python3 tools/snapshot_transcripts.py --run runs/<run-id>/
   ```

   The harness wipes `/private/tmp/claude-<uid>/<workspace-hash>/` on session change or reboot, and there is **no recovery path** afterward. The script reports expected vs found transcript counts and warns loudly if any mapped agent IDs are missing on disk. If you forget this step, the per-reference and per-script utilization plots cannot be reproduced — you'd need to re-dispatch.

3. **Generate figures and exports.**

   ```bash
   uv run --with matplotlib --with numpy python3 tools/make_plots.py \
       --run runs/<run-id>/
   ```

   Writes the generated PNG/CSV/JSON/Markdown summary bundle to `runs/<run-id>/summary/`. Idempotent — re-running produces byte-identical outputs.
4. **Author narrative.** Write `BATCHES.md` (per-batch ledger), `findings.md` (cross-batch narrative), and `summary/SUMMARY.md` (analysis + recommendations). Cite numbers directly from the JSON/CSV exports rather than reading them off the figures — every headline number in round-c's SUMMARY.md is in `summary/cumulative_summary.json`, `batch_summary.csv`, `top_skill_wins.csv`, or `transcript_stats.json`.
5. **Fill `run.json`.** Include `skill_commit_at_sweep_start/end`, `spyglass_src_commit`, `n_evals_run`, `headline_results`, contamination notes, and the optional `batches` block for per-batch figure labels.
6. **Commit and push.**

## Why a separate repo

The round-C 130-eval sweep added ~21 MB to spyglass-skill's git history, doubling its clone size. With recurring sweeps every few months, the skill repo's clone size would grow without bound, making it unpleasant to clone for users who only want the skill.

Decoupling to this repo means:
- `spyglass-skill` stays small for users.
- Reproducibility is preserved here — every sweep's full data is available for re-analysis.
- Re-running `make_plots.py` against any sweep regenerates all figures with no upstream dependency on a specific spyglass-skill commit (the metadata in `run.json` records what was measured).

The trade-off is slightly more friction when running fresh sweeps: orchestrators clone both repos as siblings. The dispatch templates in `spyglass-skill` document this.
