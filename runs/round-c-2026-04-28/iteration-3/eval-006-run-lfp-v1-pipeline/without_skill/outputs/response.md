# Running the Spyglass LFP pipeline on the `sleep` interval and getting theta-band data out

Below is the end-to-end flow. The short version: there are **two pipelines** you need, not one. Spyglass splits "wideband LFP" (`LFPV1`) from "narrow-band filtering of the LFP" (`LFPBandV1`). Theta is a band, so you have to go all the way through to `LFPBandV1` — `LFPV1.fetch1_dataframe()` would just give you the broadband 0–400 Hz signal, not theta.

Here is the full path with code.

---

## 0. Imports and the session you've already ingested

```python
import datajoint as dj
import numpy as np

from spyglass.common import (
    Electrode,
    ElectrodeGroup,
    IntervalList,
    FirFilterParameters,
)
from spyglass.lfp.lfp_electrode import LFPElectrodeGroup
from spyglass.lfp.v1.lfp import LFPSelection, LFPV1
from spyglass.lfp.lfp_merge import LFPOutput
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1

nwb_file_name = "j1620210710_.nwb"
interval_name = "sleep"   # the IntervalList name you said you want
```

Quick sanity check that ingestion actually went through and that the `sleep` interval exists:

```python
(IntervalList & {"nwb_file_name": nwb_file_name,
                 "interval_list_name": interval_name})
```

If that's empty, the pipeline will fail later — you want to fix it now.

---

## 1. Resolve "tetrodes 4, 5, 12" to actual `electrode_id` values

Tetrode numbers are *electrode group* numbers, not electrode IDs. Each tetrode usually has 4 channels with their own `electrode_id`s. Pull them from `Electrode`:

```python
target_groups = [4, 5, 12]   # tetrode numbers

electrode_ids = (
    Electrode
    & {"nwb_file_name": nwb_file_name}
    & [{"electrode_group_name": str(g)} for g in target_groups]
).fetch("electrode_id")

electrode_ids = sorted(int(e) for e in electrode_ids)
print(electrode_ids)   # e.g. [16, 17, 18, 19, 20, 21, 22, 23, 48, 49, 50, 51]
```

`electrode_group_name` in `Electrode` is a string in Spyglass even when the underlying group is numeric, so the cast in the restriction matters.

If you want to LFP only one channel per tetrode (common — the rest are redundant for slow rhythms), just pick the first id in each group instead of all four.

---

## 2. Make an `LFPElectrodeGroup` that contains those channels

`LFPElectrodeGroup` is the table that says "these are the channels we'll filter for LFP". There's a static helper for inserting it:

```python
group_name = "tetrodes_4_5_12_sleep"

LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file_name,
    group_name=group_name,
    electrode_list=electrode_ids,
)
```

This inserts the master row in `LFPElectrodeGroup` and one row per electrode in the `LFPElectrodeGroup.LFPElectrode` part table.

---

## 3. Pick the wideband LFP filter

Spyglass ships a default wideband filter named **`LFP 0-400 Hz`** in `FirFilterParameters`. It has to exist *for the raw sampling rate of this session* (the row is keyed by `(filter_name, filter_sampling_rate)`):

```python
raw_rate = (
    dj.U("sampling_rate")
    & (Electrode & {"nwb_file_name": nwb_file_name})  # or fetch from Raw
).fetch1("sampling_rate")

filter_name = "LFP 0-400 Hz"

assert FirFilterParameters & {
    "filter_name": filter_name,
    "filter_sampling_rate": int(raw_rate),
}, "Default LFP filter not found for this sampling rate – insert it first."
```

If the assert trips, the standard demo notebooks (`02_LFP.ipynb`) show how to insert the default filter via `FirFilterParameters().add_filter(...)`.

**Important:** this is the *wideband* filter. Don't put a theta filter here — the wideband output is the input to the band stage, and you want the full 0–400 Hz band preserved at this point.

---

## 4. Insert the `LFPSelection` row and populate `LFPV1`

`LFPSelection` is the manual table that joins the electrode group, the interval, and the filter:

```python
lfp_sel_key = {
    "nwb_file_name": nwb_file_name,
    "lfp_electrode_group_name": group_name,
    "target_interval_list_name": interval_name,    # 'sleep'
    "filter_name": filter_name,                    # 'LFP 0-400 Hz'
    "filter_sampling_rate": int(raw_rate),
    # target_sampling_rate defaults to 1000 Hz; override if you want
}

LFPSelection.insert1(lfp_sel_key, skip_duplicates=True)

LFPV1.populate(lfp_sel_key)
```

`LFPV1.populate` reads the raw NWB ephys, applies the FIR filter, decimates to `target_sampling_rate` (default 1000 Hz), writes an analysis NWB file, and inserts the row into `LFPV1`. It also inserts a master entry into `LFPOutput` (the merge table) so downstream pipelines can refer to it by a single UUID.

You can sanity-check it landed:

```python
(LFPV1 & lfp_sel_key)
(LFPOutput.LFPV1 & lfp_sel_key)
```

---

## 5. Resolve the `LFPOutput` merge UUID

Downstream pipelines (band, ripple, etc.) don't take an `LFPV1` key — they take the **merge UUID** out of `LFPOutput`. Use `merge_get_part` to walk from the upstream key to the part-table row, and grab the `merge_id`:

```python
lfp_merge_id = (LFPOutput.merge_get_part(lfp_sel_key)).fetch1("merge_id")
```

This is a single `UUID` scalar, which is what `set_lfp_band_electrodes` wants for `lfp_merge_id`. Don't pass `fetch1('KEY')` — that's a dict and won't be accepted as a primary-key value.

---

## 6. Make sure a theta filter exists in `FirFilterParameters`

