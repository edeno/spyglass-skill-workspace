# Running LFP V1 + LFPBand V1 for theta on `j1620210710_.nwb`

Theta power requires *two* pipeline stages, not one:

1. **`LFPV1`** — wideband filter on the raw recording (e.g. `LFP 0-400 Hz`), downsampled to 1 kHz. This is the "LFP pipeline" people usually mean.
2. **`LFPBandV1`** — band filter (`Theta 5-11 Hz`) applied to the merge entry produced by `LFPV1`. Theta power = `|hilbert(theta_band)|²`, which `LFPBandV1.compute_signal_power(...)` computes for you.

Apply the theta filter only at the band step. Putting `Theta 5-11 Hz` into `LFPSelection` is wrong — that step expects the wideband filter and will fail or give you something useless.

Below is the full flow specialized to your case: tetrodes 4, 5, 12, the `sleep` interval, default filter for the wideband step.

---

## Pre-flight: confirm rates, intervals, and filters exist

```python
import numpy as np
from spyglass.common import (
    Electrode, ElectrodeGroup, FirFilterParameters, IntervalList, Raw,
)

nwb_file = "j1620210710_.nwb"

# (a) Confirm 'sleep' is an actual interval_name on this session.
#     LFPSelection.insert1 will raise a cryptic FK error if it isn't.
print((IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_name"))

# (b) Get the raw sampling rate — the wideband filter is keyed on
#     (filter_name, filter_sampling_rate). Don't hardcode 30000.
raw_rate = int(np.round(
    (Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")
))
print("raw rate:", raw_rate)  # typically 20000 or 30000

# (c) Make sure the canonical 'LFP 0-400 Hz' rows are inserted.
#     create_standard_filters ships rows for both 20 kHz and 30 kHz raw rates.
FirFilterParameters().create_standard_filters()
assert FirFilterParameters & {
    "filter_name": "LFP 0-400 Hz", "filter_sampling_rate": raw_rate,
}, "no LFP 0-400 Hz filter for this raw rate"
```

---

## Step 1: Find the electrode_ids for tetrodes 4, 5, 12

In Spyglass, "tetrode N" maps to `electrode_group_name = "N"` and four `electrode_id` rows in `Electrode`.

```python
tetrodes = ["4", "5", "12"]   # electrode_group_name is varchar
electrode_ids = (
    Electrode
    & {"nwb_file_name": nwb_file}
    & [{"electrode_group_name": g} for g in tetrodes]
).fetch("electrode_id").tolist()
print(electrode_ids)          # expect 12 ids (4 channels × 3 tetrodes)
```

Sanity check: count should be `4 × len(tetrodes)`. If not, the recording either doesn't have those groups or has dead/dropped channels — inspect `Electrode & {"nwb_file_name": nwb_file}` before continuing.

---

## Step 2: Define the LFPElectrodeGroup

```python
from spyglass.lfp import LFPElectrodeGroup, LFPOutput
from spyglass.lfp.v1 import LFPSelection, LFPV1

LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name="sleep_t04_05_12",
    electrode_list=electrode_ids,
)
```

This populates `LFPElectrodeGroup` (master) and `LFPElectrodeGroup.LFPElectrode` (one row per `electrode_id`).

---

## Step 3: Insert LFPSelection + populate LFPV1 (wideband)

```python
lfp_sel_key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "sleep_t04_05_12",
    "target_interval_list_name": "sleep",
    "filter_name": "LFP 0-400 Hz",        # wideband filter — NOT a theta filter
    "filter_sampling_rate": raw_rate,     # MUST match Raw's rate
    "target_sampling_rate": 1000,         # downsample to 1 kHz LFP
}
LFPSelection.insert1(lfp_sel_key, skip_duplicates=True)
LFPV1.populate(lfp_sel_key, display_progress=True)
```

Why these values:

- `filter_sampling_rate` keys `FirFilterParameters` jointly with `filter_name`. If it doesn't equal the raw rate, the filter lookup misses and `make()` raises.
- `target_sampling_rate=1000` is the canonical LFP rate. It must satisfy `target > 2 × highcut` (for `LFP 0-400 Hz` that means `> 800`); 1000 is the standard choice and is what the band step downstream expects.

---

