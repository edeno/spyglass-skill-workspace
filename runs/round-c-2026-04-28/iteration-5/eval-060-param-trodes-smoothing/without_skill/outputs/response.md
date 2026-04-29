# What happens to `speed` when you turn smoothing off in `TrodesPosParams`?

Short answer: **the `speed` column you get out of `TrodesPosV1` is the speed of the *smoothed* position. If you disable smoothing, `speed` is computed from the raw (or only-LED-combined) centroid trace, and it will be much noisier and biased high — speed is roughly the magnitude of a numerical derivative of position, so any high-frequency jitter in the position trace shows up amplified in speed.**

## What the params actually control

`TrodesPosParams.insert_default()` writes the default param set used by `TrodesPosV1`. The dict is the kwargs that get forwarded into Trodes's `trodes_position` / `process_position` pipeline (the same code path that powers `Trodes2D`/the Trodes online position tracking, vendored through `position_tools` / `trodes_position`). The relevant fields are:

- `max_separation` and `max_speed` — outlier rejection thresholds applied to the two LEDs and to per-frame speed.
- `position_smoothing_duration` — width (in seconds) of the moving-average / low-pass filter applied to the centroid `x, y` time series.
- `speed_smoothing_std_dev` — standard deviation (in seconds) of a Gaussian smoother applied when computing speed.
- `orient_smoothing_std_dev` — same idea for head orientation.
- `led1_is_front` / `is_upsampled` / `upsampling_sampling_rate` / `upsampling_interpolation_method` — orientation convention and optional upsampling before filtering.

The pipeline order inside `_upsample` / `get_centroid_speed_orient` (in `position_tools` and Spyglass's `position.v1.position_trodes_position`) is roughly:

1. Combine the two LEDs into a single centroid (with `max_separation` masking).
2. Optionally upsample / interpolate.
3. Smooth `x, y` with a moving-average kernel of length `position_smoothing_duration * sampling_rate`.
4. Compute velocity by finite-differencing the smoothed position.
5. Smooth the *speed* magnitude with a Gaussian of std `speed_smoothing_std_dev`.

So smoothing is applied **twice and at different stages**: once on position before differencing, and once on the speed magnitude after differencing.

## What happens if you turn it off

There are two knobs and they do different things:

### 1. `position_smoothing_duration = 0` (or a value below one frame)

- The centroid `x, y` are no longer low-pass filtered before differencing.
- `speed = |d(x,y)/dt|` is computed from raw centroid samples.
- Trodes LED tracking has frame-to-frame jitter on the order of a pixel even when the animal is still. Because differentiation is a high-pass operation, that pixel jitter becomes a large *additive* speed offset.
- Concretely: a stationary animal will show a non-zero floor in `speed` (often several cm/s depending on camera resolution and `cm_per_pixel`), instead of the near-zero floor you get with smoothing on. Histograms of `speed` lose the clean "immobility peak near 0" that downstream code (ripple detection, run/rest segmentation, place-field code) usually relies on.
- Peak speeds during running can also be inflated, because the jitter rides on top of the real motion.

### 2. `speed_smoothing_std_dev = 0`

- No Gaussian smoothing of the speed magnitude. The per-frame `|Δposition| / Δt` is written straight to the `speed` column.
- Even with position smoothing on, this makes `speed` more spiky — short transients (e.g., a single-frame LED dropout that gets bridged) leak through as sharp speed peaks instead of being averaged out.

### 3. Both off

You get the rawest possible speed: derivative of unfiltered centroid, no post-smoothing. This is essentially what comes off the camera, and is almost never what you want for behavioral gating. Empirically with Trodes data this typically looks like a noisy trace with a non-zero immobility floor and lots of single-frame spikes.

## What the `speed` column is *not*

A few things worth being explicit about, because they trip people up:

- It is **2D speed in the camera plane** (cm/s if your `cm_per_pixel` and `meters_per_pixel` upstream are set correctly). It is not "running speed along the track" — for that you need the linearized pipeline (`LinearizedPositionV1`) and you compute speed from `linear_position`.
- It is the speed of the **smoothed combined centroid**, not of either individual LED. Turning smoothing off does not give you "raw LED speed"; the LED combination + outlier masking still happen.
- The smoothing is **acausal** (centered moving average / centered Gaussian), so turning it off also slightly changes timing alignment of speed peaks. With smoothing on, speed peaks are time-aligned to position peaks; with the moving average off there is no smoothing-induced delay, but also no noise rejection.

## Practical recommendations

- For ripple / immobility gating (where you typically threshold `speed < 4 cm/s`), keep smoothing on. The defaults Spyglass ships in `insert_default()` are tuned for this — they give a clean low-speed floor.
- If you need the raw kinematics (e.g., you want to do your own filter design downstream, or compare to a different speed estimator), insert a *new* param set with smoothing zeroed out and a new `trodes_pos_params_name`. Do not edit the default in place — it is referenced by other param sets and by existing `TrodesPosV1` keys.
- If you turn smoothing off, expect to add your own filter before any threshold-based behavioral segmentation, otherwise you will get spurious "movement" epochs from camera jitter.
- It is worth plotting `speed` vs time for a known-still epoch (e.g., the rat in the sleep box) before and after to see the noise floor change directly — that is the cleanest sanity check.

## How to verify on your own data

```python
from spyglass.common.common_position import TrodesPosParams
from spyglass.position.v1 import TrodesPosV1

# Inspect the defaults
print(TrodesPosParams().fetch("trodes_pos_params_name", "params", as_dict=True))

# After populating with smoothing on vs off, fetch the NWB and compare:
key_on  = {"trodes_pos_params_name": "default", ...}
key_off = {"trodes_pos_params_name": "no_smoothing", ...}

pos_on  = (TrodesPosV1 & key_on ).fetch1_dataframe()
pos_off = (TrodesPosV1 & key_off).fetch1_dataframe()

# Stationary epoch sanity check
import numpy as np
print("median speed, smoothing on :", np.median(pos_on["speed"]))
print("median speed, smoothing off:", np.median(pos_off["speed"]))
```

You should see the "off" median noticeably larger than the "on" median, and the histogram of `speed` losing its sharp zero peak.
