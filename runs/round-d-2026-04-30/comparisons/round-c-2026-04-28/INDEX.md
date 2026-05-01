# Comparison: round-c-2026-04-28 → round-d-2026-04-30

- old_run: `round-c-2026-04-28` (skill_commit `8b3fa1b`, n_evals=130)
- new_run: `round-d-2026-04-30` (skill_commit `7c1e966c`, n_evals=16)
- n_overlap: **16**  *(underpowered for global significance; treat headline McNemar p as diagnostic only)*
- old_only eval_ids (114): not in new run

> ⚠ Subset rerun: the new run covers 16 of 130 old-run evals. Treat this comparison as **verification of the targeted evals**, not a claim about global skill quality. Use the parent run's full summary for headline numbers.

- causal provenance dimensions changed: **2**
  - skill_commit_at_sweep_end, dispatch_prompt_template — see [`data/provenance_diff.json`](data/provenance_diff.json)
- metadata-only differences (do not undermine attribution): round_label

Read [`data/overlap.json`](data/overlap.json) first to confirm exactly what was compared. Then read [`data/headline_diff.json`](data/headline_diff.json) for the overlap-only shift, and [`data/transitions.csv`](data/transitions.csv) for the per-eval moves with rubric-drift and regression-interpretation columns.

## Primary Outputs

- [`INDEX.md`](INDEX.md) — audit: Generated guide to comparison outputs grouped by priority.
- [`data/catalog_diff.json`](data/catalog_diff.json) — audit: Per-eval diff of evals_snapshot.json: added/removed evals plus field-level changes for name / eval_name / stage / tier / difficulty / prompt / expected_output / expectations / assertions / files / expected_refs / expected_scripts. Required reading when provenance_diff shows the causal evals_catalog_semantic_sha256 drifted.
- [`data/comparison_manifest.json`](data/comparison_manifest.json) — audit: Output family/priority/purpose index for this comparison.
- [`data/overlap.json`](data/overlap.json) — audit: Overlap audit: old/new totals, n_overlap, old_only/new_only eval ids. Read this first to confirm what was actually compared.
- [`data/provenance_diff.json`](data/provenance_diff.json) — audit: Skill / src / model / harness / dispatch-template / grader / evals-catalog drift between runs. causal_changed=true is the attribution warning; metadata_changed=true flags label-only differences (round_label / skill_branch / raw snapshot bytes) that do not undermine attribution.
- [`data/intent_balance.csv`](data/intent_balance.csv) — category: Per-eval-intent counts and skill-lift on the overlap. Tracks whether the eval set is balanced for activation behavior — restraint intents (should_not_trigger / near_miss_negative) test whether the skill stays quiet on off-topic prompts; should_trigger tests helpfulness.
- [`figures/c10_is_intent_balanced.png`](figures/c10_is_intent_balanced.png) — category: Two-panel view of eval-set balance and per-intent skill-lift; restraint intents are hatched so a positive lift does not read as a win without inspection.
- [`data/regression_review.csv`](data/regression_review.csv) — fix_priority: Drill-down for ws regressions and rubric_friction stable_fails: paths to old/new response.md and grading.json so reviewers can open both side-by-side.
- [`data/regression_root_cause.csv`](data/regression_root_cause.csv) — fix_priority: Per-regression root-cause classification: rubric / routing / source_selection / tooling / synthesis / unknown. Drives c09 and speeds full-run triage by separating rubric friction from real content regressions.
- [`data/regression_root_cause_summary.json`](data/regression_root_cause_summary.json) — fix_priority: Bucket counts behind c09: how many regressions fall into each root-cause category.
- [`figures/c09_regression_root_causes.png`](figures/c09_regression_root_causes.png) — fix_priority: Distribution of regression root causes (rubric / routing / source_selection / tooling / synthesis / unknown).
- [`data/headline_diff.json`](data/headline_diff.json) — headline: Overlap-only ws/bs full-pass shift, expectation deltas with rubric_sensitive flags, transition tables, and a diagnostic-only McNemar p-value.
- [`figures/c01_did_the_headline_improve.png`](figures/c01_did_the_headline_improve.png) — headline: Paired ws/bs full-pass bars at old vs new with overlap-n callout.
- [`figures/c08_did_skill_lift_change.png`](figures/c08_did_skill_lift_change.png) — headline: Skill-lift (ws_pass_rate - bs_pass_rate) at old vs new with the delta and 95% bootstrap CIs. Headline answer to 'did the skill help differently between commits?'
- [`data/outcome_2x2_shift.json`](data/outcome_2x2_shift.json) — outcome_flow: 4-cell outcome counts at old vs new on the joint set, plus a 4x4 flow matrix with eval_id examples per cell.
- [`figures/c03_where_did_evals_move_in_2x2.png`](figures/c03_where_did_evals_move_in_2x2.png) — outcome_flow: Sankey-lite flow from old outcome buckets to new outcome buckets.
- [`data/targeted_edits_summary.csv`](data/targeted_edits_summary.csv) — targeted_edits: One row per edit_id with transition counts, rubric-changed counts, and all/regressed rubric-friction counts. Renders c04.
- [`figures/c04_did_targeted_edits_explain_movement.png`](figures/c04_did_targeted_edits_explain_movement.png) — targeted_edits: Per-edit_id outcome counts on overlap evals; hatched red marks rubric_friction.
- [`data/transitions.csv`](data/transitions.csv) — transitions: One row per overlap eval with ws/bs transitions, rubric drift, token deltas, and regression_interpretation (rubric_friction / rubric_drift / content_regression).
- [`figures/c02_did_outcomes_move_per_eval.png`](figures/c02_did_outcomes_move_per_eval.png) — transitions: Per-overlap-eval ws transition strip, hatched on ws_rubric_changed.

## Secondary Outputs

- [`data/category_shift.csv`](data/category_shift.csv) — category: Per-(stage, tier) ws + bs full-pass rates and ws transition counts at old vs new with rollups. Answers 'did stage X improve while tier Y regressed?'
- [`figures/c07_where_does_category_drift.png`](figures/c07_where_does_category_drift.png) — category: Heatmap of ws full-pass rate delta by stage x tier; n/a cells indicate no overlap evals with both ws cells present.
- [`data/cost_shift.csv`](data/cost_shift.csv) — cost: Per-overlap-eval token deltas for ws and bs with pair-completeness flags so incomplete timing is never silently aggregated.
- [`figures/c05_did_improvements_cost_more.png`](figures/c05_did_improvements_cost_more.png) — cost: ws token delta per overlap eval, split by ws_transition. Excluded buckets are labeled in a footer rather than rendered as 'no evals'.
- [`data/routing_shift.csv`](data/routing_shift.csv) — routing: Per (eval, condition) required-ref / required-script recall and unexpected-resource counts at old vs new. Gated on transcripts on both sides.
- [`figures/c06_did_routing_change.png`](figures/c06_did_routing_change.png) — routing: Two stacked bar panels: ws required-ref recall delta and required-script recall delta.
- [`data/targeted_edits_long.csv`](data/targeted_edits_long.csv) — targeted_edits: Many-to-many (edit_id, eval_id) rows joining each declared edit to its ws/bs transitions and rubric drift flags.
