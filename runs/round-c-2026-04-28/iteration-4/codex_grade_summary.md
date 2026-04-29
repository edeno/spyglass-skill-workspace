# Codex independent grade: iteration 4

Scope: Batch 4, 19 evals. This is a semantic review of the `with_skill` and
`without_skill` responses, not a rewrite of `benchmark.json` or
`grader_summary.md`.

## Headline

| Condition | Semantic full-pass evals | Notes |
| --- | ---: | --- |
| with_skill | 14 / 19 | Strong on workflow sequencing, recovery, dependency tracing, and table-usage answers. Misses remain where the answer needs exact runtime/schema routes or exact workflow position. |
| without_skill | 8 / 19 | Often gets the easy table-usage prompts, but misses several schema-specific or skill-policy-specific cases. |

The automatic grader undercounts several answers because many behavior checks are
pending/null and because at least one forbidden-string hit is a negated warning
rather than a bad recommendation. This pass grades the actual responses.

## Per-eval semantic grade

| Eval | with_skill | without_skill | Rationale |
| --- | --- | --- | --- |
| 072 dep-trace-lfpbandv1 | fail | fail | Both list static FK ancestry but omit the raw-data dependency needed to recreate populated `LFPBandV1`. |
| 085 recover-parameter-edit-in-place | pass | fail | Skill response correctly treats in-place parameter mutation as provenance corruption and recommends scoped destructive recovery/new parameter names. Baseline lacks the cautious-delete framing and offers rollback-by-update paths. |
| 087 counterfactual-trodes-pos-params-swap | pass | fail | Skill response explains new `TrodesPosV1` row/new `PositionOutput` merge id and gives a downstream-discovery one-liner. Baseline explains the concept but does not supply the requested DataJoint descendant check. |
| 089 restrict-by-interval-name-no-star | fail | fail | Both route through `SpikeSortingRecording` instead of the selection table path expected for interval restriction/discovery. |
| 090 usage-after-lfpselection | pass | pass | Both correctly name `LFPV1.populate(key)` as the next step; skill answer is cleaner. |
| 091 usage-after-trodes-pos-selection | pass | pass | Both correctly name `TrodesPosV1.populate(key)` and describe merge-output insertion. |
| 092 usage-after-positionoutput-row | pass | pass | Both point to `fetch1_dataframe()` and merge parent/part inspection. |
| 093 usage-after-lfpbandv1-row | pass | pass | Both give the required restricted-relation `fetch1_dataframe()` operation. Baseline includes a plausible but unsupported `LFPBandOutput` merge-wrapper aside; this is worth flagging but is not part of this eval's stated behavioral contract. |
| 094 usage-pick-target-sampling-rate | pass | fail | Skill answer distinguishes raw-rate filter parameters from the output target sampling rate. Baseline gives the high-level Nyquist answer but blurs the two sampling-rate roles. |
| 095 join-dependent-attr-refusal | pass | pass | Both recognize dependent-attribute collision and recommend projection/two-step restriction. |
| 098 hidden-prereq-ripple-populate | pass | pass | Both enumerate the major prerequisites for `RippleTimesV1.populate()`. |
| 099 hidden-prereq-decoding-populate | pass | pass | Both give a workable prerequisite chain for clusterless decoding, despite literal `key_source` scoring misses. |
| 100 workflow-position-post-sort-clusterless-decode | fail | fail | Skill response routes through the right later chain but assumes `CurationV1` has already happened, even though the prompt only says `SpikeSorting.populate()` finished. Baseline incorrectly says clusterless decoding does not need curation output. |
| 102 session-recording-devices | pass | fail | Skill response uses `Session.DataAcquisitionDevice` and explicitly warns not to fetch `device` from `Session`; baseline misses the part table route. |
| 103 session-subject-owner | pass | pass | Both use `Session.Experimenter`/`LabMember` style routing from subject/session ownership. |
| 104 probe-per-electrode-group | pass | fail | Skill response uses `ElectrodeGroup -> Probe`. Source confirms `ElectrodeGroup` has nullable `Probe`. Baseline routes through electrode-level metadata and does not cleanly use the table relationship. |
| 105 camera-devices-lookup | fail | fail | Skill response mentions useful tables but over-routes through `TaskEpoch` and does not make `VideoFile.camera_name` the primary recording-discovery path. Baseline invents/assumes incompatible camera-key shapes. |
| 106 compound-pfc-wtrack | pass | pass | Both answers are defensible: discover labels, avoid unsafe natural joins, and intersect session/key sets. |
| 108 sorted-spikes-group-hippocampal | fail | fail | Both recommend `SortedSpikesGroup`, but neither gives the needed brain-region route through `BrainRegion`/`ElectrodeGroup`/`SortGroupElectrode` before group creation. |

## Source spot-checks used for schema-sensitive grades

- `TaskEpoch` has a nullable `CameraDevice` FK and a `camera_names` blob.
- `VideoFile` is keyed by `TaskEpoch` plus `video_file_num` and stores
  `camera_name` as a secondary attribute.
- `ElectrodeGroup` declares `-> BrainRegion` and `-> [nullable] Probe`.
- `SortGroup.SortGroupElectrode` is the part table linking sort groups to
  electrodes.

## Eval-layer notes

- Eval 102 has the same raw-substring problem seen in earlier batches: the skill
  response contains `Session.fetch1("device")` only as a negated anti-pattern.
  The forbidden check should be semantic or context-aware.
- Eval 093 should explicitly forbid or penalize invented `LFPBandOutput` if the
  intended contract is "fetch directly from `LFPBandV1`".
- Eval 105 is a useful failure case. It should keep distinguishing
  `TaskEpoch.camera_names` / nullable `CameraDevice` from `VideoFile.camera_name`
  so the model does not collapse all camera routes into one answer.

## Interpretation

Batch 4 shows a larger semantic skill advantage than the raw substring grade:
the skill mainly wins by preserving provenance/recovery discipline and by using
the right Spyglass abstractions. The remaining misses are not generic reasoning
misses; they are exact-schema route misses and exact workflow-position misses
where the skill needs stronger reference/tool pressure for "which table actually
stores the field I need?" and "where exactly am I in the pipeline?"
