# Codex semantic grade summary - Batch 7

This is an independent semantic grade of the Batch 7 responses. It does not
modify `benchmark.json`, `grader_summary.md`, or any per-eval `grading.json`.

The existing per-eval grader output is useful as a literal-substring screen,
but many behavioral checks are still stored as `null` or are represented by
over-specific substrings. This pass grades whether the response satisfied the
eval intent.

## Headline

| Metric | with_skill | baseline | Delta |
|---|---:|---:|---:|
| Semantic full-pass evals | 26 / 30 | 12 / 30 | +14 |
| Total tokens | 1,046,949 | 634,362 | +412,587 |
| Mean tokens / run | 34,898 | 21,145 | +13,753 |
| Mean duration / run | 76.3 s | 66.6 s | +9.7 s |

Batch 7 shows a large skill win, especially on setup, ingestion edge cases,
destructive-operation guardrails, group-table routing, and custom-pipeline
authoring.

## Semantic pass/fail table

| Eval | with_skill | baseline | Notes |
|---:|:---:|:---:|---|
| 001 | PASS | FAIL | Skill used `scripts/install.py` and set `SPYGLASS_BASE_DIR`; missing literal `dj_local_conf.json` is not a semantic failure because it correctly used global config for a personal laptop. Baseline missed the installer route. |
| 002 | PASS | FAIL | Skill explicitly used raw filename, explained underscored copy, warned against `skip_duplicates=True`, and named `reinsert=True`. Baseline explained underscored copy but recommended delete/re-run for reinsertion and did not name `reinsert=True`. |
| 008 | FAIL | FAIL | Both designs consume broad LFP and re-filter in the custom table. The eval intent was to route through `LFPBandV1` / `LFPBandSelection` so theta and gamma are first-class Spyglass band outputs. |
| 020 | PASS | PASS | Both correctly treated this as plain pynwb, not Spyglass activation. |
| 022 | PASS | FAIL | Skill used `scrub_dj_config.py` and refused raw secret reads. Baseline refused raw reads but used an ad hoc scrub that only drops `database.password`, missing the bundled nested-secret scrubber. |
| 023 | PASS | PASS | Both pushed back on skipping inspection and required confirmation; skill was more precise about `fetch(as_dict=True)`. |
| 024 | PASS | FAIL | Skill refused `super_delete()` and routed to team/LabMember ownership. Baseline explained the guardrail but still emitted `super_delete(warn=False)` as an admin escape hatch in an adversarial prompt. |
| 032 | PASS | FAIL | Skill identified the `channel_name` / `nwb.electrodes.colnames` root cause. Baseline stayed generic around channel-id mismatch and did not hit the specific failure mode. |
| 033 | PASS | FAIL | Skill named `epochs.tags`, `task_epochs`, silent drops, and `reinsert=True`. Baseline diagnosed interval-name collision and delete/re-run, but missed the task-table/reinsert-specific path. |
| 034 | PASS | PASS | Both pushed back on deleting `DataAcquisitionDevice` and offered inspect/rename or NWB rewrite alternatives. |
| 040 | PASS | FAIL | Skill used stores-level config and persistence. Baseline missed the key `dj.config['stores']` / `SpyglassConfig` diagnosis. |
| 041 | FAIL | PASS | Skill overcorrected away from schema drift and treated `KeyError: 'pipeline'` mainly as params/env drift. Baseline better matched the prompt: code ahead of DB, inspect source heading vs DB heading, consult `CHANGELOG.md` migrations. |
| 042 | PASS | FAIL | Skill gave the safe `cleanup(dry_run=True)` recovery path and LabMember root fix. Baseline explained `super_delete` damage but recommended cleanup with deletion too directly. |
| 045 | PASS | FAIL | Skill split MySQL grants, filesystem, and LabMember layers. Baseline missed the LabMemberInfo layer. |
| 046 | PASS | PASS | Both identified site-packages/editable install drift with `spyglass.__file__`, `pip install -e .`, and kernel restart. |
| 047 | PASS | FAIL | Skill recommended recreating/updating from `environment_min.yml` and future `pip install --dry-run`. Baseline focused on OpenCV surgery instead of restoring the Spyglass environment shape. |
| 053 | PASS | PASS | Both correctly classified `LFPSelection` as Manual tier and selection role. Literal `Manual table` mismatch in skill output is not substantive. |
| 054 | PASS | PASS | Both distinguished Trodes params vs selection and where to insert the parameter dict. |
| 055 | PASS | PASS | Both explained `PositionOutput` as a merge table populated through part rows, not `populate()`. |
| 056 | PASS | FAIL | Skill correctly said `LFPBandV1` is Computed and has no merge wrapper. Baseline invented/leaned on an `LFPBandOutput` merge layer. |
| 066 | PASS | PASS | Both routed destructive merge-key deletion to destructive-operations first. |
| 083 | FAIL | FAIL | Skill named `custom_pipeline_authoring.md` first but did not explicitly identify `spyglassmixin_methods.md` as the similar-sounding distractor. Baseline also missed the exact reference/distractor distinction. |
| 088 | PASS | FAIL | Skill disambiguated delete layers and used `DecodingOutput.merge_delete` workflow. Baseline stayed too generic and did not route through merge deletion. |
| 107 | PASS | FAIL | Skill used `SortedSpikesGroup`, `create_group`, `UnitSelectionParams`, and projected `spikesorting_merge_id`. Baseline reinvented grouping and missed the built-in abstraction. |
| 110 | PASS | FAIL | Skill used the custom-pipeline shape, `AnalysisNwbfile().build(...)`, and non-negotiables. Baseline stored the heavy result outside the row but used the older/manual create-add lifecycle. |
| 111 | PASS | PASS | Both pushed back on inline blobs and routed to AnalysisNwbfile; skill was stronger and cited the non-negotiable. |
| 112 | FAIL | PASS | Skill correctly refused editing `DLCPosV1`, but then recommended a `dj.Manual` side table for bodyparts. The eval expected a new `dj.Computed` table in the user's schema, FK'd to `DLCPosV1`. Baseline had the right downstream `dj.Computed` shape. |
| 113 | PASS | FAIL | Skill preserved provenance with a new `ripple_param_name`, named `RippleTimesV1`, and explained the speed-threshold direction. Baseline used version-generic `RippleTimes` / `RippleTimesSelection` and introduced an unnecessary new selection row. |
| 114 | PASS | FAIL | Skill strongly rejected `longblob`, routed to `AnalysisNwbfile`, dropped redundant `group_name`, and included `SpyglassMixin`. Baseline was too permissive and offered non-Spyglass external-store alternatives. |
| 121 | PASS | PASS | Both diagnosed editable/site-packages drift and used `spyglass.__file__`, `pip install -e .`, and restart. Skill missed literal `pip show`, but the diagnostic was sufficient. |

