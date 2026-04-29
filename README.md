# spyglass-skill-workspace

Eval sweep artifacts for [edeno/spyglass-skill](https://github.com/edeno/spyglass-skill). Each sweep measures whether the Spyglass skill helps an LLM agent answer Spyglass questions correctly — it dispatches each eval prompt twice (with the skill loaded vs without), grades both, and bundles the per-batch artifacts plus a cross-batch narrative under `runs/<run-id>/`. Run-agnostic analysis scripts live at the repo root under `tools/`.

This repo is intentionally separate from `spyglass-skill` because eval sweeps are large (~20 MB / ~1300 files per sweep) and scale with sweep count. Decoupling keeps the skill repo's clone size small while preserving full reproducibility for any sweep.

## Quick start

You're a new user. Pick what you want to do:

**See the round-C results.** Read [`runs/round-c-2026-04-28/summary/SUMMARY.md`](runs/round-c-2026-04-28/summary/SUMMARY.md) — it cites every headline number with links to the figures.

**Cite a number from round-C.** Open [`runs/round-c-2026-04-28/summary/cumulative_summary.json`](runs/round-c-2026-04-28/summary/cumulative_summary.json) for the headline ws/bs/Δ; [`batch_summary.csv`](runs/round-c-2026-04-28/summary/batch_summary.csv) for per-batch numbers; [`top_skill_wins.csv`](runs/round-c-2026-04-28/summary/top_skill_wins.csv) for per-eval Δ rankings; [`transcript_stats.json`](runs/round-c-2026-04-28/summary/transcript_stats.json) for tool-call totals and contamination counts.

**Regenerate figures from scratch.** Clone this repo and `spyglass-skill` as siblings (see "Sibling-clone convention" below), then:

```bash
uv run --with matplotlib --with numpy python3 tools/make_plots.py \
    --run runs/round-c-2026-04-28/
```

All 12 PNGs + 4 CSVs + 3 JSONs regenerate to `runs/round-c-2026-04-28/summary/`.

**Run a fresh sweep (round-D).** See "Adding a new sweep" below for the dispatch → snapshot → analyze → write-up flow.

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
└── snapshot_transcripts.py            captures a live Claude Code session's transcripts into a run

runs/
└── <run-id>/                          e.g., round-c-2026-04-28
    ├── run.json                       metadata: skill commit, source pin, headline numbers, batch labels
    ├── BATCHES.md                     per-batch ledger
    ├── findings.md                    cross-batch qualitative narrative
    ├── iteration-{1..N}/              per-batch artifacts
    │   ├── benchmark.json             per-batch aggregated stats
    │   ├── grader_summary.md          behavioral grader's report
    │   ├── codex_grade_summary.md     (optional) independent codex re-grade for this batch
    │   ├── .agent_map.json            agent_id -> (eval_dir, condition) map; consumed by tools/
    │   └── eval-NNN-<name>/
    │       ├── with_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    │       └── without_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    └── summary/                       analysis bundle (outputs only — no scripts)
        ├── SUMMARY.md                 final analysis + recommendations
        ├── 01..12_*.png               12 figures
        ├── category_breakdown.csv     per stage/tier/difficulty: ws/bs/Δ pass counts
        ├── batch_summary.csv          per-batch row covering BATCHES.md's plan table
        ├── top_skill_wins.csv         per-eval Δ-pp ranking, sorted desc
        ├── cumulative_summary.json    headline ws/bs/Δ across all batches
        ├── ref_utilization.json       per-reference open count (transcript-level)
        ├── script_utilization.json    per-bundled-script execution + source-read counts
        ├── transcript_stats.json      tool-call totals, baseline contamination, SKILL.md activation
        └── transcripts_snapshot/      *.jsonl per-subagent transcripts (~14 MB per sweep)
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
# Regenerate the 12 figures + CSV + JSONs for round-C (only matplotlib + numpy needed)
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

End-to-end flow for round-D / round-E / etc:

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

   Writes 12 PNGs + 4 CSVs + 3 JSONs to `runs/<run-id>/summary/`. Idempotent — re-running produces byte-identical outputs.
4. **Author narrative.** Write `BATCHES.md` (per-batch ledger), `findings.md` (cross-batch narrative), and `summary/SUMMARY.md` (analysis + recommendations). Cite numbers directly from the JSON/CSV exports rather than reading them off the figures — every headline number in round-c's SUMMARY.md is in `summary/cumulative_summary.json`, `batch_summary.csv`, `top_skill_wins.csv`, or `transcript_stats.json`.
5. **Fill `run.json`.** Include `skill_commit_at_sweep_start/end`, `spyglass_src_commit`, `n_evals_run`, `headline_results`, contamination notes, and the optional `batches` block for per-batch figure labels.
6. **Commit and push.**

## Why a separate repo

The round-C 130-eval sweep added ~21 MB to spyglass-skill's git history, doubling its clone size. With expected sweeps every ~3 months (round-D in May, round-E in August, etc.), the skill repo's clone size would grow without bound, making it unpleasant to clone for users who only want the skill.

Decoupling to this repo means:
- `spyglass-skill` stays small for users.
- Reproducibility is preserved here — every sweep's full data is available for re-analysis.
- Re-running `make_plots.py` against any sweep regenerates all figures with no upstream dependency on a specific spyglass-skill commit (the metadata in `run.json` records what was measured).

The trade-off is slightly more friction when running fresh sweeps: orchestrators clone both repos as siblings. The dispatch templates in `spyglass-skill` document this.
