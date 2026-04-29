# Turning off smoothing in `TrodesPosParams` — what happens to `speed`

Short version: **you can't cleanly "turn smoothing off" via the param dict.** The pipeline treats `speed_smoothing_std_dev` as required and validates it as truthy, so setting it to `0` or `None` raises `ValueError` before any speed is computed. Setting `position_smoothing_duration = 0` separately breaks the LED moving-average step. If you really want unsmoothed speed, you need a tiny non-zero sigma, not zero.

## Where `speed` actually comes from

`TrodesPosV1.make()` delegates the math to `IntervalPositionInfo.calculate_position_info(...)` (`spyglass/position/v1/position_trodes_position.py:212`, `:251-253`). That function lives in `spyglass/common/common_position.py` and produces `speed` like this (lines 475-481):

```python
velocity = get_velocity(
    position,
    time=time,
    sigma=speed_smoothing_std_dev,
    sampling_frequency=sampling_rate,
)  # cm/s
speed = np.sqrt(np.sum(velocity**2, axis=1))  # cm/s
```

So `speed` is the L2 norm of `velocity`, and `velocity` is computed by `position_tools.get_velocity(...)` with `sigma = speed_smoothing_std_dev`. Internally `get_velocity` differentiates the centroid position and applies a Gaussian smoother of width `sigma` (in seconds).

There are actually three smoothing knobs in the default `params` dict (`spyglass/position/v1/position_trodes_position.py:68-78`):

| Param | Default | Where it acts |
|---|---|---|
| `position_smoothing_duration` | 0.125 s | Moving-average window applied to **front_LED and back_LED positions** before centroid/velocity (`common_position.py:432-438`) |
| `speed_smoothing_std_dev` | 0.100 s | Gaussian sigma inside `get_speed` (LED-speed outlier rejection) and `get_velocity` (the velocity used for `speed`) |
| `orient_smoothing_std_dev` | 0.001 s | Gaussian sigma on unwrapped orientation (`common_position.py:458-464`) |

The one that drives the `speed` column specifically is `speed_smoothing_std_dev`.

## Why "smoothing off" isn't a free option

`calculate_position_info` first runs the parameters through `_fix_kwargs` (`common_position.py:243-276`):

```python
if not speed_smoothing_std_dev:
    speed_smoothing_std_dev = kwargs.get("head_speed_smoothing_std_dev")
...
if not all(
    [speed_smoothing_std_dev, max_LED_separation, max_plausible_speed]
):
    raise ValueError(
        "Missing at least one required parameter:\n\t"
        + f"speed_smoothing_std_dev: {speed_smoothing_std_dev}\n\t"
        ...
    )
```

Two consequences:

1. **`speed_smoothing_std_dev = 0`** is falsy. The first `if` triggers, the code looks for the legacy fallback name `head_speed_smoothing_std_dev` (which doesn't exist in `TrodesPosParams.default_params`), gets `None`, and the `not all([...])` check raises `ValueError`. `populate()` fails, no `speed` is produced.
2. **`speed_smoothing_std_dev = None`** behaves the same — falsy, fallback is `None`, `ValueError`.

So you can't disable Gaussian smoothing of velocity by zeroing this field — you'll never reach the speed computation.

## What about `position_smoothing_duration = 0`?

That one is also load-bearing earlier in the pipeline (`common_position.py:432-438`):

```python
moving_average_window = int(position_smoothing_duration * sampling_rate)
back_LED  = bottleneck.move_mean(back_LED,  window=moving_average_window, axis=0, min_count=1)
front_LED = bottleneck.move_mean(front_LED, window=moving_average_window, axis=0, min_count=1)
```

With `position_smoothing_duration = 0`, `moving_average_window = 0`, which `bottleneck.move_mean` rejects (window must be ≥ 1). So this also crashes `populate()` rather than producing an "unsmoothed" `speed`.

If it *did* succeed (e.g. you set it to a single-sample value), the LED traces would be the raw, jittery LED reads. `speed` would inherit that jitter through the centroid → `get_velocity` chain — much noisier, with frame-to-frame spikes that the 0.125 s moving average normally absorbs.

## What "minimally smoothed" looks like in practice

If your goal is "as little smoothing as the pipeline allows":

```python
TrodesPosParams.insert1({
    "trodes_pos_params_name": "minimal_smoothing",
    "params": {
        **TrodesPosParams().default_params,
        "position_smoothing_duration": 1 / sampling_rate,  # one-sample window
        "speed_smoothing_std_dev": 1e-6,                   # tiny but truthy
        "orient_smoothing_std_dev": 1e-6,
    },
}, skip_duplicates=True)
```

Pick `speed_smoothing_std_dev` such that `sigma * sampling_rate` is on the order of one sample — at typical 30 Hz tracking that means roughly 0.03 s or smaller. Anything smaller is fine numerically and just makes the Gaussian kernel near-delta-like. The result: `speed` will track the raw LED differences much more closely, including any 1-frame jumps.

## Practical recommendation

The defaults exist for a reason — at 30 Hz tracking with LED dropouts, raw-difference speed is dominated by digitization and missed frames, not animal motion. Before turning smoothing off for real analysis:

1. Run the default params on one interval, fetch via `PositionOutput.merge_get_part(key).fetch1("KEY")` → `(PositionOutput & merge_key).fetch1_dataframe()`, and plot `speed` vs `time`.
2. Insert a second `TrodesPosParams` row with the "minimal smoothing" values above (under a *new* `trodes_pos_params_name`, never overwrite `default`), populate `TrodesPosV1` for the same interval with that name, and overlay both `speed` traces.
3. Decide based on the comparison whether the high-frequency content you've recovered is signal you care about (e.g. fine head jitter, sniffing-coupled motion) or just LED noise. Most behavioural analyses (place fields, ripple-state classification, MUA gating on running) want the smoothed default; downstream code that thresholds on speed will misbehave if you feed it the raw version.

## Source references

- `spyglass/position/v1/position_trodes_position.py:24-103` — `TrodesPosParams` definition, `default_params`, `insert_default`.
- `spyglass/position/v1/position_trodes_position.py:192-253` — `TrodesPosV1.make` and the static `calculate_position_info` delegate.
- `spyglass/common/common_position.py:243-276` — `_fix_kwargs`, the truthy validation that blocks `speed_smoothing_std_dev = 0/None`.
- `spyglass/common/common_position.py:406-481` — full pipeline from LED→speed, including the two smoothing steps.
