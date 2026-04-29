# `speed_threshold: 4.0` in Spyglass `RippleParameters`

## What it does

`speed_threshold` is the animal's running-speed cutoff (in cm/s) used to gate which candidate ripple-band events get kept as ripples. It does **not** affect the LFP filtering or the z-score detection itself — it's a *behavioral mask* layered on top.

In the Spyglass ripple pipeline (`spyglass.ripple.v1.RippleTimesV1`), the parameter is stored inside `ripple_param_dict["ripple_detection_params"]` and is passed straight through to the underlying detector function from the `ripple_detection` package (either `Kay_ripple_detector` or `Karlsson_ripple_detector`, depending on `ripple_detection_algorithm`). The detector also takes the speed trace from `PositionOutput` (the column named by `speed_name`, typically `"head_speed"` for the `default` preset or `"speed"` for `default_trodes`).

Operationally inside `ripple_detection`, the rule is roughly:

> A candidate event (a stretch where ripple-band z-scored power exceeds `zscore_threshold` for at least `minimum_duration`) is **only retained as a ripple if the animal's speed is at or below `speed_threshold` at the event boundaries** (start and end of the candidate window). Events where the animal is moving faster than the threshold get discarded.

So `speed_threshold = 4.0` means: "keep events only when the animal is essentially still (≤ 4 cm/s) at the event's start and end." 4 cm/s is the conventional immobility cutoff used in the Frank-lab / Karlsson / Kay papers — it's slow enough to exclude active locomotion and most head movements but loose enough to admit pauses, grooming, and quiet wakefulness.

The other params in the same dict do different jobs:

- `zscore_threshold: 2.0` — power threshold (in SDs of ripple-band envelope) for an event to qualify.
- `minimum_duration: 0.015` — events shorter than 15 ms are dropped.
- `smoothing_sigma: 0.004` — Gaussian smoothing (4 ms) on the envelope before thresholding.
- `close_ripple_threshold: 0.0` — minimum gap between consecutive events; 0.0 means don't merge.
- `speed_name` — which column in the position dataframe to use as "speed."

## What happens at 10 cm/s

You will get **more ripples**, not fewer.

You're loosening the immobility gate: events that occurred while the animal was moving at 4–10 cm/s — previously filtered out — now pass through. The LFP-based z-score detection finds the same candidate windows; you're just rejecting fewer of them on behavioral grounds.

A useful sanity check: plot the speed distribution at candidate-event times. The number of newly admitted events at 10 vs 4 cm/s scales roughly with the fraction of time the animal spends in that 4–10 cm/s band, which on a typical W-track or open-field session is non-trivial (think slow exploration, reward-site approach, head scans).

## The quality tradeoff

This is the core consideration:

**Sharp-wave ripples (SWRs) in CA1 are, classically, an offline / quiet-wakefulness phenomenon.** The canonical literature (Buzsáki, Foster & Wilson, Karlsson & Frank, Jadhav, Carr, etc.) treats SWRs as events that occur during slow-wave sleep, consummatory behavior, immobility pauses, and reward consumption — when the hippocampus shifts out of theta-dominated "online" navigation mode. Replay of place-cell sequences during ripples — the thing most people are detecting ripples *for* — has been characterized almost exclusively in that immobility regime.

Raising `speed_threshold` from 4 to 10 cm/s buys you more events but lowers the **specificity** of the detection in several ways:

1. **Theta–ripple contamination.** During locomotion, CA1 LFP is dominated by theta (~6–10 Hz) with prominent gamma. Bursts of high-frequency power in the 150–250 Hz band can occur during running — driven by gamma harmonics, EMG, chewing, sharp head movements — and look ripple-like to a band-pass + z-score detector. The 4 cm/s gate exists specifically to keep these out.

2. **Type II / "running ripples" are different beasts.** There is a literature on ripple-band events during movement (sometimes called type-II ripples, or movement-associated ripples — O'Neill, Csicsvari, others). They exist, but they're generally shorter, lower-amplitude, and have different downstream meaning than classical SWRs. If your downstream analysis (replay decoding, ripple-triggered averaging, memory-consolidation correlates) assumes "classical" SWRs, mixing in running ripples will dilute or distort the result.

3. **EMG / motion artifacts.** Faster speeds correlate with more head and body movement, which couples into the LFP as broadband noise that survives the 150–250 Hz band-pass.

4. **Reference-frame bias.** Speed comes from the position tracking. If position is noisy (Trodes can have brief jumps; DLC has mislabel frames), a 10 cm/s gate is more vulnerable to spurious speed spikes letting noise events through than a 4 cm/s gate is.

So the tradeoff is **sensitivity vs specificity**:

| `speed_threshold` | Effect | When to use |
|---|---|---|
| Lower (e.g. 2–4 cm/s) | Fewer events, higher specificity to classical SWRs. Closer to canonical replay-study definitions. | Replay decoding, memory-consolidation analyses, anything where you need ripples to be "true" SWRs. |
| Higher (e.g. 10 cm/s) | More events, but a non-trivial fraction will be peri-movement ripple-band power, not bona fide SWRs. | If you specifically want to study movement-associated ripples, or you have an extra downstream filter (e.g. ripple-triggered averaging that will reject non-stereotyped events). |

## Recommendations

- For most Frank-lab-style analyses, **stay at 4 cm/s**. It's the field standard and matches how upstream papers defined the events.
- If you want more events, consider lowering `zscore_threshold` (e.g. 2.0 → 1.5) **before** raising `speed_threshold`. That gives you weaker but still immobility-locked events, which is usually a cleaner tradeoff than admitting peri-movement events.
- If you do raise it, **plot the joint distribution of event speed and event amplitude / duration** on a known session before trusting the new threshold — running-speed events typically cluster differently from immobility events on those axes, and you want to see whether you're admitting a genuinely new population or just adding noise.
- Whatever you pick, **don't compare ripple rates across sessions / animals with different `speed_threshold` values** — it's a hidden confound. Document the value alongside any rate or count statistic.

## How to set a non-default value

`RippleParameters` is a Lookup with primary key `ripple_param_name`. Don't mutate `"default"` — insert a new named row:

```python
from spyglass.ripple.v1 import RippleParameters

RippleParameters.insert1({
    "ripple_param_name": "speed10_zscore2",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 10.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 2.0,
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})
```

Then pass `ripple_param_name="speed10_zscore2"` in your `RippleTimesV1.populate()` key. This keeps the default preset clean for comparison and makes the parameter choice traceable in the database.
