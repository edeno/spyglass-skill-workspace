# Not good to go — three independent problems with that plan

I'd push back on this for three reasons before you run `RippleParameters.insert1(...)`. Two of them are mechanical (will break or silently corrupt your DB), one is hygiene (will burn you in 6 months).

---

## 1. "Their analyses looked good" is not evidence these values are right *for your experiment*

You said you don't know what the fields do. That's the actual problem — not the values. If the populate fails, or a reviewer asks "why a 2.0 z-score and not 3.0?", "looked good in another lab" isn't a defense. Here's what each field in that blob actually controls for the Kay detector:

- **`speed_threshold: 4.0`** (cm/s) — animal must be moving *slower* than this for a candidate ripple epoch to count. This is the standard "ripples happen during immobility / quiet wakefulness / SWS" gate. If your animal is doing a running task and you want only awake-immobile ripples, 4 cm/s is reasonable; if you're studying ripples during locomotion (rare, but a real research question), this filter will throw away every event you care about.
- **`zscore_threshold: 2.0`** (std) — the band-power (ripple-band envelope) cutoff that defines an event. Lower = more events including weaker/noisier ones; higher (e.g. 3 or 4 std) = stricter, fewer false positives but you miss small ripples. 2.0 is on the permissive end; some labs use 3.0.
- **`minimum_duration: 0.015`** (sec, = 15 ms) — events shorter than this are discarded. Filters out single-cycle blips. Standard ripples are ~50–100 ms, so 15 ms is a generous floor.
- **`smoothing_sigma: 0.004`** (sec, = 4 ms) — Gaussian smoothing window applied to the ripple-band envelope before thresholding. Trades temporal precision for noise robustness.
- **`close_ripple_threshold: 0.0`** (sec) — if two detected events are closer than this, they get merged into one. `0.0` means "don't merge anything." Some pipelines set this to e.g. 15–30 ms to coalesce flicker.
- **`speed_name: 'head_speed'`** — names the upstream speed attribute the detector pulls from the position pipeline. Has to match what your position table actually exposes (`head_speed` vs. `speed` vs. `nose_speed`, etc.).
- **`ripple_detection_algorithm: 'Kay_ripple_detector'`** — picks the detector. The other commonly available one is `Karlsson_ripple_detector`. They use different reference signals and will not give identical events.

One thing **not** in the blob that you might expect: `sampling_frequency`. The `RippleTimesV1.make()` body pulls it from `LFPBandV1.lfp_band_sampling_rate` at populate time (`ripple/v1/ripple.py` around line 286), so it's tracked through the upstream key — you don't set it here.

If you can't paraphrase the bullets above for your own experiment, read `RippleParameters.insert_default` in `src/spyglass/ripple/v1/ripple.py` (around line 144) and the `make()` body of `RippleTimesV1` to see how each field flows in. The Kay algorithm itself lives in the upstream `ripple_detection` package.

## 2. `ripple_param_name='default'` collides with a shipped row

This is the hard mechanical problem. `RippleParameters.insert_default()` already inserts a row with `ripple_param_name='default'` containing **literally the same blob** your labmate sent (`Kay_ripple_detector`, `speed_threshold=4.0`, `zscore_threshold=2.0`, `minimum_duration=0.015`, `smoothing_sigma=0.004`, `close_ripple_threshold=0.0`). You can verify against `ripple/v1/ripple.py:144-159`.

So one of two things will happen when you `insert1`:

- **With `skip_duplicates=True`**: insert silently no-ops. You think you've registered a custom param set; you actually haven't. Any later edit to your local copy diverges from what's in the DB and you won't notice.
- **With `skip_duplicates=False`** (or default): you get a `DuplicateError`, or — if you used `replace=True` — you overwrite the shipped `default` row, which is now a footgun for everyone else in the lab who assumes `default` means "the canonical Kay defaults."

Either way: don't use the name `'default'`. It's a reserved-by-convention slot.

## 3. Even without the collision, `'default'` is a bad name

`ripple_param_name` is a primary key you'll be reading in `fetch1` calls and grepping for in old notebooks years from now. `'default'` is meaningless on inspection — you can't tell from the name what algorithm or thresholds it points at. Pick a self-describing name that encodes the salient choices:

```
'kay_speed4_zscore2'
```

or, if you want to be more explicit:

```
'kay_speed4_zscore2_dur15ms'
```

When you (or a labmate) later `restrict` on this name, the answer to "what params did I use?" is in the name itself, not behind another table lookup.

## 4. Pre-insert: search before you insert

Before inserting anything, check whether an equivalent param set already exists in your lab's `RippleParameters` under some other name. The fields are the same blob; only `ripple_param_name` differs. Something like:

```python
import pandas as pd
existing = pd.DataFrame(RippleParameters.fetch())
# inspect existing['ripple_params'] for blobs equal to your candidate
```

If a labmate already inserted this exact dict as `'kay_default_v1'` or whatever, just use their key instead of adding a near-duplicate. Param-table sprawl is a real maintenance cost.

---

## Concrete recommendation

1. Read `RippleParameters.insert_default()` and the `RippleTimesV1.make()` body so you can defend each field.
2. Search existing `RippleParameters` rows for an equal blob — reuse if one exists.
3. If you still need to insert, use a self-describing name like `'kay_speed4_zscore2'`, **not** `'default'`.
4. Confirm `speed_name='head_speed'` matches the attribute your position pipeline actually exposes for your sessions (this is lab/setup-specific).

Then you're good to go.
