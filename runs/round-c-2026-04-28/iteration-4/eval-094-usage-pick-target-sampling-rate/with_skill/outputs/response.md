# Pick `target_sampling_rate = 1000` (Hz)

That is the canonical Spyglass LFP rate, and it is the right choice for downstream ripple-band (150-250 Hz) analysis.

## Why 1000 Hz

There are three sampling-rate fields in the LFP stack and they interact strictly. Picking `target_sampling_rate` arbitrarily is the most common mis-configuration here.

The relevant constraints (from `skills/spyglass/references/lfp_pipeline.md` "Nyquist note", and the LFPBandSelection FK at `src/spyglass/lfp/analysis/v1/lfp_band.py:25-26`):

1. **`target_sampling_rate` must strictly exceed 2 x the LFP filter's high cutoff.** With the shipped `"LFP 0-400 Hz"` broadband filter, the high cutoff is 400 Hz, so `target_sampling_rate > 800`. 1000 Hz clears this and is what `create_standard_filters()` (`src/spyglass/common/common_filter.py:577`) is designed around.

2. **The downstream band filter must be registered at a `fs` matching `LFPV1`'s `target_sampling_rate`.** When you later run `LFPBandV1` for ripple, you will register `"Ripple 150-250 Hz"` via `FirFilterParameters().add_filter(..., fs=1000.0, band_edges=[140, 150, 250, 260], filter_type="bandpass")`. `FirFilterParameters` is keyed on `(filter_name, filter_sampling_rate)` — a filter registered at one rate will not apply to a stream at another rate. If you set `target_sampling_rate=1000` here, the conventional ripple filter just works.

3. **The band's high cutoff (250 Hz, plus a 260 Hz transition edge) must be strictly below Nyquist of the LFP stream (500 Hz at 1 kHz LFP).** 260 Hz < 500 Hz — fine.

So 1000 Hz comfortably satisfies Nyquist for both the broadband 0-400 Hz filter and the 150-250 Hz ripple band, and it matches the conventional `"Ripple 150-250 Hz"` / `"Theta 5-11 Hz"` filter registrations used across Frank Lab scripts.

## What this looks like in code

```python
import numpy as np
from spyglass.common import FirFilterParameters, Raw
from spyglass.lfp.v1 import LFPSelection, LFPV1

FirFilterParameters().create_standard_filters()  # ensures 'LFP 0-400 Hz' exists

raw_sampling_rate = int(np.round(
    (Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")
))  # derive, do not hard-code 30000

key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "my_lfp_group",
    "target_interval_list_name": "02_r1",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": raw_sampling_rate,  # match the raw rate (often 20k or 30k)

    "target_sampling_rate": 1000,               # <-- this is the answer
}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)
```

## Could you go higher (e.g., 2000 Hz)?

You technically can — anything > 800 Hz satisfies Nyquist for the broadband filter, and anything > 520 Hz would satisfy Nyquist for the ripple band edges alone. But:

- The shipped `"LFP 0-400 Hz"` filter is registered at `filter_sampling_rate` = 20 kHz / 30 kHz only (raw rates), and `target_sampling_rate` is the *output* rate, so any value > 800 is mechanically legal at the LFPV1 step.
- However, downstream you would then need to register `"Ripple 150-250 Hz"` at `fs=2000.0` instead of the conventional `fs=1000.0`, and `LFPBandSelection.lfp_band_sampling_rate` would have to match. You would be diverging from the lab convention with no analytical benefit at 150-250 Hz (Nyquist at 1 kHz is 500 Hz — already 2x your highest band edge).

Pick 1000 Hz unless you have a specific reason to deviate (e.g., you are also chasing a high-gamma / fast-ripple band > 500 Hz in the same stream, in which case bump to 2000 Hz and re-register all band filters at `fs=2000.0`).

## Filename note for the ripple step

Heads-up for when you set up the ripple band downstream: `RippleLFPSelection.validate_key` rejects `LFPBandV1` rows whose `filter_name` does not contain `"ripple"` (case-insensitive). Name the band filter `"Ripple 150-250 Hz"` (the lab convention), not e.g. `"150-250 Hz bandpass"`, or the ripple selection step will reject it.

## Sources

- `skills/spyglass/references/lfp_pipeline.md` — "Nyquist note on filter/sampling-rate fields" (the rule `target_sampling_rate > 2 x filter high-cutoff`, and the matched-rate requirement between `LFPV1.target_sampling_rate` and the band filter's `fs`).
- `skills/spyglass/references/lfp_pipeline.md` — Step 4 canonical band-filter example: `fs=1000.0`, `band_edges=[140, 150, 250, 260]`, `lfp_band_sampling_rate=1000`.
- `src/spyglass/common/common_filter.py:577` — `create_standard_filters()` ships `"LFP 0-400 Hz"`.
- `src/spyglass/lfp/v1/lfp.py:72-75, 107-109` — `LFPV1.make()` looks up `FirFilterParameters` by `(filter_name, filter_sampling_rate)`.
- `src/spyglass/lfp/analysis/v1/lfp_band.py:25-26` — `LFPBandSelection` FKs `LFPOutput.proj(lfp_merge_id='merge_id')`; the band filter must be registered at the LFP's output rate.
