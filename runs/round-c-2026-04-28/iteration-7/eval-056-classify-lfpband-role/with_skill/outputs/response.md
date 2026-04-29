# `LFPBandV1` is a **compute (Computed) table**, not an output/merge table

So you should **populate it yourself** for any new band you want (theta, ripple, etc.), and then **read from it** afterward. It is not the merge layer.

## Evidence

From `spyglass/lfp/analysis/v1/lfp_band.py` (cited in the skill's LFP reference):

- `LFPBandV1` is declared as **Computed** with a `make()` method that applies a band-pass FIR filter to an upstream LFP entry. The skill's `lfp_pipeline.md` explicitly tags it: `**LFPBandV1** (Computed)`.
- It is fed by `LFPBandSelection` (Manual), whose primary key is wider than `(lfp_merge_id, filter_name)` — it also keys on `filter_sampling_rate`, `target_interval_list_name`, and `lfp_band_sampling_rate` (`lfp/analysis/v1/lfp_band.py:22-30`).
- `LFPBandSelection` foreign-keys `LFPOutput.proj(lfp_merge_id='merge_id')` (`lfp/analysis/v1/lfp_band.py:25-26`), i.e. it sits **downstream** of the `LFPOutput` merge table — confirming `LFPBandV1` is a compute step, not a merge/output node.

The merge/output node for LFP is `LFPOutput` (`merge_id` UUID, with parts `LFPOutput.LFPV1`, `LFPOutput.ImportedLFP`, `LFPOutput.CommonLFP`). `LFPBandV1` is *not* a part of any merge table — band-filtered LFP has no merge layer above it; downstream consumers (e.g. `RippleLFPSelection`) FK directly to `LFPBandV1`.

## What this means in practice

You drive it like any other compute table:

```python
from spyglass.common import FirFilterParameters
from spyglass.lfp import LFPOutput
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1

# 1. Make sure the band filter is registered (once, site-wide).
FirFilterParameters().add_filter(
    filter_name="Theta 5-11 Hz",
    fs=1000.0,                   # must match LFPV1's target_sampling_rate
    filter_type="bandpass",
    band_edges=[4, 5, 11, 12],
    comments="theta band for 1 kHz LFP",
)

# 2. Resolve the upstream LFPOutput merge_id for the LFPV1 entry you want.
lfp_merge_id = LFPOutput.merge_get_part(lfp_selection_key).fetch1("merge_id")

# 3. Insert the selection (Manual) — preferred helper populates the part table too.
LFPBandSelection().set_lfp_band_electrodes(
    nwb_file_name=nwb_file,
    lfp_merge_id=lfp_merge_id,
    electrode_list=[0, 1, 2, 3],
    filter_name="Theta 5-11 Hz",
    interval_list_name="02_r1",
    reference_electrode_list=[-1],
    lfp_band_sampling_rate=1000,
)

# 4. Populate the compute table.
band_sel_key = (LFPBandSelection & {
    "nwb_file_name": nwb_file,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "02_r1",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")  # expands to the full PK
LFPBandV1.populate(band_sel_key, display_progress=True)

# 5. Read from it.
theta_df = (LFPBandV1 & band_sel_key).fetch1_dataframe()
phase    = (LFPBandV1 & band_sel_key).compute_signal_phase(electrode_list=[0, 1, 2, 3])
power    = (LFPBandV1 & band_sel_key).compute_signal_power(electrode_list=[0, 1, 2, 3])
```

## When you'd "just read" instead

If a teammate has **already populated** `LFPBandV1` for the exact `(nwb_file_name, lfp_merge_id, filter_name, filter_sampling_rate, target_interval_list_name, lfp_band_sampling_rate)` you need, then yes — skip the `populate()` and go straight to `fetch1_dataframe()` / `compute_signal_phase` / `compute_signal_power`. Check first:

```python
LFPBandV1 & {
    "nwb_file_name": nwb_file,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "02_r1",
}
```

If a row already exists with the configuration you want, read it. If not, run `set_lfp_band_electrodes(...)` + `LFPBandV1.populate(...)` yourself — populating compute tables is normal Spyglass workflow, not a destructive op.

## Two gotchas worth flagging

1. **Cardinality before `fetch1()`.** A partial restriction like `{"nwb_file_name": f, "filter_name": "Theta 5-11 Hz"}` can match multiple `LFPBandV1` rows (different intervals, different upstream `lfp_merge_id`s). Check `len(rel)` first; if >1, add PK fields until it's 1.
2. **Filter-name convention matters for ripples.** Downstream `RippleLFPSelection.validate_key` rejects `LFPBandV1` rows whose `filter_name` does not contain `"ripple"`. If you're band-filtering for ripple detection, name the filter `"Ripple 150-250 Hz"` (or similar) — not just any 150–250 Hz bandpass.