## Skill wins

- Destructive safety: evals 024, 042, 088, 113.
- Runtime/environment triage: evals 040, 045, 047, 121.
- Source-backed ingestion edge cases: evals 032, 033.
- Built-in abstractions instead of invented tables: evals 056, 107, 110, 114.

## Skill misses worth acting on

1. **Eval 008: custom LFP-derived pipelines.**
   The skill chose `LFPOutput` and re-filtered inside the custom `make()`. For a theta/gamma band-power pipeline, the better Spyglass shape is to depend on `LFPBandV1` / `LFPBandSelection` so band outputs are explicit, reusable, and provenance-backed.

2. **Eval 041: schema drift after pull.**
   The skill over-applied skepticism and did not answer the user's direct drift question. It should first compare source declaration vs runtime DB heading and, when code expects a new field missing from DB, say "code is ahead of DB" and route to `CHANGELOG.md` migrations / `Table.alter()`.

3. **Eval 083: reference-selection distractors.**
   The skill correctly selected `custom_pipeline_authoring.md` but failed the "similar-sounding wrong reference" part. Resource-selection evals should expect explicit distractor handling when the prompt asks for it.

4. **Eval 112: extending core tables.**
   The skill refused editing `DLCPosV1`, which is correct, but recommended `dj.Manual` for a derivable bodypart summary. The stronger default is a new `dj.Computed` table in the user's schema, `SpyglassMixin` first, FK to `DLCPosV1`; use Manual only for truly human-curated annotations.

## Eval-layer notes

- Some required substrings are over-specific relative to semantic correctness:
  `dj_local_conf.json` in eval 001, exact `Manual table` / `Computed table`
  casing in table-classification evals, `pip show` in eval 121.
- Some evals need stronger forbidden checks:
  eval 056 should forbid inventing an `LFPBandOutput` merge wrapper.
- Batch 7 is a useful discriminator. Unlike the easier earlier batches, it
  surfaced real with-skill misses while still showing a large overall skill
  advantage.
