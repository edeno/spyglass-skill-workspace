# Comparison: round-c-2026-04-28 → round-d-2026-04-30

- old_run: `round-c-2026-04-28` (skill_commit `8b3fa1b`, n_evals=130)
- new_run: `round-d-2026-04-30` (skill_commit `7c1e966c`, n_evals=16)
- n_overlap: **16**  *(underpowered for global significance; treat headline McNemar p as diagnostic only)*
- old_only eval_ids (114): not in new run

Read [`data/overlap.json`](data/overlap.json) first to confirm exactly what was compared. Then read [`data/headline_diff.json`](data/headline_diff.json) for the overlap-only shift, and [`data/transitions.csv`](data/transitions.csv) for the per-eval moves with rubric-drift and regression-interpretation columns.

## Primary Outputs

- [`INDEX.md`](INDEX.md) — audit: Generated guide to comparison outputs grouped by priority.
- [`data/comparison_manifest.json`](data/comparison_manifest.json) — audit: Output family/priority/purpose index for this comparison.
- [`data/overlap.json`](data/overlap.json) — audit: Overlap audit: old/new totals, n_overlap, old_only/new_only eval ids. Read this first to confirm what was actually compared.
- [`data/headline_diff.json`](data/headline_diff.json) — headline: Overlap-only ws/bs full-pass shift, expectation deltas with rubric_sensitive flags, transition tables, and a diagnostic-only McNemar p-value.
- [`figures/c01_headline_shift.png`](figures/c01_headline_shift.png) — headline: Paired ws/bs full-pass bars at old vs new with overlap-n callout.
- [`data/outcome_2x2_shift.json`](data/outcome_2x2_shift.json) — outcome_flow: 4-cell outcome counts at old vs new on the joint set, plus a 4x4 flow matrix with eval_id examples per cell.
- [`figures/c03_outcome_flow.png`](figures/c03_outcome_flow.png) — outcome_flow: Sankey-lite flow from old outcome buckets to new outcome buckets.
- [`data/targeted_edits_summary.csv`](data/targeted_edits_summary.csv) — targeted_edits: One row per edit_id with transition counts, rubric-changed counts, and all/regressed rubric-friction counts. Renders c04.
- [`figures/c04_targeted_edits.png`](figures/c04_targeted_edits.png) — targeted_edits: Per-edit_id outcome counts on overlap evals; hatched red marks rubric_friction.
- [`data/transitions.csv`](data/transitions.csv) — transitions: One row per overlap eval with ws/bs transitions, rubric drift, token deltas, and regression_interpretation (rubric_friction / rubric_drift / content_regression).
- [`figures/c02_per_eval_transitions.png`](figures/c02_per_eval_transitions.png) — transitions: Per-overlap-eval ws transition strip, hatched on ws_rubric_changed.

## Secondary Outputs

- [`data/cost_shift.csv`](data/cost_shift.csv) — cost: Per-overlap-eval token deltas for ws and bs with pair-completeness flags so incomplete timing is never silently aggregated.
- [`figures/c05_cost_shift_by_transition.png`](figures/c05_cost_shift_by_transition.png) — cost: ws token delta per overlap eval, split by ws_transition. Excluded buckets are labeled in a footer rather than rendered as 'no evals'.
- [`data/routing_shift.csv`](data/routing_shift.csv) — routing: Per (eval, condition) required-ref / required-script recall and unexpected-resource counts at old vs new. Gated on transcripts on both sides.
- [`figures/c06_routing_shift.png`](figures/c06_routing_shift.png) — routing: Two stacked bar panels: ws required-ref recall delta and required-script recall delta.
- [`data/targeted_edits_long.csv`](data/targeted_edits_long.csv) — targeted_edits: Many-to-many (edit_id, eval_id) rows joining each declared edit to its ws/bs transitions and rubric drift flags.
