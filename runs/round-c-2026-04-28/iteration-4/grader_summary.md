# Batch 4 Grader Summary — Pipeline-Usage Round 2

19 evals × 2 conditions = 38 runs. This is the seventh and final batch graded
in the iteration-4 sweep (130 evals total).

## Headline numbers

| Condition     | Behavioral pass count | Pass rate |
| ------------- | --------------------- | --------- |
| with_skill    | 54/63                 | 85.7%     |
| without_skill | 44/63                 | 69.8%     |

**Delta: +15.9pp** on the with_skill base (10 more behavioral expectations
passed out of 63). Roughly tracks the substring-level signal (with_skill
missed 9 substrings vs without_skill missed 15) and is in line with prior
pipeline-usage batches; the larger spread here vs batch 3 / 5 is driven
by the joins / atomic-read evals where the skill steers responses to the
correct part-table (Session.DataAcquisitionDevice, ElectrodeGroup→Probe via
nullable FK, exact-match FirFilterParameters keying).

## Per-eval behavioral pass-count table

| Eval | Tier | with | without | Δ |
| --- | --- | --- | --- | --- |
| 072 dep-trace-lfpbandv1 | dependency-tracing | 2/3 | 2/3 | 0 |
| 085 recover-parameter-edit-in-place | workflow-recovery | 4/5 | 3/5 | +1 |
| 087 counterfactual-trodes-pos-params-swap | counterfactual | 5/6 | 5/6 | 0 |
| 089 restrict-by-interval-name-no-star | joins | 3/5 | 2/5 | +1 |
| 090 usage-after-lfpselection | table-usage | 2/2 | 2/2 | 0 |
| 091 usage-after-trodes-pos-selection | table-usage | 2/2 | 2/2 | 0 |
| 092 usage-after-positionoutput-row | table-usage | 2/2 | 2/2 | 0 |
| 093 usage-after-lfpbandv1-row | table-usage | 2/2 | 2/2 | 0 |
| 094 usage-pick-target-sampling-rate | table-usage | 4/4 | 2/4 | +2 |
| 095 join-dependent-attr-refusal | joins | 4/4 | 2/4 | +2 |
| 098 hidden-prereq-ripple-populate | dependency-tracing | 2/2 | 2/2 | 0 |
| 099 hidden-prereq-decoding-populate | dependency-tracing | 2/2 | 2/2 | 0 |
| 100 workflow-position-post-sort-clusterless-decode | workflow-position | 1/2 | 1/2 | 0 |
| 102 session-recording-devices | joins | 3/3 | 1/3 | +2 |
| 103 session-subject-owner | joins | 3/3 | 3/3 | 0 |
| 104 probe-per-electrode-group | atomic-read | 3/3 | 2/3 | +1 |
| 105 camera-devices-lookup | atomic-read | 2/3 | 2/3 | 0 |
| 106 compound-pfc-wtrack | compound | 5/5 | 5/5 | 0 |
| 108 sorted-spikes-group-hippocampal | group-tables | 3/5 | 2/5 | +1 |

## Patterns

**Dependency-tracing (072, 098, 099).** Both conditions converged on the same
answers and, importantly, on the same blind spot: 072 (`LFPBandV1` upstream
ancestry) — neither condition named `Raw` as the runtime data source pulled
inside `LFPV1.make()`. Both responses walked the static FK chain cleanly
but missed that `Raw` is fetched at populate time, not declared as an FK.
This is a known eval where the static-graph view both responses use is
structurally insufficient. 098 and 099 were full passes for both.

**Counterfactual (087).** Both responses correctly identified that swapping
`trodes_pos_params_name` mints a new TrodesPosV1 row plus a new
PositionOutput merge_id. with_skill called `.descendants()` explicitly
(eval expectation); without_skill walked the graph by hand and missed the
DataJoint-method call check, but compensated by enumerating LFP /
spike-sorting / curation as unaffected branches — the inverse failure
mode. Net: 5/6 each on different checks.

