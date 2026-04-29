# `encoding_interval` vs `decoding_interval` in `ClusterlessDecodingSelection`

Short answer: **yes, they can be the same interval, and that is in fact a perfectly normal configuration**. They are kept as two separate primary-key fields because the model is mathematically a two-step pipeline — *fit a generative model on encoding data, then run inference on decoding data* — and Spyglass exposes both knobs so you can choose whether those two windows are the same slice of time, two disjoint slices, or one nested inside the other.

Both are FK references into `IntervalList` and live on `ClusterlessDecodingSelection` (and the analogous `SortedSpikesDecodingSelection`) — see [decoding_pipeline.md § Clusterless Decoding Flow](../../../../skills/spyglass/references/decoding_pipeline.md). The same is true for `SortedSpikesDecodingSelection`.

## What each interval actually controls

- **`encoding_interval`** — the time window whose spikes / waveform features and concurrent position are used to **fit** the encoding model: place fields (sorted spikes) or the spike–feature–position joint density (clusterless, via KDE / mark-conditioned intensity). This is the data the classifier "learns from."
- **`decoding_interval`** — the time window over which the fitted model is **evaluated** to produce the posterior `P(position | spikes)` returned in `results.acausal_posterior` / `causal_posterior`. This is the time axis you get back in the xarray `Dataset`.

How the `decoding_interval` is consumed depends on which branch of `make()` runs, which is gated by `estimate_decoding_params` on the selection row (table default `1`):

- True branch (`src/spyglass/decoding/v1/clusterless.py:289`, Baum-Welch): treats times *outside* the decoding interval as missing via an `is_missing` mask, and writes per-time `interval_labels` derived from that mask.
- False branch (`clusterless.py:333`, fixed-parameter): predicts only on the non-empty decoding intervals and concatenates the per-interval outputs. `interval_labels`’ shape depends on this branch.

That mechanical detail is why the two fields exist independently: the encoding window controls the model fit; the decoding window controls which timestamps end up in the posterior.

## Case 1: setting them to the same interval

Totally legitimate. You're saying: "fit the model on this window and also report posteriors over this window." Common situations:

- **Full-session run-epoch decoding.** You have a single run interval (e.g. `"02_r1_valid_times"`) and you want a continuous posterior over that whole run, fit from spikes/position observed during that same run. Just point both fields at that interval name.
- **Sanity-check / training-set decoding.** You want to look at how well the model fits the data it was trained on (residuals, place-field reconstruction quality, MAP-vs-actual on the training window). This is in-sample by construction — useful as a sanity check, not as a generalization test.
- **You only have one well-defined behavioral interval.** If the session has only one usable run epoch, encoding == decoding is the only thing you can do without a held-out split.

## Case 2: when you would set them differently

Set them differently whenever the encoding window and the window you want a posterior over are not the same scientific question. Concrete cases I've seen:

1. **Train on run, decode on rest / sleep / SWR ripples (replay decoding).**
   - `encoding_interval` = run/maze epoch (where the animal moves through space, so you actually see place fields).
   - `decoding_interval` = sleep epoch, post-task rest, or a set of SWR-ripple times.
   This is the canonical Foster-and-Wilson / Karlsson / Davidson replay-detection setup: you need the place-field model from running, but you want the posterior over rest/SWR times where the animal is *not* moving — there is no behavior to fit a model from in the decoding window itself.

2. **Held-out cross-validation / generalization test.** Split run epochs into halves (or trials into odd/even, or first half / second half of the session), encode on one, decode on the other. This breaks the in-sample optimism of Case 1.

3. **Decode across task phases.** Encoding on a "well-behaved" exploratory phase, decoding over a different task phase (e.g. choice point, reward delivery, novel context) where you want to read out what the network represents but where the stats might be too noisy or atypical to fit place fields reliably.

4. **Decoding longer than encoding (or vice versa).** You may have a short, clean run interval for fitting and a long interval for inference (or you use a fast subset of run for encoding to keep memory bounded, and decode over the whole session). The fields are independent — the lengths don't have to match.

## A few practical notes

- Both interval names must already exist as rows in `IntervalList` for that `nwb_file_name` (the FKs into `IntervalList` will fail otherwise). Discover them with:
  ```python
  from spyglass.common import IntervalList
  IntervalList & {"nwb_file_name": nwb_file}
  ```
- The intervals do not need to be disjoint. Overlap, identity, and full nesting are all allowed at the schema level — the choice is scientific, not structural.
- The `decoding_interval` shows up downstream in `results.interval_labels` and (in the False branch) determines how per-interval predictions are concatenated, so if you're going to filter results by interval index later (`results.where(results.interval_labels == 0, drop=True)`), make sure the `decoding_interval` you pick is the one you actually want labeled.
- `estimate_decoding_params` interacts with the decoding interval differently in each branch (mask vs concatenate); if you change one, re-check the other.

## Bottom line

- Same interval for both → fine; it just means "fit and evaluate on the same window" (full-session decoding, in-sample sanity check).
- Different intervals → required whenever the *training* data and the *inference* data are scientifically different — replay decoding (run → sleep/SWR), cross-validation splits, decoding across task phases, or asymmetric-length fit vs predict windows.

Sources: [skills/spyglass/references/decoding_pipeline.md](../../../../skills/spyglass/references/decoding_pipeline.md) — §§ Canonical Example, Clusterless Decoding Flow, Results Structure; cited source lines `src/spyglass/decoding/v1/clusterless.py:83`, `:289`, `:333` and `src/spyglass/decoding/v1/core.py:130`.
