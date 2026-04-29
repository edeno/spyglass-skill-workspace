# What `speed_threshold` does in `RippleParameters`

## Where it lives

In a `RippleParameters` row, `speed_threshold` lives inside the nested `ripple_param_dict["ripple_detection_params"]` blob:

```python
{
    "speed_name": "head_speed",                  # or "speed" for the trodes preset
    "ripple_detection_algorithm": "Kay_ripple_detector",
    "ripple_detection_params": {
        "speed_threshold": 4.0,                  # cm/s  <-- this one
        "minimum_duration": 0.015,               # sec
        "zscore_threshold": 2.0,                 # std
        "smoothing_sigma": 0.004,                # sec
        "close_ripple_threshold": 0.0,           # sec
    },
}
```

It is consumed inside `RippleTimesV1.make()` at `src/spyglass/ripple/v1/ripple.py:146` and `:219` and passed straight through to the underlying `ripple_detection` package's `Kay_ripple_detector` / `Karlsson_ripple_detector`.

## What it actually does

`speed_threshold` is the **immobility cutoff** that gates which candidate ripples are kept. The detector takes the speed series named by `speed_name` (column from the `PositionOutput` dataframe — `"head_speed"` for DLC/Kalman-smoothed presets, `"speed"` for the Trodes preset) and, for every candidate ripple-band power excursion, checks the animal's speed at the start and end of that candidate.

A candidate is kept only when the **immobility condition holds at both endpoints**, i.e. `speed <= speed_threshold` at the start AND at the end of the event. Candidates that start or end while the animal is moving faster than the threshold are dropped.

So `speed_threshold` is **not** a power threshold and not the thing that decides "is this big enough to be a ripple" — that's `zscore_threshold` (default 2.0 SD). `speed_threshold` is purely a behavioral state filter on top of those z-scored candidates.

## Direction: 4 → 10 cm/s

Bumping `speed_threshold` from 4.0 to 10.0 cm/s **loosens** the immobility filter, so you keep **more** candidate events. Specifically, every candidate whose start/end speeds fall in the (4, 10] cm/s window — which previously got rejected for "too fast" — will now pass the gate. You only ever add events; you never lose any, because every event that passed at 4 cm/s also passes at 10 cm/s.

(The converse: if you want fewer, cleaner SWRs, **lower** the threshold, e.g. to 2 cm/s.)

## Quality tradeoff

The reason the default is 4 cm/s and not 10 cm/s is that the canonical sharp-wave ripple is a hippocampal phenomenon of quiet wakefulness / consummatory behavior / NREM — i.e. immobility. Other things in the 150–250 Hz LFP band look ripple-like but are not classical SWRs:

- **Movement / running artifact.** Cable motion, EMG bleed-through, and head-bumps inject broadband high-frequency power that the band-pass filter can't distinguish from a real ripple. These get worse with speed.
- **Theta-associated high-gamma.** During locomotion, hippocampus is in theta state, with prominent fast-gamma (~60–120 Hz) and a weaker high-frequency tail that can cross the z-score threshold occasionally — but these are not SWRs and they ride on different network dynamics (CA3 input gating differs from the SPW-R "off-line" regime).
- **Type-2 / "movement" ripples.** Even some genuine high-frequency events that occur peri-movement have different physiology and likely different downstream consequences than the classic immobility SWR.

By raising the threshold to 10 cm/s, you are saying "I'm willing to call events ripples even when the animal was moving at a slow walk at the start or end of the event." Practical consequences:

- **More events overall**, including a non-trivial fraction that are peri-movement and that many in the field would not classify as SWRs.
- **Higher false-positive rate** for downstream analyses that assume an immobility / off-line state — replay decoding, reactivation, memory-consolidation analyses. If you condition behavior on "ripple time" and your ripple times include slow-walk events, you've contaminated your "off-line" set.
- **Lower miss rate** for events that genuinely happen at the boundary of immobility (e.g. the animal pauses at a reward well, gets a ripple, then starts moving again before the event ends — a 4 cm/s gate can clip these because the *end* speed is above threshold). If your concern is missing these boundary events, raising the threshold helps; but the cleaner fix is usually a small bump (4 → 5 or 6), not 10.
- **Interaction with `speed_name`.** The threshold is in the units of whichever speed column you named. `head_speed` (DLC head-marker speed) tends to be a bit jitterier than centroid `speed`; if you switch from `default` to `default_trodes` (or vice versa) you may need a different absolute number to mean the same behavioral state.

## Recommendation

- Default `4.0` cm/s is the standard immobility cutoff in the Frank-lab pipeline and matches most published SWR work — keep it unless you have a specific reason to deviate.
- If you genuinely need looser gating (e.g. you're studying peri-movement high-frequency events as a category), bump it deliberately and **rename the parameter row** (`ripple_param_name="permissive_10cms"` or similar) so downstream analyses don't silently mix immobility and peri-movement events under the `"default"` label.
- If you suspect you're losing real ripples at event boundaries, the more targeted fix is usually to look at `minimum_duration`, `smoothing_sigma`, or the speed signal itself (Kalman-smoothed vs raw), not to widen the speed gate to 10 cm/s.

## Sources

- `skills/spyglass/references/ripple_pipeline.md` — `RippleParameters` semantics, "speed_threshold (default 4.0 cm/s)" paragraph.
- `src/spyglass/ripple/v1/ripple.py:146, :219` — where `speed_threshold` is read out of `ripple_param_dict["ripple_detection_params"]` and passed to the detector.
- `src/spyglass/ripple/v1/ripple.py:9, :23` — `RIPPLE_DETECTION_ALGORITHMS` registry (`Kay_ripple_detector`, `Karlsson_ripple_detector` from the `ripple_detection` package, which is where the immobility-at-both-endpoints logic actually lives).