**Workflow-recovery (085) and atomic-read/joins cluster (089, 095, 102, 104,
105).** with_skill outperformed by a clear margin. The skill consistently
routes through the correct part-table (Session.DataAcquisitionDevice
vs pynwb file inspection in 102; ElectrodeGroup→Probe with nullable-FK
warning in 104; FirFilterParameters exact-match keying in 094) and flags
the silent-no-op restriction footgun. without_skill in 102 went the
pynwb route entirely and never used the canonical Spyglass part-table.

**Table-usage / "what's next after X" (090–094).** Both conditions are
tied at full passes on the easy ones (090, 091, 092, 093), with the skill
pulling ahead on 094 (target_sampling_rate) where the skill cited the
exact `(filter_name, filter_sampling_rate)` keying rule and without_skill
gave only a generic "Nyquist is fine" answer.

**Workflow-position (100), group-tables (108).** Both conditions struggled
on these. 100: with_skill assumed CurationV1 was already done and skipped
flagging it as the mandatory next step; without_skill explicitly called
curation "optional/sidestepped" — a substantive miss. 108: neither
condition derived hippocampal sort_group_ids by walking
SortGroup.SortGroupElectrode * Electrode * BrainRegion as the eval
demanded — both punted to "you decide / restrict by region".

**Compound (106) and session-introspection (103).** Both full passes for
both conditions — these are well-rehearsed common queries.

## Evals where with_skill scored worse than baseline

None. The closest the skill came to underperforming was 087 (tied, with
each condition missing a different check) and 105 (tied at 2/3, both
missing the camera_name-is-secondary-not-FK distinction).

## Close-call grading judgments

- **108 with_skill, BC4 (`spikesorting_merge_id` + `get_restricted_merge_ids`
  per-key).** The response uses the projected attr name correctly but
  routes through `merge_restrict({"nwb_file_name": ...})` instead of
  looping `get_restricted_merge_ids` per recording. Marked fail because
  the eval explicitly calls out the per-call loop as the correctness
  requirement, but the response's path also works in practice — close call.
- **085 with_skill, BC3 (enumerate unaffected branches).** Marked fail
  because the response cites `db_graph.py path --down RippleTimesV1` for
  the user to run, rather than enumerating LFP / LFPBand / RippleLFPSelection
  / position / decoding as the eval's literal text expects. Defensible
  either way — the response defers to a canonical inspection tool, which
  is arguably better practice than enumerating from memory.
- **099 BC1 (first diagnostic = `len(ClusterlessDecodingSelection & key)`).**
  Both responses include the check but neither leads with it. Graded as
  pass for both since both responses do clearly identify ClusterlessDecodingSelection
  as the row-identity check.

## Substantive misses by either condition

- **072 (both): `Raw` not named.** Static-graph dependency walk misses
  the runtime fetch in LFPV1.make().
- **100 (both): CurationV1 framing.** with_skill assumes user has done
  it; without_skill calls it optional — both wrong, since the
  SpikeSortingOutput.CurationV1 part-row is structurally required even
  for clusterless.
- **108 (both): hippocampal-sort-group derivation skipped.** Both gave
  a placeholder filter-comment instead of walking through Electrode→BrainRegion.
- **102 without_skill: pynwb-only answer.** Misses the Spyglass-native
  `Session.DataAcquisitionDevice` part-table entirely — a 0/3 BC scoring.

## Recommended substring relaxations

Tight list, this being the final batch:

1. **072** — `Raw` is required but neither condition produced it; this
   is a real failure mode (static-graph incompleteness), not a phrasing
   issue. Keep as-is — it's a meaningful signal.
2. **102 with_skill `Session.fetch1("device")` forbidden-substring false
   positive.** The response contains `Don't write Session.fetch1("device")`
   as a guardrail warning; the literal substring grader caught it as
   forbidden. Recommend either (a) loosening the forbidden-substring to
   match a code-block context only, or (b) updating the with_skill
   reference text to use a different example phrasing. Low priority —
   it's clearly a doing-the-right-thing-in-prose case.
3. **108 `region_name` and `SortGroupElectrode` required substrings.**
   Both conditions failed these because neither response actually walked
   that path. The substring is a reasonable proxy for the BC2 derivation
   check; keep.

No other relaxations recommended — substring assertions in this batch
are pulling their weight as proxies for the behavioral checks.
