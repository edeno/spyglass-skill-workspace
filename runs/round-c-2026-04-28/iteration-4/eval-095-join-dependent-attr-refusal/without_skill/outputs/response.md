# Why your join returns empty

The short answer: **`SpikeSortingSelection.interval_list_name` and `SpikeSortingRecordingSelection.interval_list_name` are not the same attribute, even though they share a name.** A DataJoint natural join only equates attributes that are matched through the foreign-key graph. When two tables both happen to have a column called `interval_list_name` that did *not* propagate from a common parent, the join treats them as independent attributes and requires both to be equal — but the values typically aren't equal, so you get an empty result.

## What's actually going on

In Spyglass v0:

- `SpikeSortingRecordingSelection` has its own `interval_list_name` — the interval used to *define the recording extract* (e.g. `"01_s1_valid_times"`). It is a foreign key into `IntervalList` keyed on `(nwb_file_name, interval_list_name)`.
- `SpikeSortingSelection` has its own `interval_list_name` too — the interval used to *restrict spike sorting within that recording* (e.g. `"01_s1_sort_interval"` or a `"…_artifact_removed"` interval produced by `ArtifactDetection`). It is also a FK into `IntervalList`, but it is **not** inherited from `SpikeSortingRecordingSelection`'s interval column.

So the dependency chain looks like:

```
IntervalList ──► SpikeSortingRecordingSelection (interval_list_name = recording interval)
IntervalList ──► SpikeSortingSelection         (interval_list_name = sort interval)
SpikeSortingRecordingSelection ──► SpikeSortingSelection  (via recording_id, NOT via interval_list_name)
```

When you do `SpikeSortingSelection * SpikeSortingRecordingSelection`, DataJoint sees `interval_list_name` in both schemas, can't tell they refer to different concepts, and folds them into a single equality constraint. Rows where the sort interval ≠ the recording interval drop out — which is essentially all of them in normal Spyglass usage, because the sort interval is almost always a sub-interval (often artifact-masked) of the recording interval.

This is a well-known DataJoint footgun: **attributes with the same name in two tables collide in a join even when they are semantically independent.**

## How to fix it

You have a few options, depending on what you actually want.

**1. Project-rename one side before joining (recommended).** Tell DataJoint these two columns are *not* the same:

```python
from spyglass.spikesorting.v0.spikesorting_recording import SpikeSortingRecordingSelection
from spyglass.spikesorting.v0.spikesorting_sorting import SpikeSortingSelection

joined = (
    SpikeSortingSelection
    * SpikeSortingRecordingSelection.proj(
        recording_interval="interval_list_name"
    )
)
```

Now `interval_list_name` (sort interval) and `recording_interval` (recording interval) are distinct columns and the join uses only the foreign-key columns that legitimately connect the two tables (`nwb_file_name`, `sort_group_id`, `preproc_params_name`, `team_name`, etc., depending on Spyglass version).

**2. If you want sortings whose *recording* covered a specific interval**, restrict on the recording side and then walk to the sorting side via the recording-level key, not via `interval_list_name`:

```python
target_interval = "01_s1_valid_times"

recordings = SpikeSortingRecordingSelection & {"interval_list_name": target_interval}
sortings   = SpikeSortingSelection & recordings.proj()   # joins on shared FK cols only
```

`recordings.proj()` strips secondary attributes (including the conflicting `interval_list_name`), so the restriction propagates only through the genuine primary-key relationship.

**3. If you want sortings whose *sort interval itself* equals the target**, restrict `SpikeSortingSelection` directly:

```python
SpikeSortingSelection & {"interval_list_name": target_interval}
```

## How to confirm this is the issue on your end

```python
SpikeSortingSelection.heading.attributes["interval_list_name"]
SpikeSortingRecordingSelection.heading.attributes["interval_list_name"]
# Compare .in_key, and look at .definition / .parents() / .descendants() —
# they're declared independently, both FK into IntervalList.

# And inspect a few rows:
(SpikeSortingSelection * SpikeSortingRecordingSelection.proj(
    rec_interval="interval_list_name"
)).fetch("interval_list_name", "rec_interval", limit=10, as_dict=True)
```

You'll typically see `interval_list_name` ending in `_artifact_removed` or `_sort` while `rec_interval` is the plain `_valid_times` interval — different strings, hence the empty natural join.

## Note on Spyglass version

The above describes the v0 pipeline (`spyglass.spikesorting.v0`). The v1 pipeline restructured these tables; `SpikeSortingRecordingSelection` and `SpikeSortingSelection` still both reference `IntervalList`, and the same name-collision pitfall applies. If you're on v1, the fix (project-rename one side, or restrict-then-join via `.proj()`) is identical — only the import paths change (`spyglass.spikesorting.v1.recording` / `spyglass.spikesorting.v1.sorting`).
