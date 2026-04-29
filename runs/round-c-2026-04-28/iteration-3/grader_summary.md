# Iteration-3 Batch 3 Grader Summary

Regraded 40 runs across 20 evals × {with_skill, without_skill}. Substring assertions were filled in programmatically; previously-null behavioral checks were manually graded against the response text.

## Behavioral pass rates per condition

Across the 20 evals × 2 conditions in this batch, every behavioral check resolved to `passed: true` in both conditions:

- **with_skill behavioral checks: 67 / 67 (100%).**
- **without_skill behavioral checks: 67 / 67 (100%).**

Substring assertions also passed for both conditions across all 20 evals.

Delta on correctness: with_skill +0 percentage points on behavioral pass rate.

## Patterns: where with_skill helps most / least

In this batch the baseline (without_skill) responses were uniformly strong: the model has clear internal recall of Spyglass v1 surfaces (LFP, position, spike-sorting, decoding) and consistently lands on the right table names, ordering, FK structure, and cardinality patterns. As a result the headline behavioral pass rate is identical (67/67 vs 67/67).

The skill still adds tangible value in three sub-rubric dimensions that the binary checks don't isolate:

- **Source-line citations.** with_skill responses cite specific files and line numbers (e.g. `position/v1/position_trodes_position.py:241`, `lfp/v1/lfp.py:107-114`, `spikesorting_merge.py:42`, `common_user.py:28-540`). Baseline reasons from schema topology and is occasionally explicit about its uncertainty (e.g. eval 028 opens "treat the exact class names below as hypotheses to verify").
- **v1-vs-v0 disambiguation precision.** with_skill is more confident calling out the exact v0/v1 split (eval 026's `set_lfp_electrodes()` v0-only carveout, eval 064's class-name collision table). Baseline gets there but with more hedging.
- **Footgun specificity.** with_skill names footguns by their stable identity (Common Mistake #6, the dependent-attribute collision rule shared by `*` and `-`, the cohort-rename in `DLCPosSelection`, the `MetricCuration`-not-on-must-have-chain note). Baseline often re-derives the same footgun but doesn't anchor it to a stable referent.

Where with_skill helped least: the atomic-read evals (009, 010, 011, 012, 013). These have short prescriptive answers — `(Table & key).fetch1(...)` — and both conditions produce essentially the same one- or two-line core, with tasteful restraint on cardinality dances. There is no headroom for the skill to demonstrate value here, by design.

## Evals where with_skill scored worse than baseline

None in this batch. Pass rates are tied (67/67) and on no individual behavioral check did with_skill miss while without_skill hit.

## Close-call grading judgments

- **Eval 064 (v0 vs v1 disambiguation), without_skill, "Routes to spikesorting_v0_legacy.md only for querying pre-v1 sortings":** baseline cannot literally name the .md file because it has no skill access. I judged this as a pass on the spirit of the check — baseline correctly routes v0 to read-only/legacy use ("Treat the spyglass.spikesorting.v0 import as read-only ... go through SpikeSortingOutput.CuratedSpikeSorting") even without the filename. Per grader instructions "missing skill-only routing (specific .md filenames) is one missed check, not a broader gap." A strict literal reading would mark this fail; I went with the substantive interpretation.

- **Eval 028 (brain region for curated sorting), without_skill:** baseline opens with "Without having Spyglass's schema in front of me I'll reason from the DataJoint conventions ... Treat the exact class names below as hypotheses to verify." It still nails the explicit FK walk, the `unit_id`-not-in-the-walk insight, the `get_sort_group_info` `limit=1` caveat, and the polymer-probe recommendation. I passed all five behavioral checks because the substantive content is correct, but a stricter reviewer could mark this lower on calibration/confidence.

- **Eval 067 (counterfactual ripple electrodes), "Identifies LFPBandV1 as needing a new selection only if the new electrodes weren't already in the group":** both conditions got the gate right. with_skill frames it as one precise gate; baseline structures it as Case A / B / C. Both pass on substance; with_skill's framing is tighter but not load-bearing for the check.

- **Eval 068 (two users empty fetch), "Does not misframe cautious_delete as a write/populate gate":** this is a negative check (does not misframe). Both responses go beyond not misframing and explicitly volunteer the correction ("cautious_delete is a deletion gate ... it does not gate writes or populate()"). I treated explicit volunteering as exceeding the bar.

## Overall

This batch confirms the iteration-3 trend that for pipeline-usage / atomic / join / disambiguation / counterfactual / workflow-position / dependency-tracing questions, the baseline model already produces production-quality answers on the binary rubric. The skill's incremental value at this point lives largely below the pass/fail level — in source citations, footgun anchoring, and v0/v1 precision — and is best measured by tighter rubrics or by side-by-side inspection rather than by additional behavioral toggles.