## Step 4: Resolve the LFPOutput merge_id (a UUID, not a dict)

```python
lfp_merge_id = LFPOutput.merge_get_part(lfp_sel_key).fetch1("merge_id")
# lfp_merge_id is now a uuid.UUID scalar — that's what set_lfp_band_electrodes wants.
```

Common bug to avoid: do **not** pass `LFPOutput.merge_get_part(lfp_sel_key).fetch1("KEY")` (the full PK dict) as `lfp_merge_id`. The kwarg expects the bare merge_id UUID. Passing a dict raises a DataJoint type error.

If you also need the full merge key for fetching the wideband DataFrame later, use:

```python
merge_key = LFPOutput.merge_get_part(lfp_sel_key).fetch1("KEY")
lfp_df_wideband = (LFPOutput & merge_key).fetch1_dataframe()
```

---

## Step 5: Register the theta filter (once per site)

The `Theta 5-11 Hz` filter is **not** shipped by `create_standard_filters()` — only the broadband `LFP 0-400 Hz` is. Insert it once if it's missing. The `fs` argument must match `LFPV1`'s `target_sampling_rate` (1000 Hz) because `LFPBandSelection` will look the band filter up by `(filter_name, filter_sampling_rate=1000)`.

```python
if not (FirFilterParameters
        & {"filter_name": "Theta 5-11 Hz", "filter_sampling_rate": 1000}):
    FirFilterParameters().add_filter(
        filter_name="Theta 5-11 Hz",
        fs=1000.0,
        filter_type="bandpass",
        band_edges=[4, 5, 11, 12],
        comments="theta band for 1 kHz LFP",
    )
```

---

## Step 6: LFPBandSelection — register band electrodes for the `sleep` interval

Use the `set_lfp_band_electrodes` helper (preferred over manual `insert1` because it also populates the `.LFPBandElectrode` part table). All seven kwargs below are the actual signature in `lfp/analysis/v1/lfp_band.py`:

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1

