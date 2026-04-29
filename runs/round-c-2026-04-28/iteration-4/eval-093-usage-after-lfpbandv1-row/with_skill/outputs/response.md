With a populated `LFPBandV1` row for theta, the next step depends on what you want from theta — but they all reuse the same row. The four canonical things to do:

### 1. Fetch the band-filtered LFP as a DataFrame

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1

# Use the FULL selection PK to avoid grabbing other rows.
# LFPBandSelection's PK is (nwb_file_name, lfp_merge_id, filter_name,
# filter_sampling_rate, target_interval_list_name, lfp_band_sampling_rate).
band_sel_key = (LFPBandSelection & {
    "nwb_file_name": nwb_file,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "02_r1",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")

theta_df = (LFPBandV1 & band_sel_key).fetch1_dataframe()
```

### 2. Compute theta phase / power / analytic signal

These are the methods on `LFPBandV1` (`spyglass/lfp/analysis/v1/lfp_band.py`), and they're the usual reason you'd populate a band table at all:

```python
electrodes = [0, 1, 2, 3]   # subset of what you registered
analytic = (LFPBandV1 & band_sel_key).compute_analytic_signal(electrode_list=electrodes)
phase    = (LFPBandV1 & band_sel_key).compute_signal_phase(electrode_list=electrodes)   # 0 to 2π
power    = (LFPBandV1 & band_sel_key).compute_signal_power(electrode_list=electrodes)   # |z|²
```

Typical follow-ups: phase-lock spike trains to theta, segment running vs. immobility by theta power, compute theta-gamma coupling, etc.

### 3. Sanity-check before you trust the row

A `populate()` that returned without error doesn't guarantee the row is what you think. Two cheap checks:

```python
# (a) Cardinality is exactly 1 — partial restrictions silently match >1.
print(len(LFPBandV1 & band_sel_key))   # expect 1

# (b) Sampling rate and shape match expectations.
print(theta_df.shape, 1 / (theta_df.index[1] - theta_df.index[0]))
# expect ~1000 Hz given lfp_band_sampling_rate=1000
```

If `len != 1`, expand `band_sel_key` until it is — this is the pre-`fetch1` cardinality loop the skill warns about.

### 4. Use it as input to ripple detection — but only if you actually filtered for ripples

This is a common "next thing" mistake worth flagging: `RippleLFPSelection` FKs to `LFPBandV1`, but `validate_key` rejects rows whose `filter_name` does not contain `"ripple"` (see `references/lfp_pipeline.md` and `references/ripple_pipeline.md`). A theta-band row (`"Theta 5-11 Hz"`) is **not** a valid input to the ripple pipeline. For ripples, you'd populate a **second** `LFPBandV1` row with `filter_name="Ripple 150-250 Hz"` from the same upstream `LFPOutput` merge entry.

---

**Most likely "next thing"**: option 2 — call `compute_signal_phase` / `compute_signal_power` on the electrodes you care about. That's the whole reason theta-band populate exists; the row itself is just an intermediate.
