# Brain region(s) for a `CurationV1` sorting

There is a built-in helper on `CurationV1` that does exactly this:
`CurationV1.get_sort_group_info(key)`. It joins the curation row through
`SpikeSortingSelection` -> `SpikeSortingRecordingSelection` ->
`SortGroup.SortGroupElectrode` -> `Electrode` -> `BrainRegion`, and
returns one row per sort group with the brain-region columns attached.

## Quickest answer — get the regions for this sorting

```python
import pandas as pd
from spyglass.spikesorting.v1 import CurationV1

key = {
    "sorting_id": "003581ca-a7e4-4953-bfc3-42198c1ba2a8",
    "nwb_file_name": "j1620210710_.nwb",
    # curation_id is part of CurationV1's primary key. If you have multiple
    # curations for this sorting, pin the one you actually curated, e.g.:
    # "curation_id": 1,
}

info = CurationV1.get_sort_group_info(key)
df = info.fetch(format="frame").reset_index()

# Unique regions across all sort groups in this sorting
regions = (
    df[["sort_group_id", "region_name", "subregion_name", "subsubregion_name"]]
    .drop_duplicates()
    .sort_values("sort_group_id")
)
print(regions)
```

The relevant columns come from `BrainRegion`:

- `region_name` — top-level region (e.g. `"hippocampus"`)
- `subregion_name` — e.g. `"CA1"`, `"CA3"`, `"dentate gyrus"`
- `subsubregion_name` — finer subdivision when present
- plus `region_id` (the FK key into `BrainRegion`)

For most Frank-lab tetrode datasets each sort group corresponds to one
tetrode placed in a single region, so a single sorting will usually
return one region (e.g. CA1) — but multi-region sessions do exist, so
always inspect `regions` rather than assuming length 1.

## Why `get_sort_group_info` is the right call

I checked
`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v1/curation.py`
(`CurationV1.get_sort_group_info`, lines 268-302). It builds:

```
(CurationV1 & key)
  * SpikeSortingSelection
  * SpikeSortingRecordingSelection.proj("recording_id", "sort_group_id")
  * SortGroup.SortGroupElectrode
  * Electrode
  * BrainRegion
```

i.e. it goes from your curation row to the recording's sort groups, to
the electrodes that make up each sort group, and finally joins
`BrainRegion` so you get `region_name` / `subregion_name` /
`subsubregion_name` directly. It picks one electrode per sort group
(`fetch(limit=1)`) which is the right behavior here because every
electrode in a sort group is, by construction, in the same brain
region.

`Electrode`'s definition (in
`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_ephys.py`,
class `Electrode`, line 73) includes `-> BrainRegion`, so the FK chain
is real and you can also do this manually if you want all electrodes
rather than one-per-group:

```python
from spyglass.common import Electrode, BrainRegion
from spyglass.spikesorting.v1.recording import (
    SortGroup,
    SpikeSortingRecordingSelection,
)
from spyglass.spikesorting.v1.sorting import SpikeSortingSelection
from spyglass.spikesorting.v1 import CurationV1

key = {
    "sorting_id": "003581ca-a7e4-4953-bfc3-42198c1ba2a8",
    "nwb_file_name": "j1620210710_.nwb",
}

per_electrode = (
    (CurationV1 & key)
    * SpikeSortingSelection
    * SpikeSortingRecordingSelection.proj("recording_id", "sort_group_id")
    * SortGroup.SortGroupElectrode
    * Electrode
    * BrainRegion
)
print(per_electrode.fetch(format="frame")
      [["sort_group_id", "electrode_id",
        "region_name", "subregion_name", "subsubregion_name"]]
      .reset_index(drop=True))
```

Either query returns the same brain-region columns; `get_sort_group_info`
is just the convenience wrapper.

## Filtering downstream by region

Once you know which `sort_group_id`s are in the region you care about,
you can filter units by sort group. The unit IDs in `CurationV1.get_sorting`
come from a single sorting that itself belongs to one sort group
(`SpikeSortingSelection` has `sort_group_id` in its key), so the more
common pattern is:

1. Find all sortings (across sort groups) for the session whose
   `sort_group_id` lies in the target region.
2. Pull the curated units from each.

Example — restrict to CA1 sortings for this session:

```python
from spyglass.common import Electrode, BrainRegion
from spyglass.spikesorting.v1.recording import (
    SortGroup,
    SpikeSortingRecordingSelection,
)
from spyglass.spikesorting.v1.sorting import SpikeSortingSelection
from spyglass.spikesorting.v1 import CurationV1

nwb = "j1620210710_.nwb"

# Sort groups in CA1 for this session
ca1_groups = (
    (Electrode & {"nwb_file_name": nwb})
    * BrainRegion
    * SortGroup.SortGroupElectrode
) & 'subregion_name = "CA1"'
ca1_sort_group_ids = set(ca1_groups.fetch("sort_group_id"))

# Curations whose recording's sort_group_id is in CA1
ca1_curations = (
    CurationV1
    * SpikeSortingSelection
    * SpikeSortingRecordingSelection.proj("recording_id", "sort_group_id")
) & {"nwb_file_name": nwb} & [
    {"sort_group_id": sg} for sg in ca1_sort_group_ids
]
print(ca1_curations.fetch("KEY"))
```

For *your specific* sorting, the simpler check is: run
`get_sort_group_info(key)` first, see what region(s) it reports, and
then decide whether this sorting is in your target region or not. If
the table prints e.g. `region_name="hippocampus", subregion_name="CA1"`
across all rows, you can keep the whole sorting; if it prints multiple
regions you'd need to drop down to the per-electrode query above and
inspect which sort groups fall where.

## A couple of gotchas worth flagging

- `CurationV1`'s primary key is `(sorting_id, curation_id)`. The key
  you gave (sorting_id + nwb_file_name) restricts uniquely on
  `sorting_id` (which is globally unique) but may match multiple
  `curation_id` rows if you've inserted iterative curations. The brain
  region is the same across all of them (it's a property of the
  recording, not the curation), so this doesn't change the answer —
  but `fetch1` calls downstream will need a `curation_id` pinned.
- `BrainRegion` is a pure lookup table keyed by `region_id`. The
  human-readable text lives in `region_name` / `subregion_name` /
  `subsubregion_name`, and `subregion_name` is where things like
  `"CA1"` typically end up (with `region_name="hippocampus"`). Don't
  filter on `region_id` directly — it's an autoincrement ID and not
  stable across databases.
- The "one electrode per sort group" inside `get_sort_group_info` is
  fine because Spyglass enforces same-region-per-sort-group at the
  electrode-grouping stage. If you ever build a sort group spanning
  regions (unusual), use the per-electrode query above instead.

## TL;DR

```python
CurationV1.get_sort_group_info(
    {"sorting_id": "003581ca-a7e4-4953-bfc3-42198c1ba2a8",
     "nwb_file_name": "j1620210710_.nwb"}
).fetch(format="frame")[
    ["sort_group_id", "region_name", "subregion_name", "subsubregion_name"]
]
```

That's the brain region(s) for the units in this sorting. If they all
say `subregion_name="CA1"`, all your units are CA1 and you can keep
the sorting wholesale; if you see multiple regions, fall back to the
per-electrode query and filter by `sort_group_id`.