The band stage takes the *LFP* sampling rate as its filter sampling rate (1000 Hz by default — whatever you set for `target_sampling_rate` in step 4), not the raw rate. Spyglass usually ships a `Theta 5-11 Hz` filter at 1000 Hz, but check:

```python
band_filter_name = "Theta 5-11 Hz"
lfp_rate = int((LFPV1 & lfp_sel_key).fetch1("lfp_sampling_rate"))

assert FirFilterParameters & {
    "filter_name": band_filter_name,
    "filter_sampling_rate": lfp_rate,
}, "Theta filter not present at the LFP sampling rate – insert it first."
```

If it's missing, insert it via `FirFilterParameters().add_filter(...)` (passband 5–11 Hz, stopbands 4 and 12 Hz, sampling rate `lfp_rate`) before continuing.

---

## 7. Fill `LFPBandSelection` with `set_lfp_band_electrodes`

This is a helper method on `LFPBandSelection` that does the master + part-table insert in one call:

```python
LFPBandSelection().set_lfp_band_electrodes(
    nwb_file_name=nwb_file_name,
    lfp_merge_id=lfp_merge_id,
    electrode_list=electrode_ids,             # same channels as before, or a subset
    filter_name=band_filter_name,             # 'Theta 5-11 Hz'
    interval_list_name=interval_name,         # 'sleep' – required, no default
    reference_electrode_list=-1,              # -1 = no re-referencing; or list aligned to electrode_list
    lfp_band_sampling_rate=lfp_rate,          # keep equal to LFP rate to avoid aliasing
)
```

A few things that bite people here:

- The kwarg is **`reference_electrode_list`** with `_list` at the end, not `reference_electrode` or `reference_electrodes`. `-1` (or a 1-element list with `-1`) means "no reference" for every electrode; otherwise pass a list the same length as `electrode_list` with one ref electrode id per channel.
- `interval_list_name` has no default — you must pass it, even though `LFPBandSelection` already inherits an interval through `LFPOutput`.
- `lfp_band_sampling_rate` must be ≤ the LFP sampling rate, and decimation is `lfp_rate // lfp_band_sampling_rate` (integer). Easiest is to set it equal to the LFP rate.

---

## 8. Populate `LFPBandV1`

The corresponding key for population is the master key built by `set_lfp_band_electrodes`:

```python
band_key = {
    "nwb_file_name": nwb_file_name,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": band_filter_name,
    "filter_sampling_rate": lfp_rate,
    "target_interval_list_name": interval_name,
    "lfp_band_sampling_rate": lfp_rate,
}

LFPBandV1.populate(band_key)
```

---

## 9. Pull the band-filtered signal out as a DataFrame

`LFPBandV1` exposes `fetch1_dataframe()`, which returns a tidy `(time × electrode)` DataFrame indexed by timestamp:

```python
theta_df = (LFPBandV1 & band_key).fetch1_dataframe()
theta_df.head()
#                          electrode 16  electrode 17  ...
# time
# 1626040320.000000           -34.5         -22.1
# 1626040320.001000           -33.9         -21.7
# ...
```

That's the theta-band-filtered LFP. From there you can compute power however you like.

### Theta power, the easy way

`LFPBandV1` already has helpers that wrap the Hilbert transform:

```python
# instantaneous theta amplitude (|Hilbert|)
analytic_df = (LFPBandV1 & band_key).compute_analytic_signal()

# instantaneous theta power (|Hilbert|^2)
theta_power_df = (LFPBandV1 & band_key).compute_signal_power()

# instantaneous phase, [0, 2*pi)
theta_phase_df = (LFPBandV1 & band_key).compute_signal_phase()
```

These are instance methods, so call them on the *restricted* relation `(LFPBandV1 & band_key)`, not on the bare class — internally they call `fetch_nwb()[0]` on a single row.

If you want a slow theta-power envelope (e.g. for sleep-state classification), smooth `theta_power_df` with a 250–500 ms rolling window:

```python
window = int(0.25 * lfp_rate)
theta_env = theta_power_df.rolling(window, center=True, min_periods=1).mean()
```

---

## Summary of the dependency chain

```
Electrode / ElectrodeGroup        (already populated by ingestion)
        |
        v
LFPElectrodeGroup (+ LFPElectrode part)        <- step 2
        |
        v
LFPSelection (electrodes + 'sleep' interval + 'LFP 0-400 Hz' filter)  <- step 4
        |
        v
LFPV1.populate  ───────────►  LFPOutput (merge table, gives merge_id) <- step 5
                                              |
                                              v
                              LFPBandSelection (+ LFPBandElectrode part)
                              via set_lfp_band_electrodes(            <- step 7
                                  lfp_merge_id, electrode_list,
                                  filter_name='Theta 5-11 Hz',
                                  interval_list_name='sleep',
                                  reference_electrode_list=-1, ...)
                                              |
                                              v
                                  LFPBandV1.populate(band_key)        <- step 8
                                              |
                                              v
                              fetch1_dataframe() / compute_signal_power()   <- step 9
```

A few last gotchas worth flagging:

- The `sleep` interval has to already be in `IntervalList` for that NWB file. If it isn't, `set_lfp_band_electrodes` will raise. Check with `(IntervalList & {"nwb_file_name": nwb_file_name, "interval_name": "sleep"})`.
- Don't stuff the theta filter into `LFPSelection` — that step is wideband only. Theta filtering belongs in `LFPBandSelection`.
- If `LFPV1.populate` succeeds but `LFPOutput.merge_get_part(...)` returns nothing, the `LFPV1.make` insert into `LFPOutput` failed; deleting and re-populating usually clears it.
- For "theta power" specifically, `compute_signal_power()` already gives you a DataFrame — you don't have to roll your own Hilbert.
