# Brain region for a single electrode

In Spyglass, the per-electrode brain region lives in `common.Electrode`, which has a foreign key into `common.BrainRegion` (via `region_id`). To get the region for `electrode_id=7` on session `j1620210710_`, restrict `Electrode * BrainRegion` by both keys and `fetch1` the region columns.

## Quick note on the session name

Spyglass sessions are keyed by `nwb_file_name`, which is the filename of the ingested NWB file and conventionally ends in `.nwb` (e.g. `j1620210710_.nwb`). The trailing underscore in `j1620210710_` is normal — it's the date-suffix separator used by `rec_to_nwb` — but you almost certainly need `"j1620210710_.nwb"` as the actual primary key value. If a bare `j1620210710_` doesn't match anything, that's why. You can confirm with:

```python
from spyglass.common import Nwbfile
Nwbfile() & "nwb_file_name LIKE 'j1620210710%'"
```

## The query

```python
import datajoint as dj
from spyglass.common import Electrode, BrainRegion

key = {
    "nwb_file_name": "j1620210710_.nwb",   # adjust if your filename differs
    "electrode_id": 7,
}

# Join Electrode to BrainRegion and pull the region fields.
region = (Electrode & key) * BrainRegion
region.fetch1("region_name", "subregion_name", "subsubregion_name")
```

`fetch1` will raise if there isn't exactly one matching row, which is the behavior you want for a single-electrode lookup — it'll surface a typo in `nwb_file_name` or a missing electrode immediately rather than silently returning empty.

If you'd rather see all the fields at once:

```python
((Electrode & key) * BrainRegion).fetch1()
```

That returns a dict with the electrode metadata (`x`, `y`, `z`, `electrode_group_name`, `probe_id`, …) plus `region_name`, `subregion_name`, `subsubregion_name`.

## Why the join is needed

`Electrode` only stores `region_id` (an integer). The human-readable region label lives in `BrainRegion`:

- `BrainRegion`: `region_id` → (`region_name`, `subregion_name`, `subsubregion_name`)
- `Electrode`: `(nwb_file_name, electrode_group_name, electrode_id)` → `region_id` (plus position, impedance, etc.)

So `Electrode * BrainRegion` is the natural join you want; restricting first (`Electrode & key`) just keeps the join cheap.

## A couple of related sanity checks

1. **Is the electrode actually one of the LFP channels?** `electrode_id=7` exists in `Electrode` regardless, but the LFP pipeline only runs on a subset of channels selected via `LFPElectrodeGroup.LFPElectrode`. To confirm electrode 7 is in your LFP selection:

   ```python
   from spyglass.lfp.lfp_electrode import LFPElectrodeGroup
   LFPElectrodeGroup.LFPElectrode & key
   ```

2. **Bulk version, if you ever want all LFP electrodes' regions for this session:**

   ```python
   (LFPElectrodeGroup.LFPElectrode & {"nwb_file_name": "j1620210710_.nwb"}) \
       * Electrode * BrainRegion
   ```

   Then `.fetch("electrode_id", "region_name", as_dict=True)` to get a list.

That's it — `(Electrode & key) * BrainRegion` then `fetch1` is the canonical pattern.
