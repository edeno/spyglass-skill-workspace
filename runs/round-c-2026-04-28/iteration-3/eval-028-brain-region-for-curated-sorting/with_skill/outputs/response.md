# Brain regions for a `CurationV1` sorting

Brain region in Spyglass is **a property of electrodes, not of units or sortings**. `CurationV1` does not carry a `region` attribute, and `unit_id` does not affect the answer — every unit produced by a given sort group is sorted from the same set of electrodes, so all units in that sort group share the same region(s). The route is:

```
CurationV1 → SpikeSortingSelection → SpikeSortingRecording(Selection) → SortGroup
                                                                          ↓
                                                  SortGroup.SortGroupElectrode → Electrode → BrainRegion
```

## Source-of-truth answer — explicit FK walk

The cleanest, fully accurate query joins through to `BrainRegion` and returns one row per electrode (so polymer-probe sort groups whose electrodes span regions show every region they hit, not just one).

There is one subtlety: the bare `SpikeSortingSelection * SpikeSortingRecordingSelection` join raises `DataJointError: Cannot join query expressions on dependent attribute '...'` because both selection tables carry `nwb_file_name` and `interval_list_name` as **secondary** attributes that arrive through different FK paths (`src/spyglass/spikesorting/v1/sorting.py:199-207` and `src/spyglass/spikesorting/v1/recording.py:147-157`). DataJoint refuses to assume those secondaries mean the same thing. Project the one bridging attribute you actually need — `recording_id` — off `SpikeSortingSelection` first:

```python
from spyglass.spikesorting.v1 import (
    CurationV1,
    SpikeSortingSelection,
    SpikeSortingRecordingSelection,
    SortGroup,
)
from spyglass.common import Electrode, BrainRegion

key = {
    "sorting_id": "003581ca-a7e4-4953-bfc3-42198c1ba2a8",
    "curation_id": 0,
}

regions = (
    (CurationV1 & key)
    * (SpikeSortingSelection & key).proj("recording_id")   # one-sided-secondary bridge
    * SpikeSortingRecordingSelection                        # carries sort_group_id + nwb_file_name
    * SortGroup.SortGroupElectrode                          # one row per electrode in the sort group
    * Electrode                                             # carries region_id
    * BrainRegion                                           # region_name, subregion_name, subsubregion_name
).fetch("sort_group_id", "electrode_id", "region_name", as_dict=True)

# If you just want the unique region names:
unique_regions = sorted({r["region_name"] for r in regions})
```

Equivalent two-restriction shape (identical result, easier to inspect step-by-step):

```python
recording_id = (SpikeSortingSelection & key).fetch1("recording_id")
regions = (
    SpikeSortingRecordingSelection
    * SortGroup.SortGroupElectrode
    * Electrode
    * BrainRegion
    & {"recording_id": recording_id}
).fetch("sort_group_id", "electrode_id", "region_name", as_dict=True)
```

Either shape is fine. The first stays composable in one expression; the second lets you pause and look at `recording_id` mid-debug.

## Convenience shortcut — `CurationV1.get_sort_group_info(key)`

Spyglass ships a helper that wraps a similar join (`src/spyglass/spikesorting/v1/curation.py:268`):

```python
sort_group_info = CurationV1.get_sort_group_info(key)
sort_group_info.fetch("sort_group_id", "region_name", as_dict=True)
```

It is fine for the common case **but has an important caveat**. Looking at the implementation (`curation.py:288-294`):

```python
electrode_restrict_list = []
for entry in table:
    # pull just one electrode from each sort group for info
    electrode_restrict_list.extend(
        ((SortGroup.SortGroupElectrode() & entry) * Electrode).fetch(
            limit=1
        )
    )
```

It loops over sort groups and pulls **one electrode per sort group** (`limit=1`) before joining to `BrainRegion`. So `get_sort_group_info(...).fetch('region_name')` returns **one region per sort group**, not one row per electrode.

- **Tetrodes** — by Frank-lab convention, all 4 channels of a tetrode sit in the same brain region, so the helper is exact and you can stop here.
- **Polymer probes (e.g. NeuroPixels, multi-shank silicon probes)** — a single sort group can span multiple regions across its contacts. The helper will report only the **sampled** electrode's region and silently miss the others. Use the explicit FK walk above whenever you can't guarantee per-sort-group region homogeneity, or whenever you need an electrode-level breakdown.

A quick way to detect the polymer-probe case for your sorting:

```python
n_electrodes = len(SortGroup.SortGroupElectrode * SpikeSortingRecordingSelection
                   & {"recording_id": recording_id})
n_sort_groups = len(SortGroup * SpikeSortingRecordingSelection
                    & {"recording_id": recording_id})
print(n_electrodes / n_sort_groups, "electrodes per sort group")
# ≈ 4 → tetrode, helper is fine
# > 4 → likely polymer; prefer the explicit walk
```

## Notes

- `unit_id` does not enter the query — region is determined entirely by which electrodes belong to each sort group, and every unit from that sort group is sorted off those same electrodes. Don't write things like "unit 5 is in CA1, unit 6 is in CA3" off a sorting unless those units came from different sort groups.
- `CurationV1` itself has no `region` / `brain_region` attribute. If you find yourself reaching for one, you're missing the FK walk.
- `BrainRegion` lives in `spyglass.common` (`src/spyglass/common/common_region.py:9`); its primary key is `region_id`, with `region_name`, `subregion_name`, `subsubregion_name` as the human-readable fields. If you also want substructure, fetch `region_name`, `subregion_name`, `subsubregion_name` together.
