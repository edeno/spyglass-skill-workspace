Yes — there's a built-in for exactly this. It's `SortedSpikesGroup` (with its part `SortedSpikesGroup.Units`), in `spyglass.spikesorting.analysis.v1.group`. You give a name to a chosen subset of sorted unit sets (across as many sort groups / tetrodes as you like), and downstream code can foreign-key the *group* instead of joining merge IDs by hand every time.

Source of truth: `src/spyglass/spikesorting/analysis/v1/group.py`.

## What `SortedSpikesGroup` is

- A `dj.Manual` master keyed on `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)` (`group.py:63-67`). Note the FK to `UnitSelectionParams` is part of the primary key — you must supply `unit_filter_params_name` to identify the group, not just the name.
- A part table `SortedSpikesGroup.Units` whose rows FK `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')` (`group.py:73`). Each part row references a sorted-unit set by its **renamed** merge ID column `spikesorting_merge_id` — not raw `merge_id`. `create_group` splats the dict straight into the part insert (`group.py:97-103`), so passing `merge_id` will fail.
- A companion parameter table `UnitSelectionParams` ships defaults `"all_units"`, `"exclude_noise"`, `"default_exclusion"` (`group.py:17-59`). On a fresh DB these are not auto-inserted on import despite being a `dj.Manual`; run `UnitSelectionParams().insert_default()` once before referencing those names, or the FK insert will fail.

## Building the group for one session's hippocampal units

The general flow is: discover the merge keys for the unit sets you want → pick a label filter → call `create_group`. Skill convention is to inspect first, write second.

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)

nwb_file = "your_session_.nwb"

# 0. One-time on a fresh DB:
# UnitSelectionParams().insert_default()

# 1. Find the merge keys for this session's sorted unit sets, and rename
#    `merge_id` -> `spikesorting_merge_id` to match the part-table FK.
candidate_units = (
    SpikeSortingOutput.merge_restrict({"nwb_file_name": nwb_file})
    .proj(spikesorting_merge_id="merge_id")
    .fetch("KEY", as_dict=True)
)
print(len(candidate_units), "candidate unit sets for", nwb_file)
```

If you have a way to restrict to *just* hippocampal sort groups upstream of this — e.g. a brain-region annotation on `Electrode` / `SortGroup`, or a known subset of `sort_group_id` values — apply that restriction at step 1 so `candidate_units` only contains the hippocampal sets. Spyglass does not infer "hippocampal" from a string anywhere; you'll need to base it on lab metadata you've already populated (BrainRegion, electrode group names, or a curated list of merge IDs you trust). I don't know your specific schema for that — happy to help wire it up if you tell me where region info lives in your DB.

```python
# 2. Pick a label filter. "exclude_noise" drops units curated as noise.
filter_name = "exclude_noise"

# 3. Inspect-before-write: is this group key already used?
group_name = "ca1_all_tetrodes"
existing = SortedSpikesGroup & {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}
print(len(existing), "existing rows for this group key")

# 4. Create the group. create_group inserts the master + all part rows
#    in one call. It RAISES if a row with the same triple already exists
#    (`group.py:84-95`); pick a new name or delete the old group first.
SortedSpikesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name=group_name,
    unit_filter_params_name=filter_name,
    keys=candidate_units,
)
```

## Using the group to get all spikes at once

`SortedSpikesGroup` has helpers that materialize the membership for you, so a single `key` returns everything across the included sort groups:

```python
group_key = {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}

# List of spike-time arrays, one per unit, plus the matching unit IDs.
spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    group_key, return_unit_ids=True
)

# Or as a (n_time, n_units) binary indicator on a chosen time vector:
import numpy as np
time = np.arange(t0, t1, 0.002)  # 2 ms bins, for example
spike_indicator = SortedSpikesGroup().get_spike_indicator(group_key, time)

# Or smoothed firing rates:
firing_rate = SortedSpikesGroup().get_firing_rate(
    group_key, time, multiunit=False, smoothing_sigma=0.015
)
```

`fetch_spike_data` accepts an optional `time_slice` (list/tuple/`slice`) — internally a list/tuple is converted with `time_slice = slice(*time_slice)` (`group.py:231-232`); prefer passing `slice(t0, t1)` directly for clarity.

## Footguns worth knowing about

- **Use `spikesorting_merge_id` in the keys, not `merge_id`.** The part FK is renamed (`group.py:73`); `create_group` will raise on the unknown column otherwise.
- **`unit_filter_params_name` is part of the primary key.** Two rows with the same `sorted_spikes_group_name` but different filter params are distinct rows. However, `SortedSpikesGroup.fetch_spike_data` only restricts the `Units` part by `(nwb_file_name, sorted_spikes_group_name)` (`group.py:171`) — it does **not** filter by `unit_filter_params_name`. If you have two groups sharing a name under different filters, `fetch_spike_data` will silently merge their units. Keep `sorted_spikes_group_name` unique per session unless you've verified that's what you want.
- **`create_group` does not append.** It raises on collision; it is not idempotent. To change membership, delete the existing master row (which cascades to `SortedSpikesGroup.Units`) and re-create, or use a new name.
- **Downstream consumers** that already accept a `SortedSpikesGroup` key directly: `SortedSpikesDecodingSelection` and `MuaEventsV1`. So once the group exists you don't have to re-aggregate for those either.

If you want, I can sketch the upstream restriction for "hippocampal only" once you tell me how brain region is recorded in your setup (e.g. `Electrode.region_name`, a per-tetrode lookup, or a hand-maintained list of `sort_group_id`s). That's the only piece Spyglass itself doesn't decide for you.
