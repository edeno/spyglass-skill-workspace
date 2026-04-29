# Batch 5 grader summary — pipeline-usage round 3 + parameter-understanding cluster

## Headline numbers

| Metric | with_skill | without_skill |
| --- | --- | --- |
| Behavioral passes | 29 / 32 | 28 / 32 |
| Substring misses (required + forbidden) | 7 | 14 |

Behavioral pass-rate delta: **+1 (with_skill)** — small at the behavioral
layer in this batch. The substring-rate delta is larger (ws 50% fewer
literal misses), but a substantial fraction of the substring misses are
over-strict literal-phrasing failures rather than substantive ones — see
"Recommended substring relaxations" below.

Per-eval behavioral pass counts:

| Eval | ws | bs |
| --- | --- | --- |
| 057 param-target-sampling-rate | 4/4 | 4/4 |
| 058 param-speed-threshold-ripple | 4/4 | 4/4 |
| 059 param-encoding-vs-decoding-interval | 2/2 | 2/2 |
| 060 param-trodes-smoothing | 3/4 | 3/4 |
| 061 param-sort-group-by-electrode-group | 5/5 | 3/5 |
| 116 counterfactual-ripple-threshold | 5/5 | 4/5 |
| 117 counterfactual-sort-interval-change | 4/4 | 4/4 |
| 118 counterfactual-decoding-bin-size | 2/4 | 4/4 |

## Substring signal: real wins vs over-strict literals

Of the 14 baseline substring misses, the ones that look like **real
skill signal** (baseline genuinely missed the technical content):

- **eval-061** baseline missed `contact positions` and `SpikeSortingRecording`.
  This isn't a phrasing miss — the baseline's response never identifies the
  specific failure mode (duplicate `(x, y)` contact positions rejected at
  `SpikeSortingRecording.populate`) and never flags that
  `set_group_by_electrode_group` is v0-only. The skill response is grounded
  in source on both points.
