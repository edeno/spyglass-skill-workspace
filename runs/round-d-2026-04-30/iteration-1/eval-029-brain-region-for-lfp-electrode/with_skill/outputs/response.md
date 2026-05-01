# Brain region for a single electrode

Short answer: don't pull the region off the LFP table — pull it off `Electrode` (or `ElectrodeGroup`) joined to `BrainRegion`. `Electrode` carries its own `region_id` per channel, which is the per-contact authoritative value.

## The query

```python
from spyglass.common import Electrode, ElectrodeGroup, BrainRegion

key = {
    "nwb_file_name": "j1620210710_.nwb",   # see the note below about the trailing ".nwb"
    "electrode_id": 7,
}

# One row, all the brain-region columns alongside the electrode metadata:
row = (Electrode * BrainRegion & key).fetch1(
    "electrode_group_name",
    "region_id",
    "region_name",
    "subregion_name",
    "subsubregion_name",
    as_dict=True,
)
print(row)
```

Or if you just want the human-readable label:

```python
region_name = (Electrode * BrainRegion & key).fetch1("region_name")
```

## Why this works (and what to watch for)

- **`Electrode` has its own `-> BrainRegion` FK.** Each electrode row carries
  `region_id` independently of its group; this is what gets stored at ingest
  and what config-YAML overrides modify (`common_ephys.py:79`,
  `common_ephys.py:94-148`). So for "the brain region of *this contact*",
  `Electrode` is the source of truth, not the LFP table.

- **PK is composite.** `Electrode.primary_key == ['nwb_file_name',
  'electrode_group_name', 'electrode_id']` (it inherits the first two from
  `ElectrodeGroup`). `electrode_id` is unique within a session in practice
  (NWB ingest assigns each contact a session-wide id), so
  `{"nwb_file_name": ..., "electrode_id": 7}` is normally enough to land on
  one row — but if you ever see `DataJointError: fetch1 should only return
  one tuple`, add `electrode_group_name` to the restriction. Quick
  cardinality check before `fetch1`:

  ```python
  rel = Electrode * BrainRegion & key
  print(len(rel))   # expect 1
  ```

- **Session name suffix.** Spyglass stores `nwb_file_name` *with* the
  `.nwb` suffix (that's the PK in `Nwbfile`). `j1620210710_` looks like the
  stem; the actual key is almost certainly `"j1620210710_.nwb"`. Confirm
  with:

  ```python
  from spyglass.common import Nwbfile
  Nwbfile & 'nwb_file_name LIKE "j1620210710_%"'
  ```

- **Group-level region (alternative).** If you'd rather see what the
  *electrode group* says (the per-probe / per-shank label that seeds the
  per-electrode value), join `ElectrodeGroup` instead:

  ```python
  (ElectrodeGroup * BrainRegion & key).fetch1("region_name", "target_hemisphere")
  ```

  In most sessions the two agree, but the per-electrode `Electrode.region_id`
  can be overridden via the ingest config YAML, so for a *single contact*
  the `Electrode`-side join is the safer answer.

- **You don't need to go through the LFP table.** `LFPV1`'s
  `LFPElectrodeGroup` is a selection of which channels were filtered into
  LFP — it doesn't store anatomy. The region lives upstream in
  `common_ephys`, and you can query it for any electrode regardless of
  whether LFP was computed on it.
