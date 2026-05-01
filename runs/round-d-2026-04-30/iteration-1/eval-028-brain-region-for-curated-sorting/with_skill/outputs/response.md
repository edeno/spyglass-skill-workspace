# Brain region for a `CurationV1` sorting

The shortest path is **`CurationV1.get_sort_group_info(key)`** — it joins your
curation row through `SpikeSortingSelection` → `SpikeSortingRecordingSelection`
→ `SortGroup.SortGroupElectrode` → `Electrode` → `BrainRegion` and returns a
DataJoint table you can `.fetch()`. This is the same path the merge-layer
wrapper `SpikeSortingOutput.get_sort_group_info` uses internally
(`spikesorting/spikesorting_merge.py:186-205`); it just delegates to the part
table's class method (`spikesorting/v1/curation.py:269-302`).

`BrainRegion` (`common/common_region.py:9-15`) carries three fields:
`region_name`, `subregion_name`, `subsubregion_name` — these are what you'll
filter on downstream.

## Recipe

```python
from spyglass.spikesorting.v1 import CurationV1

sorting_id = "003581ca-a7e4-4953-bfc3-42198c1ba2a8"

# 1. Cardinality check first. CurationV1's PK is (sorting_id, curation_id);
#    `nwb_file_name` is NOT a CurationV1 attribute (it lives upstream on
#    SpikeSortingRecordingSelection), so a restriction of just
#    {"sorting_id": ...} can match multiple curation_id rows for the same
#    sorting. Pick one before calling get_sort_group_info, otherwise you'll
#    get the union across curations.
cur_rows = (CurationV1 & {"sorting_id": sorting_id}).fetch("KEY", as_dict=True)
print(len(cur_rows), cur_rows)
# If >1, pick the curation_id you actually want (e.g. the latest):
key = {"sorting_id": sorting_id, "curation_id": 0}     # or whichever id

# 2. Fetch the joined sort-group / electrode / brain-region table.
sort_group_info = CurationV1.get_sort_group_info(key)
df = (sort_group_info
      .proj("sort_group_id", "electrode_id",
            "region_name", "subregion_name", "subsubregion_name")
      .fetch(format="frame")
      .reset_index())
print(df[["sort_group_id", "electrode_id",
          "region_name", "subregion_name", "subsubregion_name"]]
        .drop_duplicates()
        .sort_values("sort_group_id"))

# 3. Unique brain regions for this sorting:
unique_regions = (
    df[["region_name", "subregion_name", "subsubregion_name"]]
      .drop_duplicates()
)
print(unique_regions)
```

How `get_sort_group_info` works internally (`curation.py:283-302`): for each
sort group it pulls one electrode (sort groups in v1 are typically one
tetrode/shank, so the region label is the same for every electrode in the
group; pulling one is intentional), then joins `Electrode * SortGroupElectrode
* BrainRegion` so each `sort_group_id` lands with its anatomical labels. That
means you'll get one region row per sort group, not per unit — which is the
right granularity, since brain region is assigned at the
electrode-group/probe-shank level upstream of sorting (in `ElectrodeGroup` and
`Electrode` from raw NWB ingestion).

## Filtering by region for downstream analysis

Once you know which `sort_group_id`s correspond to the region you care about,
two common patterns:

**(a) Filter unit IDs at fetch time.** Get the per-unit table with
`CurationV1.get_sorting(key, as_dataframe=True)` (curation.py around
`get_sorting`), restrict to the sort groups in your region of interest, and
use the resulting unit ids to slice spike times.

**(b) Restrict the merge layer.** If you've published this curation to
`SpikeSortingOutput`, call the same method on the merge master — it returns
the same join with `merge_id` attached:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# Find the merge_id corresponding to your CurationV1 row.
merge_key = (SpikeSortingOutput.CurationV1 & key).fetch1("KEY")
info = SpikeSortingOutput.get_sort_group_info(merge_key)
ca1_groups = (info & {"region_name": "CA1"}).fetch(
    "merge_id", "sort_group_id", "electrode_id", as_dict=True
)
```

Then use the filtered `merge_id`s with `SpikeSortingOutput().get_spike_times(...)`
or feed the surviving `sort_group_id`s into `SortedSpikesGroup` for
group-level analyses.

## Heads-up on naming

`region_name` values come from upstream NWB ingestion (whatever the lab put
in the electrode group's `location` field). They aren't enforced against an
ontology, so case and spelling matter — do `(BrainRegion).fetch("region_name")`
once to see what strings are actually present in your DB before hard-coding
`"CA1"` vs `"ca1"` vs `"hippocampus_CA1"` filters.

## Quick verification you can run

```python
# Sanity: confirm the sort_group_ids returned match what's in SortGroup for this nwb file.
from spyglass.spikesorting.v1 import SortGroup
nwb_file = "j1620210710_.nwb"
print((SortGroup.SortGroupElectrode & {"nwb_file_name": nwb_file})
      .fetch("sort_group_id", "electrode_id", as_dict=True)[:5])

# Sanity: confirm the BrainRegion rows are non-empty for those electrodes.
from spyglass.common import Electrode, BrainRegion
print((Electrode * BrainRegion & {"nwb_file_name": nwb_file})
      .fetch("electrode_id", "region_name", "subregion_name", as_dict=True)[:5])
```

If `region_name` comes back empty or as a placeholder, the brain region
metadata wasn't populated during NWB ingestion — check the original
`ElectrodeGroup` / `Electrode` rows for that session.