- **eval-116** baseline missed `ripple_param_dict` and `provenance`. The
  baseline does discuss the issue but with vaguer language ("inconsistent
  with the params hash"); the skill response uses the table's actual blob
  field and explicitly frames the issue as provenance corruption.
- **eval-117** baseline missed `new recording_id` and `insert_selection`.
  Substantively the baseline does describe inserting a new selection row,
  but it doesn't name the exact `recording_id` UUID generation point or
  the `insert_selection()` API surface that the skill cites with line
  numbers.
- **eval-061** baseline also failed two behavioral checks that align with
  these substring misses (the duplicate-contact-position mechanism and
  the v0-only constraint).

The ones that look like **over-strict literal phrasing** (both responses
substantively answer the question; only one happens to use the literal
substring):

- **eval-057** `downsampled output` — both responses describe decimation
  to the output rate using exact synonyms ("decimate the filtered LFP
  down to ... output rate", "the output LFP should be written at after
  filtering and decimation"). Both pass all behavioral checks.
- **eval-059** `model is trained`, `model is applied`, `replay analysis` —
  both responses use "fit/train" and "applied/evaluated" and "replay
  decoding" instead of the literal phrases. Both pass all behavioral
  checks.
- **eval-058** baseline `speed <= speed_threshold` — baseline writes
  "speed is at or below speed_threshold" — clearly the same condition.

## Patterns

**Parameter-understanding (057–061) is converging where both conditions
have semantic depth.** On the simpler param-semantics evals (057, 058,
059) both with_skill and without_skill answer the substantive question
correctly: they correctly identify what each parameter does, give the
right qualitative direction, and explain the relevant tradeoff. The
substring failures here are almost entirely literal-phrasing artifacts.

**The hardest param-understanding eval (061) shows a real skill win.**
Multi-shank `set_group_by_electrode_group` is the case where the
baseline lacks the v0-vs-v1 distinction and the specific
SpikeInterface failure mode. The baseline gives a reasonable
geometry-based explanation but misses the actual error message and
incorrectly treats the method as available in v1. The skill response
is source-grounded and gets both right.

**Counterfactuals (116–118) tested whether responses cascade the
consequence of a parameter change through the dependency chain.**
116 and 117 show with_skill marginally cleaner — better naming of the
exact downstream path and provenance framing. 118 is the *only* eval
in this batch where with_skill scored worse than baseline on
behavioral checks (2/4 vs 4/4).

**Why 118 is the outlier:** the with_skill response gets distracted by
a meta-caveat ("`position_bin_size` may not be a real field — let me
check"), spends a section questioning whether the parameter is honored,
and as a consequence (a) doesn't explicitly name the qualitative
direction (coarser bins → fewer state bins → faster, lower spatial
resolution) and (b) doesn't call out `UnitWaveformFeaturesGroup` /
`PositionGroup` by name as untouched. The baseline answers the
question more directly. This looks like a generation-time choice
(the with_skill response chose to be source-skeptical rather than
direct-answering), not a skill content gap.

## Evals where with_skill scored worse than baseline

- **eval-118 counterfactual-decoding-bin-size**: with_skill 2/4
  behavioral vs baseline 4/4. Failure mode: with_skill spent a
  "no source confirmation" caveat section on whether the field
  exists, and consequently never named the qualitative direction
  or the specific `UnitWaveformFeaturesGroup` / `PositionGroup`
  tables the rubric asked about. Baseline answered the substantive
  question more directly.

## Close-call grading judgments

- **eval-060 (both conditions) — `position_smoothing_duration` placement
  in the pipeline.** With_skill explicitly cites
  `common_position.py:432-438` and says the moving-average is applied
  to the LED positions before centroid. Without_skill places the
  moving-average on the centroid `x, y` (after combination, before
  differencing), which contradicts the source. I judged this a *pass*
  for without_skill on the distinguishing-the-two-fields check because
  it does keep both fields distinct, both before-speed, and the
  rubric's negative requirements ("does NOT claim either is decoupled,
  does NOT claim position_smoothing is applied after speed") are met.
  A stricter reviewer could fairly mark it down.

- **eval-117 (without_skill) — "new recording_id" check.** The rubric
  asks for explicit recognition that `insert_selection` produces a
  NEW `recording_id` (a UUID generated from the inputs, not a
  mutation). Without_skill says "Hash will reflect the new interval"
  and recommends "insert a new selection row" but never uses the
  literal phrase "new recording_id" or cites the UUID-generation
  line. I passed it because the substance is there; a literalist
  reviewer might fail it.

- **eval-116 (without_skill) — provenance framing.** Without_skill
  uses "params hash they were computed under" and "remain valid as a
  comparison baseline" instead of the word "provenance". The mental
  model is the same; I passed it on substance.

## Substantive misses by either condition

The runs whose `overall_passed` is now false are mostly false because
of the substring-grader, not the behavioral-grader. The ones with
behavioral failures that are genuinely substantive:

- **eval-060 both conditions**: neither response recommends inspecting
  `TrodesPosParams.describe()` / `.heading` to discover the exact
  field names. Both cite source files instead. Real miss vs. the
  rubric's intent (encourage using DataJoint introspection methods),
  but functionally both responses give the right field names anyway.
- **eval-061 baseline**: missed both the SpikeInterface failure mode
  ("contact positions are not unique" at `SpikeSortingRecording.populate`)
  and the v0-only API constraint. Real skill-content win for with_skill.
- **eval-116 baseline**: incorrectly recommends re-creating
  `RippleLFPSelection` — the rubric's "no new RippleLFPSelection row
  is needed" check fails because baseline says "Re-create the
  RippleLFPSelection (or equivalent) entry pointing at default_zscore_3".
  This is a factual error.
- **eval-118 with_skill**: the two missing checks discussed in the
  outlier section above (qualitative direction, named tables).

## Recommended substring relaxations

These literal substrings appear over-strict given that both responses
substantively answer the question with exact synonyms. The skill
maintainer can decide whether to relax:

1. **eval-057** `downsampled output` → accept synonyms like
   `decimate(d) ... output rate`, `output LFP rate (after) decimation`,
   or any phrasing that pairs "output" with a downsampling verb.
2. **eval-058** `speed <= speed_threshold` → accept "speed is at or
   below speed_threshold" / "below threshold at endpoints" / any
   formal statement of the immobility-at-boundaries condition.
3. **eval-059** `model is trained`, `model is applied`,
   `replay analysis` → accept "fit/train the model", "apply/evaluate
   the model", "replay decoding". The literal-passive-voice forms
   are not how either response chose to phrase it.
4. **eval-060** `TrodesPosParams.describe` → would suggest making this
   *behavioral* rather than substring (the goal is "recommend a
   DataJoint introspection method to discover field names"). Both
   responses chose source-citation instead, which is also valid;
   the substring shape conflates "discoverability via the API" with
   "literally call .describe()".
5. **eval-116** `new ripple_param_name` (with_skill miss) → with_skill
   uses `ripple_param_name="zscore3"` (a concrete new name) but
   never the literal phrase "new ripple_param_name". Accept any
   form of "insert under a new ripple_param_name".
6. **eval-117** `new recording_id`, `insert_selection` (baseline miss)
   → without_skill says "insert a new selection row" and "Hash will
   reflect the new interval", which is the same content. Accept
   "insert a new selection row" as a synonym for `insert_selection`,
   and "new selection row" / "new selection key" as synonyms for
   `new recording_id`.
7. **eval-118** `new decoding_param_name` (both miss) → both responses
   use `decoding_param_name="my_params_5cm"` etc. — concrete new
   names. Same shape as 116.

Substrings that look correctly strict and would catch real failures
if relaxed too far:

- **eval-061** `contact positions`, `SpikeSortingRecording`, and the
  paired behavioral check. These successfully gated the v0-vs-v1
  technical accuracy of the answer.
- **eval-116** `ripple_param_dict`, `provenance`. The baseline missed
  the explicit framing the rubric is testing for.
