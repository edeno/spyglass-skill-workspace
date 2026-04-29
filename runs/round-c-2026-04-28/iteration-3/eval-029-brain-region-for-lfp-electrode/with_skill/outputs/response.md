# Brain region for `electrode_id=7` on `j1620210710_`

Short version: this is purely an anatomical-metadata lookup — the LFP merge_id, filter, and sampling rate don't enter into it. Brain region lives on `Electrode` (declared via `-> BrainRegion`), and is populated at ingest from the NWB file's `electrode_group.location`. Filtering a signal can't change where the contact was implanted.

## The query

```python
from spyglass.common import Electrode, BrainRegion

region_name = (
    Electrode * BrainRegion
    & {"nwb_file_name": "j1620210710_.nwb", "electrode_id": 7}
).fetch1("region_name")
```

`fetch1` is safe here because `(nwb_file_name, electrode_group_name, electrode_id)` is the full PK of `Electrode` and `electrode_id` is unique within a session in practice — joining on `BrainRegion` doesn't fan it out (the FK is `region_id`, single-valued per electrode).

If you want subregion as well:

```python
(Electrode * BrainRegion
 & {"nwb_file_name": "j1620210710_.nwb", "electrode_id": 7}
).fetch1("region_name", "subregion_name", "subsubregion_name")
```

## Why the LFP merge_id is not needed

The merge_id you have refers to the *processed* LFP artifact in `LFPOutput` (the merge layer over `LFPV1`, imported LFP, etc.). None of those tables carry a region attribute — region is upstream metadata on the probe/contact, ingested once when the session was inserted. There is no `region` field on `LFPV1`, `LFPOutput`, `LFPElectrodeGroup`, or `LFPElectrodeGroup.LFPElectrode`; trying to fetch one will fail.

Concretely, the FK chain that owns brain region is:

```
Session → ElectrodeGroup ──→ BrainRegion
              │
              └──→ Electrode ──→ BrainRegion   (this is the one you want)
```

Source: `spyglass/common/common_ephys.py:73` declares `class Electrode` with `-> BrainRegion` at line 79; `spyglass/common/common_region.py:9` declares `BrainRegion` with `region_id` PK and `region_name` attribute. The `make()` for `Electrode` (`common_ephys.py:128-134`) populates `region_id` per electrode from `elect_data.group.location` via `BrainRegion.fetch_add(...)`.

## Optional: verify electrode 7 was actually included in *this* LFP computation

This is orthogonal to the region question, but if you also want to confirm electrode 7 was in the LFP electrode group that produced your merge_id (not just that the contact exists on the probe), one extra restriction does it:

```python
from spyglass.lfp.lfp_merge import LFPOutput
from spyglass.lfp.v1 import LFPV1, LFPElectrodeGroup

# Recover the LFPV1 selection key from the merge_id
lfp_key = LFPOutput.merge_get_part({"merge_id": your_merge_id}).fetch1("KEY")

# Was electrode 7 in the LFP electrode group used by that selection?
in_group = bool(
    LFPElectrodeGroup.LFPElectrode
    & lfp_key
    & {"electrode_id": 7}
)
```

If `in_group` is `True`, the LFP trace you're plotting really is from that electrode. If it's `False`, the contact exists on the probe but wasn't filtered into this LFP run — your trace is coming from somewhere else.

For the plot label itself, though, the first query is all you need.
