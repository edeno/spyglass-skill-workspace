# Custom table that aggregates spikes across sort groups

## The key idea

In Spyglass, every spike-sorted result for a single sort group lives as one row in `SpikeSortingOutput` (the merge table at `spyglass.spikesorting.spikesorting_merge.SpikeSortingOutput`). Each `merge_id` corresponds to **one** sort group's curated sorting. So "spikes across all tetrode sort groups" is really "many `merge_id`s grouped together under one logical container."

The pattern Spyglass already uses for this is **a master table + a part table**, where the part table has one row per sort group's `merge_id`. This is exactly how `SortedSpikesGroup` (in `spyglass.spikesorting.analysis.v1.group`) is built, and it's the canonical template you should copy.

## Recommended table definition

```python
import datajoint as dj
from spyglass.common import Session
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.utils.dj_mixin import SpyglassMixin, SpyglassMixinPart

schema = dj.schema("my_custom_schema")  # pick your own schema name


@schema
class MyTetrodeSpikeGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    group_name: varchar(80)        # human-readable name for this group
    """

    class Units(SpyglassMixinPart):
        # One row per sort group whose spikes belong in this group.
        definition = """
        -> master
        -> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')
        """
```

Two things to notice:

1. **The master table** (`MyTetrodeSpikeGroup`) carries the *identity* of the group — keyed by `nwb_file_name` (from `Session`) plus a `group_name` you choose. There is no `sort_group_id` here, on purpose: a group spans many sort groups.
2. **The part table** (`MyTetrodeSpikeGroup.Units`) is where the cross-sort-group fan-in happens. Each row references one entry in `SpikeSortingOutput`. Because a single `merge_id` corresponds to one curated sorting from one sort group, inserting N rows into the part table aggregates N sort groups under one master row.

The `.proj(spikesorting_merge_id='merge_id')` rename is important. It lets you keep the foreign key as `spikesorting_merge_id` in your part table while still pointing at `SpikeSortingOutput.merge_id`. This avoids name collisions if you later join to other merge tables that also have a `merge_id` column.

## Populating the table

```python
nwb_file_name = "myfile_.nwb"
group_name = "all_tetrodes_run1"

# 1. Pull all the merge_ids that correspond to your tetrode sort groups for
#    this session. Restrict by whatever is appropriate — sort_interval,
#    sorter, curation_id, etc.
merge_ids = SpikeSortingOutput.get_restricted_merge_ids(
    {"nwb_file_name": nwb_file_name},
    sources=["v1"],          # or include "v0" if relevant
    as_dict=True,            # returns [{"merge_id": uuid}, ...]
)

# 2. Insert the master row.
MyTetrodeSpikeGroup.insert1(
    {"nwb_file_name": nwb_file_name, "group_name": group_name},
    skip_duplicates=True,
)

# 3. Insert one part row per sort group (= one per merge_id).
MyTetrodeSpikeGroup.Units.insert(
    [
        {
            "nwb_file_name": nwb_file_name,
            "group_name": group_name,
            "spikesorting_merge_id": m["merge_id"],
        }
        for m in merge_ids
    ],
    skip_duplicates=True,
)
```

`SpikeSortingOutput.get_restricted_merge_ids` is the supported way to resolve a partial key (session, sort interval, sorter, curation, etc.) down to the merge IDs you want. If you only want certain sort groups, add `sort_group_id` (and any other constraints) to the restriction dict — that filter propagates through the recording-selection table inside the helper.

## Fetching spikes across all sort groups in the group

The part table is what makes cross-sort-group fetches one-liners:

```python
# All merge_ids in this group
group_key = {"nwb_file_name": nwb_file_name, "group_name": group_name}
merge_ids = (MyTetrodeSpikeGroup.Units & group_key).fetch(
    "spikesorting_merge_id"
)

# Spike times concatenated across all sort groups
spike_times_per_unit = []
for mid in merge_ids:
    nwb = (SpikeSortingOutput & {"merge_id": mid}).fetch_nwb()[0]
    field = "object_id" if "object_id" in nwb else "units"
    spike_times_per_unit.extend(nwb[field]["spike_times"].to_list())
```

If you want to skip writing this loop yourself, you can mirror `SortedSpikesGroup.fetch_spike_data` (in `spyglass/spikesorting/analysis/v1/group.py`) — it does exactly this aggregation and also handles unit-label filtering (e.g., excluding `noise`/`mua`).

## Why this shape, and what to avoid

- **Don't put `sort_group_id` in the master's primary key.** That would force one master row per sort group and defeat the purpose.
- **Don't use `dj.Lookup` with hard-coded contents.** You want this table populated per-session, so `dj.Manual` (or `dj.Computed` if you derive the membership from another query) is correct.
- **Don't reach upstream of the merge table** (e.g., foreign-keying directly to `CurationV1` or `SpikeSorting`). Going through `SpikeSortingOutput` is what lets the same group hold v0, v1, and `ImportedSpikeSorting` results uniformly, and it's the supported integration point for downstream pipelines.
- **Use `SpyglassMixin` / `SpyglassMixinPart`**, not bare `dj.Manual` / `dj.Part`, so you get `fetch_nwb`, cautious-delete, and the rest of the Spyglass conveniences.

## TL;DR

Master table keyed by `(nwb_file_name, group_name)`, plus a part table whose only extra foreign key is `-> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`. Insert one part row per tetrode sort group's `merge_id`. The canonical worked example to copy is `SortedSpikesGroup` in `spyglass/spikesorting/analysis/v1/group.py`.
