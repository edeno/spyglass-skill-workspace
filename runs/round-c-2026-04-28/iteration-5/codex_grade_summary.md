# Codex Batch 5 Grade

This is a separate Codex-side grading artifact. It does not overwrite
`benchmark.json`, `grader_summary.md`, or the per-run `grading.json` files.

## Strict Assertion Score

These counts apply the current `evals.json` assertions literally, including
exact required substrings.

| condition | evals full pass | expectation pass rate | expectations | tokens / run | duration / run |
| --- | ---: | ---: | ---: | ---: | ---: |
| with_skill | 3/8 | 85.1% | 57/67 | 53,649 | 263.7s |
| baseline | 0/8 | 70.1% | 47/67 | 26,655 | 176.5s |

Delta: with_skill +3 full-pass evals and +15.0 percentage points.

## Per-Eval Notes

- **eval-057 `param-target-sampling-rate`**: both answers are substantively
  correct on `target_sampling_rate`, LFP output rate, Nyquist, 1000 Hz default,
  and aliasing risk. Both miss only the exact phrase `downsampled output`.
- **eval-058 `param-speed-threshold-ripple`**: with_skill passes. Baseline is
  substantively correct but misses the exact substring
  `speed <= speed_threshold`; it says "at or below `speed_threshold`" instead.
- **eval-059 `param-encoding-vs-decoding-interval`**: both answers explain the
  train/apply split and same-vs-different interval use cases. Both miss exact
  required phrases (`model is trained`, `model is applied`, `replay analysis`).
- **eval-060 `param-trodes-smoothing`**: with_skill is source-grounded and
  correctly distinguishes `speed_smoothing_std_dev` from
  `position_smoothing_duration`, including the `0`/`None` validation failure.
  It still misses the `TrodesPosParams.describe()` inspection expectation.
  Baseline gets the broad idea but is less source-accurate about where the
  smoothing enters and also misses the describe expectation.
- **eval-061 `param-sort-group-by-electrode-group`**: with_skill passes.
  Baseline misses the v0-only fact and the concrete SpikeInterface duplicate
  `contact positions` / `SpikeSortingRecording.populate()` failure mode.
- **eval-116 `counterfactual-ripple-threshold`**: with_skill is correct on
  provenance, new `RippleParameters` row, no new `RippleLFPSelection`, fewer
  events, and coexistence of old/new rows; it misses only the exact substring
  `new ripple_param_name` because the phrase is broken by backticks. Baseline
  gives a good high-level answer but uses the wrong parameter blob name
  (`ripple_params` instead of `ripple_param_dict`), suggests re-creating
  `RippleLFPSelection`, and invents a `RippleTimesOutput` merge surface that is
  not in the current skill expectation.
- **eval-117 `counterfactual-sort-interval-change`**: with_skill passes.
  Baseline mostly understands the cascade and curation non-transfer, but misses
  the concrete `new recording_id` / `insert_selection` wording required by the
  eval.
- **eval-118 `counterfactual-decoding-bin-size`**: baseline is slightly closer
  to the eval rubric on untouched upstream objects (`PositionGroup`,
  `UnitWaveformFeaturesGroup`). with_skill adds a useful source-level caveat
  that Spyglass passes the blob opaquely to `non_local_detector`, but it omits
  the explicit "coarser bins = fewer state bins = faster, lower spatial
  resolution" consequence and does not name the untouched upstream group tables.

## Interpretation

Batch 5 is high-value because it tests parameter understanding and
counterfactual provenance, but the strict score is noisier than prior batches.
Several misses are exact-substring false negatives where the answer is
semantically correct. The most obvious candidates for relaxation are:

- eval-057: `downsampled output`
- eval-058: `speed <= speed_threshold`
- eval-059: `model is trained`, `model is applied`, `replay analysis`
- eval-116: `new ripple_param_name`
- eval-118: `new decoding_param_name`

The real skill advantages are eval-061 and eval-116: with_skill avoids the
v0/v1 sort-group trap, identifies the source-level SpikeInterface failure mode,
and keeps ripple parameter changes in a provenance-preserving new-row shape.

The real with_skill miss is eval-118: the answer is cautious and source-based,
but it under-answers the scientific consequence of changing bin size and omits
the explicit untouched upstream groups the rubric asks for.
