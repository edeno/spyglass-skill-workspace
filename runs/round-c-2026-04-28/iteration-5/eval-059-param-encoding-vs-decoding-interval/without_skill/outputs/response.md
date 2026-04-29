# Clusterless decoding: `encoding_interval` vs `decoding_interval`

Short answer: **yes, they can be the same interval, and that's a perfectly valid (and common) choice — but they're separated on purpose so you can set them differently when the science calls for it.**

## What each interval controls

In the Spyglass clusterless decoding pipeline (`spyglass.decoding.v1.clusterless.ClusterlessDecodingV1`, backed by the `non_local_detector` package), the selection table takes two `IntervalList` references:

- **`encoding_interval`** — the time window used to **fit/train** the generative model. Specifically, this is the data the decoder uses to learn:
  - the **place fields / mark intensity functions** (the joint distribution `p(mark, position)` for each electrode, in the clusterless case),
  - the **occupancy** (how much time the animal spent at each position),
  - and any other parameters of the observation/likelihood model.
- **`decoding_interval`** — the time window over which the fitted model is **applied** to compute the posterior `p(position_t | spikes_{1:t})` (or smoothed posterior, depending on the algorithm). This is the window you actually get a decoded trajectory for.

Internally, the make function pulls spikes/marks and position for both intervals, fits the encoding model on the encoding interval, then runs the state-space filter/smoother on the decoding interval.

## Case 1: Same interval (encoding == decoding)

Setting them to the same `IntervalList` (e.g. both pointing to `"pos 0 valid times"` or a run epoch) is fine and is what people often do as a first pass. You're saying "fit the place fields on this run, and decode that same run."

Caveats when they're identical:

- This is **in-sample decoding**. The model has seen every time bin it's being evaluated on, so decoded position will tend to track true position closely — that's not strong evidence the decoder generalizes.
- For benchmarking decoder quality, people typically use **cross-validation** (fit on one portion, decode on a held-out portion), which requires the two intervals to differ.
- It is still the right choice when your goal is just "give me the best posterior over position for this epoch using all available data," e.g. for downstream replay detection on a separate epoch.

## Case 2: Different intervals — when and why

You want them different whenever the **statistics you want the model to learn** live in a different time window than the **times you want to decode**. Common scenarios:

1. **Decoding replay during sleep / immobility / SWRs.**
   - `encoding_interval`: the run/behavior epoch where the animal actively explored the track (so place fields are well-sampled).
   - `decoding_interval`: a sleep epoch, a quiet-wake epoch, or specifically the SWR/ripple times.
   - Rationale: there's no spatial behavior to learn place fields from during sleep, and replay events are exactly the thing you want to decode. This is the canonical Frank-lab use case.

2. **Decoding a different task phase than you trained on.**
   - Train on free exploration, decode on a goal-directed task on the same track — or vice versa — to ask whether the spatial code generalizes across behavioral states.

3. **Cross-validation / held-out evaluation.**
   - Train on the first half of a run, decode on the second half (or interleaved folds). Required for any honest decoder-quality metric (e.g. median decoding error, posterior calibration).

4. **Decoding immobility / consummatory periods at reward sites** while having learned place fields from movement-only times. A movement filter is often applied to the encoding interval (so you don't dilute place fields with stationary periods) but you still want to decode through the stationary periods.

5. **Decoding novel-environment exposure using a familiar-environment model**, or decoding an extended session using place fields from a stable subset, when you have reason to believe the code is stationary across those windows.

6. **Stitching together non-contiguous encoding data.** If place fields are best estimated from several short clean windows but you want a single continuous decoded trace, define a composite encoding interval and a separate continuous decoding interval.

## Practical guidance

- For a first sanity-check / debug run: set them equal to your run epoch. Verify the decoder reconstructs true position reasonably before doing anything more elaborate.
- For replay analyses: encoding = run epoch (with a movement-speed filter applied via the position selection / encoding params), decoding = sleep epoch or ripple times.
- For reported decoder accuracy: use disjoint intervals (e.g. odd vs even laps, or a held-out time block). Don't quote in-sample error as accuracy.
- The two intervals do **not** need to be subsets of each other and do **not** need to overlap. They just need to be valid `IntervalList` entries for the same `nwb_file_name`, and the encoding interval needs to contain enough behavior+spikes for the model to be identifiable.
- Both intervals must be covered by your `PositionOutput` (you need position during encoding to learn place fields, and during decoding if you want to compare decoded vs actual — though strictly the decoder only *requires* position for the encoding window).

## TL;DR

Same interval = quick in-sample decode, fine for development. Different intervals = the whole point of separating them — fit place fields where the animal is behaving, then decode wherever you actually want a posterior (sleep, ripples, held-out laps, a different task phase). The split exists so you can do replay decoding and cross-validation cleanly.
