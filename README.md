# spyglass-skill-workspace

Eval sweep artifacts for [edeno/spyglass-skill](https://github.com/edeno/spyglass-skill). Each sweep is a self-contained per-run directory under `runs/<run-id>/` with narrative, per-batch grading, the analysis bundle, and (for sweeps that ran on Claude Code) a transcript snapshot.

This repo is intentionally separate from `spyglass-skill` because eval sweeps are large (~20 MB / ~1300 files per sweep) and scale with sweep count. Decoupling keeps the skill repo's clone size small while preserving full reproducibility for any sweep.

## Layout

```
runs/
└── <run-id>/                          e.g., round-c-2026-04-28
    ├── run.json                       metadata: skill commit, source pin, headline numbers
    ├── BATCHES.md                     per-batch ledger
    ├── findings.md                    cross-batch qualitative narrative
    ├── iteration-{1..N}/              per-batch artifacts
    │   ├── benchmark.json             per-batch aggregated stats
    │   ├── grader_summary.md          behavioral grader's report
    │   └── eval-NNN-<name>/
    │       ├── with_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    │       └── without_skill/{eval_metadata.json, grading.json, timing.json, outputs/response.md}
    └── summary/                       analysis bundle
        ├── SUMMARY.md                 final analysis + recommendations
        ├── 01..12_*.png               12 figures
        ├── category_breakdown.csv
        ├── ref_utilization.json
        ├── script_utilization.json
        ├── make_plots.py              regenerates all figures
        ├── snapshot_transcripts.py    refreshes transcripts_snapshot from a live session
        └── transcripts_snapshot/      *.jsonl per-subagent transcripts (~14 MB per sweep)
```

## Sibling-clone convention

The analysis scripts (`make_plots.py`, `snapshot_transcripts.py`) read metadata from the **spyglass-skill** repo (specifically `skills/spyglass/evals/evals.json` for category breakdowns, and the encoded skill-repo path for transcript-tasks-dir auto-detection). The default convention is that this repo and `spyglass-skill` are cloned as siblings:

```
~/Documents/GitHub/
├── spyglass-skill/                ← the skill itself
└── spyglass-skill-workspace/      ← this repo
```

When that's the case, the scripts work without arguments. Otherwise, override via:

- `--skill-root /path/to/spyglass-skill` CLI flag, or
- `SPYGLASS_SKILL=/path/to/spyglass-skill` environment variable

Resolution order: `--skill-root` → `SPYGLASS_SKILL` → sibling-clone default → legacy in-tree walk-up (only relevant for sweeps run before this repo was extracted from spyglass-skill).

## Running the analysis scripts

```bash
cd runs/round-c-2026-04-28/summary

# Regenerate the 12 figures + CSV + JSONs (only matplotlib + numpy needed)
uv run --with matplotlib --with numpy python3 make_plots.py

# Refresh transcripts_snapshot from a live Claude Code session
# (only useful if the live session's tasks dir still exists)
python3 snapshot_transcripts.py

# Override skill-root if needed
python3 make_plots.py --skill-root /custom/path/to/spyglass-skill
```

`make_plots.py` is idempotent — re-running produces byte-identical PNGs (modulo matplotlib non-determinism on some systems).

## Per-run metadata

Each `runs/<run-id>/run.json` carries:

- `skill_commit_at_sweep_start` / `skill_commit_at_sweep_end` — which spyglass-skill commits were measured
- `spyglass_src_commit` — which upstream Spyglass commit the eval agents had access to (pinned for reproducibility)
- `n_evals_run`, `n_dispatches`, `n_transcripts_snapshotted`
- `headline_results` — full-pass and expectation pass rates, total tokens
- Notes on contamination caveats and data-integrity issues observed during the sweep

See `runs/round-c-2026-04-28/run.json` for the canonical example.

## Adding a new sweep

1. Create `runs/<run-id>/` with `iteration-N/` subdirs and dispatch the eval subagents (orchestrator-side; see `spyglass-skill`'s `skills/spyglass/evals/dispatch_prompts.md` for the canonical prompt templates).
2. After dispatch, run `snapshot_transcripts.py` while the live session's tasks dir still exists.
3. Run `make_plots.py` once benchmark.json is aggregated for each batch.
4. Write `BATCHES.md`, `findings.md`, `summary/SUMMARY.md` as the qualitative narrative.
5. Fill in `run.json` with the metadata.
6. Commit and push.

## Why a separate repo

The round-C 130-eval sweep added ~21 MB to spyglass-skill's git history, doubling its clone size. With expected sweeps every ~3 months (round-D in May, round-E in August, etc.), the skill repo's clone size would grow without bound, making it unpleasant to clone for users who only want the skill.

Decoupling to this repo means:
- `spyglass-skill` stays small for users.
- Reproducibility is preserved here — every sweep's full data is available for re-analysis.
- Re-running `make_plots.py` against any sweep regenerates all figures with no upstream dependency on a specific spyglass-skill commit (the metadata in `run.json` records what was measured).

The trade-off is slightly more friction when running fresh sweeps: orchestrators clone both repos as siblings. The dispatch templates in `spyglass-skill` document this.
