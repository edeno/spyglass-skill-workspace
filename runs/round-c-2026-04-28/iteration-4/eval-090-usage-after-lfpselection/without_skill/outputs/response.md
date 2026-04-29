## Answer

Once you have an `LFPSelection` row inserted, the next step is to **populate the `LFPV1` table** — that's the computed table that actually does the LFP extraction (filtering + downsampling) for the selection you just specified.

The standard pattern looks like this:

```python
from spyglass.lfp.v1 import LFPV1, LFPSelection

# the key you used to insert the selection
key = {
    "nwb_file_name": "minirec20230622_.nwb",
    "lfp_electrode_group_name": "test",
    "target_interval_list_name": "01_s1",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": 30000,
}

# kick off the actual LFP computation
LFPV1.populate(key)
```

### What `populate` actually does

`LFPV1.make()` (called per key by `populate`) will:

1. Pull the raw recording referenced by the parent `Raw`/`IntervalList` keys.
2. Restrict to the electrodes listed in the matching `LFPElectrodeGroup` / `LFPSelection.LFPElectrode` part table.
3. Apply the digital filter named in `FirFilterParameters` (the `filter_name` + `filter_sampling_rate` you picked — typically the "LFP 0-400 Hz" filter).
4. Downsample to the LFP sampling rate (commonly ~1 kHz).
5. Write the filtered, downsampled traces into a new analysis NWB file and store the path + an `IntervalList` entry on the `LFPV1` row.

### After `populate` finishes

Once `LFPV1` has the row, the typical follow-ups are:

- **Fetch the data as a pynwb object / DataFrame:**
  ```python
  lfp_nwb = (LFPV1 & key).fetch_nwb()[0]      # NWB-style access
  lfp_df  = (LFPV1 & key).fetch1_dataframe()  # pandas, time-indexed
  ```
- **Merge into the unified `LFP` merge table** so downstream code doesn't care which version produced it:
  ```python
  from spyglass.lfp.lfp_merge import LFPOutput
  LFPOutput.insert([key], part_name="LFPV1", skip_duplicates=True)
  ```
  Most downstream pipelines (LFP band extraction, theta/ripple detection, decoding) key off `LFPOutput`/`LFPOutput.merge_get_part(...)`, not `LFPV1` directly.
- **Run band-specific extraction** (e.g. theta, ripple) by inserting into `LFPBandSelection` and populating `LFPBandV1`, which reads from the merge table.
- **Plot / sanity-check** the trace for one electrode over a short interval before trusting it for analysis (always worth doing — verifies the filter band, sampling rate, and interval alignment match what you expected).

### Quick sanity checks before populating

- Confirm `LFPSelection & key` returns exactly one row (not zero, not many).
- Confirm the parent rows actually exist: `LFPElectrodeGroup & key`, `IntervalList & {"interval_list_name": target_interval_list_name}`, and `FirFilterParameters & {"filter_name": ..., "filter_sampling_rate": ...}`.
- For a long recording, smoke-test on a short interval first — full-session LFP populate is I/O heavy.
