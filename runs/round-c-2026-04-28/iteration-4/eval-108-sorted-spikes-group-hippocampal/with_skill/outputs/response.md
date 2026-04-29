Yes — this is exactly what `SortedSpikesGroup` is for. It's a Spyglass-native group table that aggregates units across many sort groups under one user-named key, so any downstream analysis (decoding, MUA, your own scripts) can FK the *group* instead of re-joining merge IDs each time.

## What it is

`SortedSpikesGroup` lives in `spyglass.spikesorting.analysis.v1.group` (source: `src/spyglass/spikesorting/analysis/v1/group.py`). It is a `dj.Manual` master with a `Units` part table that FKs `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`. Primary key on the master is `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)` — note that `unit_filter_params_name` is part of the PK, so you must always supply it.

There's a sibling lookup, `UnitSelectionParams`, that ships defaults (`"all_units"`, `"exclude_noise"`, `"default_exclusion"`) — pick one to control which curation labels are filtered out at fetch time.

## Canonical workflow

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)

nwb_file = "your_session_.nwb"

# 1. Discover the curated unit sets you want to group. SortedSpikesGroup.Units
#    FKs SpikeSortingOutput with merge_id RENAMED to spikesorting_merge_id —
#    the dicts you pass to create_group() must use the renamed key, not raw
#    merge_id (group.py:73, 97-103).
candidate_units = (
    SpikeSortingOutput
    .merge_restrict({"nwb_file_name": nwb_file})  # NOT & {...} — silent no-op
    .proj(spikesorting_merge_id="merge_id")
    .fetch("KEY", as_dict=True)
)

# (Optional: filter candidate_units down to just hippocampal sort groups
#  by joining on SortGroup / electrode_group_name before this point.)

# 2. Inspect-before-write: is the group name already used?
group_name = "hippocampal_units"
filter_name = "exclude_noise"
existing = SortedSpikesGroup & {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}
print(len(existing), "rows already exist for this group key")

# 3. Create the group in one call. Raises if the (nwb_file_name,
#    unit_filter_params_name, sorted_spikes_group_name) triple exists.
SortedSpikesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name=group_name,
    unit_filter_params_name=filter_name,
    keys=candidate_units,
)

# 4. From now on, one key fetches all your hippocampal units.
group_key = {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}

spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    group_key, return_unit_ids=True
)
# spike_times: list of arrays, one per unit
# unit_ids: list of (merge_id, unit_id) identifiers

spike_indicator = SortedSpikesGroup().get_spike_indicator(group_key, time)
# (n_time, n_units) boolean / count matrix

firing_rate = SortedSpikesGroup().get_firing_rate(
    group_key, time, smoothing_sigma=0.015
)
```

## Why this is the right tool (vs. merge / vs. ad-hoc join)

A merge table aggregates *versions* of one analysis (v0 vs v1, sorter A vs sorter B). A group table aggregates *several distinct entities* into one set — exactly the "all my hippocampal units across tetrodes" shape. Downstream tables FK the group name, not a multi-row PK, which is why `SortedSpikesDecodingSelection` and `MuaEventsV1` both consume `SortedSpikesGroup` directly (`src/spyglass/decoding/v1/sorted_spikes.py`, `src/spyglass/mua/v1/mua.py:66`).

## Footguns worth flagging

1. **`spikesorting_merge_id`, not `merge_id`** in the `keys=[...]` you pass to `create_group()`. `SortedSpikesGroup.Units` FKs `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')` — passing raw `merge_id` will fail.
2. **Use `merge_restrict({"nwb_file_name": ...})`, not `& {"nwb_file_name": ...}`** on `SpikeSortingOutput`. The merge master's heading has only `merge_id`, so DataJoint silently drops the unknown attribute and the `&` returns the *whole* table (Common Mistake #6).
3. **`unit_filter_params_name` is part of the PK.** Two rows with the same `sorted_spikes_group_name` but different filter params are *different rows*. And `fetch_spike_data` only restricts the `Units` part by `(nwb_file_name, sorted_spikes_group_name)` (`group.py:171`) — it does **not** filter by `unit_filter_params_name`. If you accidentally create two groups with the same name under different filters, `fetch_spike_data` will silently merge their units. Keep `sorted_spikes_group_name` unique per session.
4. **Filtering to just hippocampal units** is your responsibility before `create_group`. `SortedSpikesGroup` itself is region-agnostic; you'd typically restrict `candidate_units` by joining `SortGroup` / electrode metadata to keep only HPC tetrodes.
5. **`time_slice`** on `fetch_spike_data` accepts a slice, list, or tuple — list/tuple gets converted via `slice(*time_slice)` (`group.py:231-232`). Prefer `slice(t0, t1)` for clarity.

## Where to read more

- `notebooks/11_Spike_Sorting_Analysis.ipynb` — canonical worked example.
- `src/spyglass/spikesorting/analysis/v1/group.py` — source; `create_group` at L84-103, `fetch_spike_data` at L142-232.
- `UnitAnnotation` (same module) if you want to attach per-unit labels (region, cell type, quality) once the group exists.