LFPBandSelection().set_lfp_band_electrodes(
    nwb_file_name=nwb_file,
    lfp_merge_id=lfp_merge_id,            # UUID scalar from Step 4
    electrode_list=electrode_ids,         # subset of the LFPV1 electrodes is OK
    filter_name="Theta 5-11 Hz",
    interval_list_name="sleep",           # REQUIRED — no default
    reference_electrode_list=-1,          # exact kwarg name; -1 = no reference
    lfp_band_sampling_rate=1000,          # 1 kHz in, 1 kHz out — no further downsample
)
```

Three things this step is strict about, all of which match real footguns the helper validates:

- `interval_list_name` has **no default** — omit it and you get a `TypeError: missing required argument`. It must already exist in `IntervalList` for this NWB file (you confirmed `"sleep"` in pre-flight).
- The kwarg is `reference_electrode_list` (note `_list`), **not** `reference_electrodes` or `reference_electrode`. `-1` means "no reference"; alternatively pass a list the same length as `electrode_list` of per-channel reference electrode_ids.
- `lfp_band_sampling_rate=1000` keeps the band stream at the LFP rate. Setting it lower would downsample again; the band's high cutoff (11 Hz) makes that safe Nyquist-wise, but you typically want to keep 1 kHz so the Hilbert-derived phase/power is well-resolved.

---

## Step 7: Populate LFPBandV1

`LFPBandSelection`'s primary key is wider than `(lfp_merge_id, filter_name)` — it also keys on `filter_sampling_rate`, `target_interval_list_name`, and `lfp_band_sampling_rate`. Don't restrict `populate` by only the first two; pull the full PK back so you don't accidentally trigger band populates for unrelated rows.

```python
band_sel_key = (LFPBandSelection & {
    "nwb_file_name": nwb_file,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "sleep",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")  # expands to the full PK incl. filter_sampling_rate

LFPBandV1.populate(band_sel_key, display_progress=True)
```

---

## Step 8: Get the band-filtered signal as a DataFrame (for theta power)

You asked for the band-filtered signal as a DataFrame; here are the two options, both returning a `pandas.DataFrame` (timestamps as index, electrode columns):

```python
# (a) The band-filtered (real-valued) theta signal — directly what you asked for.
theta_df = (LFPBandV1 & band_sel_key).fetch1_dataframe()
print(theta_df.shape, theta_df.columns.tolist()[:4])

# (b) Theta power directly (|hilbert|²) — skip computing it yourself.
#     Note: compute_signal_power is an *instance* method that uses self,
#     so it MUST be called on a restricted relation, not on the bare class.
theta_power_df = (LFPBandV1 & band_sel_key).compute_signal_power(
    electrode_list=electrode_ids
)
print(theta_power_df.shape)

# (c) If you want phase too:
theta_phase_df = (LFPBandV1 & band_sel_key).compute_signal_phase(
    electrode_list=electrode_ids
)
```

If you stick with `(a)` and want power yourself, square the magnitude of the Hilbert transform: `np.abs(scipy.signal.hilbert(theta_df.values, axis=0))**2`. That's exactly what `compute_signal_power` does internally, so prefer `(b)` unless you need a custom variant.

---

## Recap — full end-to-end, just the calls

```python
# 0. Pre-flight
raw_rate = int(np.round((Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")))
FirFilterParameters().create_standard_filters()

# 1. Find electrode ids
electrode_ids = (
    Electrode & {"nwb_file_name": nwb_file}
    & [{"electrode_group_name": g} for g in ["4", "5", "12"]]
).fetch("electrode_id").tolist()

# 2. LFPElectrodeGroup
LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name="sleep_t04_05_12",
    electrode_list=electrode_ids,
)

# 3. LFPSelection + LFPV1 (wideband)
lfp_sel_key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "sleep_t04_05_12",
    "target_interval_list_name": "sleep",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": raw_rate,
    "target_sampling_rate": 1000,
}
LFPSelection.insert1(lfp_sel_key, skip_duplicates=True)
LFPV1.populate(lfp_sel_key, display_progress=True)

# 4. Resolve UUID
lfp_merge_id = LFPOutput.merge_get_part(lfp_sel_key).fetch1("merge_id")

# 5. Register theta filter at 1 kHz (once per site)
if not (FirFilterParameters
        & {"filter_name": "Theta 5-11 Hz", "filter_sampling_rate": 1000}):
    FirFilterParameters().add_filter(
        filter_name="Theta 5-11 Hz", fs=1000.0,
        filter_type="bandpass", band_edges=[4, 5, 11, 12],
    )

# 6. LFPBandSelection
LFPBandSelection().set_lfp_band_electrodes(
    nwb_file_name=nwb_file,
    lfp_merge_id=lfp_merge_id,
    electrode_list=electrode_ids,
    filter_name="Theta 5-11 Hz",
    interval_list_name="sleep",
    reference_electrode_list=-1,
    lfp_band_sampling_rate=1000,
)

# 7. LFPBandV1.populate with the FULL selection key
band_sel_key = (LFPBandSelection & {
    "nwb_file_name": nwb_file,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "sleep",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")
LFPBandV1.populate(band_sel_key, display_progress=True)

# 8. Theta DataFrame (or power directly)
theta_df       = (LFPBandV1 & band_sel_key).fetch1_dataframe()
theta_power_df = (LFPBandV1 & band_sel_key).compute_signal_power(electrode_ids)
```

---

## Failure-mode checklist

If something goes wrong, almost always one of these:

- `FK constraint failed on LFPSelection` → `'sleep'` isn't in `IntervalList` for this nwb_file, or `(filter_name, filter_sampling_rate)` isn't in `FirFilterParameters` for the raw rate.
- `LFPV1.populate` succeeds but produces no rows → `electrode_ids` was empty (groups `4 / 5 / 12` not in `Electrode`); recheck Step 1.
- `LFPBandSelection.set_lfp_band_electrodes(...)` raises `ValueError: filter ... is not in the FirFilterParameters table` → you registered the theta filter at the wrong `fs` (must be 1000, the LFP rate), not the raw rate.
- `LFPBandV1.populate(band_sel_key)` is a no-op → you used a partial restriction; `fetch1("KEY")` against the full PK fixes it.
- `compute_signal_power` raises `AttributeError: 'LFPBandV1' object has no attribute 'fetch_nwb'` or returns nothing useful → you called it on the bare class instead of on `(LFPBandV1 & band_sel_key)`. It's an instance method and needs a restricted relation.
