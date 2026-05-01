Yes — Spyglass has a built-in table designed for exactly this:
`SortedSpikesGroup` in `spyglass.spikesorting.analysis.v1.group`. It
lets you bundle the curated outputs from many sort groups (e.g. all your
hippocampal tetrodes) under a single named group, then fetch combined
spike trains, spike indicators, or firing rates with one call.

## What it is

`SortedSpikesGroup` is a `dj.Manual` table with a part-table `Units` that
points at `SpikeSortingOutput` (the merge table that unifies the v0/v1
sorting outputs). One row in the master = one named group for a session;
the part table holds one row per `merge_id` you want included in that
group.

Schema (from `spyglass/spikesorting/analysis/v1/group.py`):

```python
@schema
class SortedSpikesGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    -> UnitSelectionParams
    sorted_spikes_group_name: varchar(80)
    """

    class Units(SpyglassMixinPart):
        definition = """
        -> master
        -> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')
        """
```

`UnitSelectionParams` is a small parameter table for label-based filtering
(e.g. drop units curated as `"noise"` or `"mua"`). It ships with three
defaults: `"all_units"`, `"exclude_noise"`, and `"default_exclusion"` —
the latter two exclude `noise` and `mua` labels.

## Typical workflow

```python
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# 1. Make sure the default selection params exist
UnitSelectionParams().insert_default()

nwb_file_name = "my_session_.nwb"

# 2. Find the merge_ids for the curations you want to bundle.
#    Restrict SpikeSortingOutput (or one of its part tables, e.g. CurationV1)
#    to the curations from your hippocampal tetrodes for this session.
#    `keys` must be a list of dicts each containing `spikesorting_merge_id`.
hippo_merge_ids = (
    SpikeSortingOutput.CurationV1
    & {"nwb_file_name": nwb_file_name}
    # ... plus whatever restriction picks out hippocampal sort groups
    #     (sort_group_id list, brain_region, etc.)
).fetch("merge_id")

keys = [{"spikesorting_merge_id": mid} for mid in hippo_merge_ids]

# 3. Create the group
SortedSpikesGroup().create_group(
    group_name="CA1_all_tetrodes",
    nwb_file_name=nwb_file_name,
    unit_filter_params_name="exclude_noise",  # or "all_units"
    keys=keys,
)
```

`create_group` inserts the master row and then inserts one part-table row
per merge_id, all in one shot. It refuses to overwrite an existing group
of the same `(nwb_file_name, sorted_spikes_group_name)` — delete the old
group first if you want to recreate it.

## Pulling combined spikes back out

Once the group exists, three classmethods do the heavy lifting and
already concatenate units across all member sort groups:

```python
group_key = {
    "nwb_file_name": nwb_file_name,
    "sorted_spikes_group_name": "CA1_all_tetrodes",
    "unit_filter_params_name": "exclude_noise",
}

# (a) Raw spike times: list[np.ndarray], one per unit, all sort groups merged
spike_times = SortedSpikesGroup.fetch_spike_data(group_key)

# Or with provenance:
spike_times, unit_ids = SortedSpikesGroup.fetch_spike_data(
    group_key, return_unit_ids=True
)
# unit_ids is a list of {"spikesorting_merge_id": ..., "unit_id": ...}

# (b) Binned spike indicator on a chosen time axis -> shape (n_time, n_units)
import numpy as np
time = np.arange(t_start, t_stop, 0.002)  # 2 ms bins, for example
spike_indicator = SortedSpikesGroup.get_spike_indicator(group_key, time)

# (c) Smoothed firing rate -> shape (n_time, n_units), or multiunit
fr = SortedSpikesGroup.get_firing_rate(
    group_key, time, multiunit=False, smoothing_sigma=0.015
)
mua_rate = SortedSpikesGroup.get_firing_rate(
    group_key, time, multiunit=True
)
```

`fetch_spike_data` also takes a `time_slice=[start, stop]` (or a `slice`
object) if you only want spikes inside an interval, and it applies the
include/exclude label filtering from `UnitSelectionParams` for you, so
the units curated as `noise`/`mua` are dropped automatically when you
chose `exclude_noise` / `default_exclusion`.

## Why this is the right primitive

- It's the same table the downstream pipelines already consume:
  `SortedSpikesDecodingV1` (`spyglass/decoding/v1/sorted_spikes.py`) and
  the MUA pipeline (`spyglass/mua/v1/mua.py`) both take a
  `SortedSpikesGroup` foreign key and call `fetch_spike_data` /
  `get_spike_indicator` internally. So the group you make for "all
  hippocampal spikes" is reusable for decoding and MUA detection without
  re-plumbing anything.
- Provenance is preserved: every spike train can be traced back to its
  `(spikesorting_merge_id, unit_id)` via `return_unit_ids=True`.
- The label-based filtering means you don't have to re-implement the
  noise/MUA exclusion logic each time.

## Files to look at

- `spyglass/spikesorting/analysis/v1/group.py` — `SortedSpikesGroup`,
  `UnitSelectionParams`, `create_group`, `fetch_spike_data`,
  `get_spike_indicator`, `get_firing_rate`.
- `spyglass/spikesorting/spikesorting_merge.py` — `SpikeSortingOutput`
  merge table (this is what your `merge_id`s come from).
- `spyglass/decoding/v1/sorted_spikes.py` and `spyglass/mua/v1/mua.py` —
  examples of downstream pipelines consuming a `SortedSpikesGroup`.

So: stop hand-joining sort groups. Build a `SortedSpikesGroup` once per
region per session and fetch from it.
