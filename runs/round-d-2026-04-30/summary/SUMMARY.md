# Round-D Summary

Round-D is a **targeted 16-eval rerun**, not a full replacement for round-C. It
exists to verify the phase-2 skill edits and the post-review rubric fixes on the
specific evals they were meant to affect. Treat the results as per-eval
verification evidence; use round-C for global skill-quality claims until the
next full run.

## Headline

On the 16 targeted evals, the skill improved the current-run result:

| Metric | with_skill | without_skill | Delta |
|---|---:|---:|---:|
| Full pass | 7/16 (43.75%) | 5/16 (31.25%) | +12.5 pp |
| Expectation pass rate | 144/164 (87.8%) | 126/164 (76.8%) | +11.0 pp |
| Total tokens | 904k | 614k | +290k |

Source: [`data/cumulative_summary.json`](data/cumulative_summary.json).

The outcome split was 4 both-pass, 3 skill-only, 1 baseline-only, and 8
both-fail. The exact McNemar p-value was 0.625 on only 4 discordant pairs, so it
is not a meaningful significance test for this narrow rerun.

## Compared With Round-C

On the same 16 evals, round-D moved in the right direction:

| Comparison metric | round-C subset | round-D | Delta |
|---|---:|---:|---:|
| with_skill full pass | 3/16 (18.75%) | 7/16 (43.75%) | +25.0 pp |
| without_skill full pass | 4/16 (25.0%) | 5/16 (31.25%) | +6.25 pp |
| skill lift | -6.25 pp | +12.5 pp | +18.75 pp |

Source: [`../comparisons/round-c-2026-04-28/data/headline_diff.json`](../comparisons/round-c-2026-04-28/data/headline_diff.json).

The per-eval transition table is the most important readout: 5 with-skill evals
improved, 1 regressed, 2 stayed passing, and 8 stayed failing. The one strict
regression is eval 28, classified as rubric friction rather than a clear content
regression. Source:
[`../comparisons/round-c-2026-04-28/data/transitions.csv`](../comparisons/round-c-2026-04-28/data/transitions.csv).

## What Worked

The strongest wins were targeted and interpretable:

- eval 41: verify-before-claim traceback triage moved to a strong skill-only win.
- eval 107: advanced authoring around `SortedSpikesGroup` became a skill-only win.
- eval 113: destructive-operation pushback improved with the cascade template.
- evals 72, 99, and 100 moved from both-fail to both-pass relative to round-C.

The phase-2 edit mapping is summarized in
[`../comparisons/round-c-2026-04-28/data/targeted_edits_summary.csv`](../comparisons/round-c-2026-04-28/data/targeted_edits_summary.csv).

## What Still Needs Work

The main remaining issues are:

- **Rubric friction**: 7 of 9 with-skill failures are annotated as
  `rubric_friction` in [`data/failure_taxonomy.csv`](data/failure_taxonomy.csv).
  These under-count skill performance and should be corrected before a full
  round-E sweep.
- **Script execution**: agents read the tool-routing directive but still rarely
  execute the bundled scripts. The round-D findings identify this as the main
  phase-2.2 gap.
- **Content gap on eval 108**: the skill routes to the right table family but
  does not show the hippocampal `sort_group_id` derivation step.
- **Cost**: with-skill spent 290k extra tokens; 50.5% of extra spend landed on
  both-fail evals. Source: `spend_by_outcome` in
  [`data/cumulative_summary.json`](data/cumulative_summary.json).

## Read Order

For details, start with [`../findings.md`](../findings.md). For generated
artifacts, use:

1. [`INDEX.md`](INDEX.md) for the within-run output map.
2. [`data/cumulative_summary.json`](data/cumulative_summary.json) for round-D
   headline counts.
3. [`../comparisons/round-c-2026-04-28/INDEX.md`](../comparisons/round-c-2026-04-28/INDEX.md)
   for the round-D vs round-C comparison bundle.
4. [`../comparisons/round-c-2026-04-28/data/transitions.csv`](../comparisons/round-c-2026-04-28/data/transitions.csv)
   for the per-eval movement.

## Verdict

Round-D is a useful partial win. The phase-2 edits moved the intended targeted
set upward, especially on hard problem shapes, but the result is underpowered
and still entangled with rubric friction and script-execution gaps. The next
decision should be based on the per-eval fixes and then a full run, not on this
subset as a global headline.
