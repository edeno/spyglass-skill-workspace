# `IndexError: index 0 is out of bounds for axis 0 with size 0` in `DLCPosV1.populate`

Short answer: yes, this almost always means an upstream prerequisite is empty / missing — the DLC pipeline is reaching for a row in some array (typically position timestamps or interval bounds) that has zero length. `DLCPosSelection` being correctly inserted is necessary but not sufficient: DLC reads from upstream position-interval bookkeeping that has to be populated *before* you start the DLC pipeline.

## The most common upstream gap on a fresh session

Spyglass's DLC pipeline depends on the standard position-interval plumbing that gets set up during NWB ingest. Specifically:

- `Session` / `Nwbfile` ingestion must have populated `IntervalList` for the file (the canonical interval-bookkeeping table).
- `PositionSource` and `RawPosition` (in `spyglass.common.common_behav`) anchor the position-interval rows. These get inserted during `populate_all_common` / `Session.populate`.
- `TaskEpoch` ties the *task* epochs to interval names.
- `PositionIntervalMap` is the table that maps a task epoch's interval name to the corresponding position-interval name (`pos N valid times` style entries on `IntervalList`). DLC needs a resolved row here to know which timestamps to align video frames to.

If `PositionIntervalMap` for your `(nwb_file_name, interval_list_name)` doesn't exist or has `position_interval_name = ''` (the empty/null sentinel), the downstream DLC make() will index into a zero-length array and crash with exactly the error you're seeing.

## Walk the diagnostic layers in this order

### 1. Inspect `PositionIntervalMap` for your session

Restrict by the table's *actual* primary key — `nwb_file_name` and `interval_list_name`, which it inherits from `IntervalList`. The key is **not** `epoch`. There is a helper, `convert_epoch_interval_name_to_position_interval_name`, that accepts an `epoch` integer for convenience, but it works by first translating the epoch via `get_interval_list_name_from_epoch` and then doing the lookup on `interval_list_name`. So restrict directly:

```python
from spyglass.common.common_behav import (
    PositionIntervalMap,
    get_interval_list_name_from_epoch,
)

interval_list_name = get_interval_list_name_from_epoch(nwb_file_name, epoch)
rows = (PositionIntervalMap & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": interval_list_name,
}).fetch(as_dict=True)
print(rows)
```

Three outcomes:
- **Empty result** — no mapping exists for this task epoch.
- **`position_interval_name == ''`** — the converter ran, found no match, and inserted the null sentinel.
- **Populated row** — mapping is fine; the IndexError is from somewhere else (move to step 3).

In the first two cases, the data shape is the problem; you can't fix it by re-running `DLCPosV1.populate`, because the same gap will reproduce.

Note that `DLCPoseEstimation`'s `make()` already calls `convert_epoch_interval_name_to_position_interval_name(..., populate_missing=True)` under the hood, so the once-common advice of "just run the converter manually with `populate_missing=True`" doesn't help here — that code path has already run and already failed to find a match.

### 2. Confirm the position-interval prerequisites exist

`PositionIntervalMap`'s make() doesn't query `RawPosition` directly. It walks `IntervalList` rows whose names are recognized as position-interval names by `PositionSource._is_valid_name()` (the `pos N valid times` convention). So check the upstreams as **prerequisites** — they're what put the recognizable interval rows on `IntervalList` during ingest:

```python
from spyglass.common import PositionSource, RawPosition, IntervalList

print((PositionSource & {"nwb_file_name": nwb_file_name}).fetch(as_dict=True))
print((RawPosition  & {"nwb_file_name": nwb_file_name}).fetch(as_dict=True))
print((IntervalList & {"nwb_file_name": nwb_file_name}).fetch("interval_list_name"))
```

If `PositionSource` / `RawPosition` are empty: the NWB file's position data didn't get ingested. Re-run ingestion with errors surfaced:

```python
from spyglass.common.populate_all_common import populate_all_common
populate_all_common(nwb_file_name, raise_err=True)
```

…and then check `InsertError` for what blocked it (most often a missing field in the NWB processing module, or a behavior series that doesn't match the expected schema).

If `PositionSource` / `RawPosition` exist but `IntervalList` has no rows whose names look like `pos N valid times`, then the position-source naming convention isn't being matched and the converter has nothing to map to.

### 3. Check `TaskEpoch` ↔ `IntervalList` name alignment

The mapper matches a task-epoch interval to a position interval by overlapping `valid_times` (with a small EPSILON tolerance), not by name. If your data renamed the epoch (custom epoch label) or if the position-interval `valid_times` don't overlap with the task-epoch `valid_times`, the converter will fail to match and write the null entry.

```python
from spyglass.common import TaskEpoch, IntervalList

task_intervals = (TaskEpoch & {"nwb_file_name": nwb_file_name}).fetch(
    "interval_list_name", "epoch"
)
all_intervals  = (IntervalList & {"nwb_file_name": nwb_file_name}).fetch(
    "interval_list_name"
)
print("task intervals:", task_intervals)
print("all intervals: ", all_intervals)
```

Then for the specific epoch you're populating, fetch `valid_times` for both the task-epoch interval and any candidate `pos N valid times` row and confirm they overlap.

## DLC-only sessions (edge case worth knowing)

If this session has *only* DLC video and no Trodes-derived position at all, `DLCPoseEstimation.make()` falls back to using the source video's timestamps when the converter returns no position-interval name — so pose estimation itself doesn't strictly require a `pos N valid times` row. In that case, the IndexError tends to surface *downstream* (e.g. in `DLCCentroid` or `DLCOrientation`, which still expect a resolvable position interval to align against). The fix is one of:

- Populate `PositionSource` / `RawPosition` so the mapper has something to match (giving `_is_valid_name()` an `IntervalList` row to accept), or
- Stop the DLC pipeline at `DLCPoseEstimation` and skip centroid/orientation for sessions where there's no Trodes-side position.

## Why "just re-run `DLCPosV1.populate`" is the wrong move

The IndexError isn't transient — it reflects a missing/empty row upstream. Re-running `DLCPosV1.populate(key)` will re-enter the same code path, hit the same zero-length array, and raise the same error. Fix the upstream first (one of the three diagnostic layers above), then retry the DLC populate.

## Suggested order of operations

1. Run the `PositionIntervalMap` query above for your `(nwb_file_name, epoch)`.
2. If empty / null: inspect `PositionSource`, `RawPosition`, and `IntervalList` for the file.
3. If those are empty: re-run `populate_all_common(nwb_file_name, raise_err=True)` and look at `InsertError`.
4. If those exist but no recognized position-interval rows are present: confirm the NWB file's position data follows the `pos N valid times` naming convention used by `PositionSource._is_valid_name()` — if not, that's the ingestion-side bug to fix.
5. Only after the upstream is non-empty and `PositionIntervalMap` resolves to a real `position_interval_name`, retry `DLCPosV1.populate(key)`.

`DLCPosSelection` being correct is fine — the issue is one layer up the dependency graph, in the position-interval bookkeeping that DLC depends on.
