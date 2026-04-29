# `IndexError` from `DLCPosV1.populate` — diagnosing the `PositionIntervalMap` gap

You aren't necessarily missing an upstream populate step in the way you're thinking, and `DLCPosSelection` is probably fine. The IndexError is almost always coming from `convert_epoch_interval_name_to_position_interval_name` (or a downstream selection step) failing to resolve a `PositionIntervalMap` row for this session's task epoch. The fix lives upstream in `IntervalList` / `PositionSource` / `RawPosition`, not in `DLCPosSelection`.

## Important context first — the converter already runs automatically

Before diving in, one thing the older docs get wrong: **`DLCPoseEstimation.make()` already calls the converter for you** (`src/spyglass/position/v1/position_dlc_pose_estimation.py:255-262`):

```python
interval_list_name = (
    convert_epoch_interval_name_to_position_interval_name(
        {
            "nwb_file_name": key["nwb_file_name"],
            "epoch": key["epoch"],
        },
    )
)
```

And `convert_epoch_interval_name_to_position_interval_name` defaults `populate_missing=True` (`src/spyglass/common/common_behav.py:1056-1057`). When that flag is set, the converter calls `PositionIntervalMap().make(key)` itself for any missing or null map row (`common_behav.py:1086-1089`).

So the old advice — "just call the converter manually with `populate_missing=True`" — is no longer the typical fix. That code path **already ran** during `DLCPoseEstimation.populate`, came up empty, and continued. The IndexError you're hitting now is a *downstream* symptom of the converter having returned nothing, typically:

- The `RawPosition` lookup at `position_dlc_pose_estimation.py:264-267` (only entered if `interval_list_name` was truthy — but if it returned `[]`, that's truthy enough to confuse downstream code in some shapes).
- A subsequent `DLCCentroid` / `DLCOrientation` / `DLCPosV1` step that still expects a real position interval to be resolvable for this epoch.

## Walk the diagnostic surface

### Layer 1 — Inspect `PositionIntervalMap` for this epoch directly

This is the single most useful check. The trick: `PositionIntervalMap` is **not** keyed by `epoch`. It inherits its primary key from `IntervalList` (`common_behav.py:954-959`):

```python
@schema
class PositionIntervalMap(SpyglassMixin, dj.Computed):
    definition = """
    -> IntervalList
    ---
    position_interval_name="": varchar(200)
    """
```

So the PK is `nwb_file_name + interval_list_name`. The converter accepts an `epoch` kwarg only because it translates it internally via `get_interval_list_name_from_epoch` (`common_behav.py:1075-1078, 1103-1129`). Resolve the interval name first, then restrict:

```python
from spyglass.common.common_behav import (
    PositionIntervalMap,
    get_interval_list_name_from_epoch,
)

interval_list_name = get_interval_list_name_from_epoch(nwb_file, epoch_id)
print(interval_list_name)

(PositionIntervalMap & {
    "nwb_file_name": nwb_file,
    "interval_list_name": interval_list_name,
}).fetch(as_dict=True)
```

Three outcomes, all diagnostic:

- **Empty result.** The converter never inserted *anything* for this epoch — usually means `get_interval_list_name_from_epoch` returned `None` (because `TaskEpoch` has 0 or >1 rows for this epoch — see `common_behav.py:1118-1127`). Inspect `(TaskEpoch & {"nwb_file_name": nwb_file, "epoch": epoch_id}).fetch(as_dict=True)`.
- **Row with `position_interval_name == ''`.** This is the *null entry* the populator inserts when no matching position interval is found (`common_behav.py:984, 990, 1031`). It's there to prevent re-running. Re-running the converter with `populate_missing=True` will not help — it sees the null entry, deletes it, re-runs `make()`, and re-inserts the same null. That's the same path that already ran.
- **Row with a real `position_interval_name`.** Then this layer is fine; the IndexError is from somewhere else (check tracebacks more carefully — e.g., an empty `RawPosition` fetch_nwb result, an empty `valid_times` array).

### Layer 2 — Confirm `PositionSource` / `RawPosition` and the recognized `IntervalList` rows exist

This is where the upstream-prerequisite question lives. `PositionIntervalMap._no_transaction_make` doesn't query `RawPosition` at all — it walks `IntervalList` rows whose names pass `PositionSource._is_valid_name()` (which is just `name.startswith("pos ") and name.endswith(" valid times")`, `common_behav.py:154-156`). The mapping uses `get_pos_interval_list_names` (`common_behav.py:1045-1053`).

So `PositionSource` and `RawPosition` matter as **prerequisites that anchor those `pos N valid times` rows during ingest**, not as tables `PositionIntervalMap` itself queries:

```python
from spyglass.common import (
    PositionSource, RawPosition, IntervalList, TaskEpoch,
)

(PositionSource & {"nwb_file_name": nwb_file}).fetch(as_dict=True)
(RawPosition  & {"nwb_file_name": nwb_file}).fetch(as_dict=True)

# Show all interval names; eyeball whether any look like "pos N valid times"
(IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_list_name")
```

If `PositionSource` / `RawPosition` are empty, that's a real missing-prereq problem — re-run ingestion for this session and look at `InsertError`:

```python
from spyglass.common import populate_all_common
from spyglass.common.errors import InsertError  # if needed by your install

populate_all_common(nwb_file, raise_err=True)
# then inspect InsertError rows for this session if anything was skipped
```

If they exist but **no `IntervalList` row has a name matching `pos N valid times`**, the source NWB doesn't carry the position-interval naming convention that Spyglass expects, and the converter has nothing to map onto. That's the data-shape variant of the same problem.

### Layer 3 — `TaskEpoch` ↔ `IntervalList` name and time-bounds alignment

If both layers above check out (you have `pos N valid times` rows AND a row in `PositionIntervalMap` for this `interval_list_name`), the failure mode is the EPSILON time-bounds match in `_no_transaction_make` (`common_behav.py:976, 994-1019`). The mapper requires that the task epoch's `valid_times[0][0]` and `valid_times[-1][-1]` both fall within `±0.51 s` of a position interval's bounds. If the user's data has a custom epoch name, a renamed interval, or a session split where the bounds don't line up, no match is found and the null row is inserted.

```python
te = (TaskEpoch    & {"nwb_file_name": nwb_file}).fetch("interval_list_name", "epoch", as_dict=True)
il = (IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_list_name", as_dict=True)
print("task epochs:", te)
print("interval names:", il)

# For the suspect epoch, compare its valid_times bounds against each pos-N-valid-times row:
ep_vt  = (IntervalList & {"nwb_file_name": nwb_file, "interval_list_name": interval_list_name}).fetch1("valid_times")
pos_vt = (IntervalList & {"nwb_file_name": nwb_file, "interval_list_name": "pos 0 valid times"}).fetch1("valid_times")
print("epoch  bounds:", ep_vt[0][0], ep_vt[-1][-1])
print("pos N bounds:", pos_vt[0][0], pos_vt[-1][-1])
```

A drift larger than ~0.5 s on either side is the typical culprit.

## Edge case — DLC-only session (no Trodes-derived position)

If the session genuinely has no Trodes-side position (camera-only / DLC-only), `DLCPoseEstimation.make()` is designed to handle that: when the converter returns no interval name, it falls back to the source video's timestamps and sets `spatial_series = None` (`position/v1/position_dlc_pose_estimation.py:263-269`). Pose estimation itself doesn't strictly require a `pos N valid times` row.

But the IndexError still surfaces *downstream* — `DLCCentroid`, `DLCOrientation`, or the `DLCPosV1`/`DLCPosSelection` step expects a resolvable position interval and pulls index `[0]` from an empty fetch. Two paths to fix:

- **Raw position is actually available** (you just hadn't ingested it yet) → populate `PositionSource` / `RawPosition` first so `pos N valid times` rows land in `IntervalList`. Then the converter can resolve them.
- **Genuinely DLC-only** → stop the DLC pipeline at `DLCPoseEstimation` for this session; don't insert `DLCCentroidSelection` / `DLCOrientationSelection` / `DLCPosSelection`. Those stages require a real position interval.

## What not to do

- **Don't just retry `DLCPosV1.populate(key)`** — the upstream gap will reproduce the same IndexError on the next run. The converter has already run with `populate_missing=True` and inserted (or refused to insert) what it could; re-running won't change anything until the upstream `IntervalList` / `PositionSource` data is right.
- **Don't blame `DLCPosSelection`** until you've confirmed Layer 1 returns a real `position_interval_name`. The selection table doesn't trigger the converter; `DLCPoseEstimation.make` does, and the IndexError originates there.

## TL;DR

Run Layer 1 first — `(PositionIntervalMap & {"nwb_file_name": nwb_file, "interval_list_name": interval_list_name}).fetch(as_dict=True)`. If it returns empty or `position_interval_name == ''`, the task epoch has no resolvable position interval, and the fix is upstream (Layer 2: confirm `PositionSource` / `RawPosition` ingested and `pos N valid times` rows exist; or Layer 3: confirm task-epoch and position-interval `valid_times` overlap within ~0.5 s). Re-running the converter or `DLCPosV1.populate` won't change anything — Spyglass already ran the converter for you.

### Source references

- `convert_epoch_interval_name_to_position_interval_name` and `populate_missing=True` default — `src/spyglass/common/common_behav.py:1056-1100`
- `get_interval_list_name_from_epoch` (the `epoch` → `interval_list_name` translator) — `src/spyglass/common/common_behav.py:1103-1129`
- `PositionIntervalMap` PK definition (inherits from `IntervalList`) — `src/spyglass/common/common_behav.py:953-959`
- Null-row insert when no match / no pos intervals — `src/spyglass/common/common_behav.py:984, 988-991, 1024-1032`
- `PositionSource._is_valid_name` (the `pos N valid times` filter) — `src/spyglass/common/common_behav.py:154-156`
- `get_pos_interval_list_names` (walks `IntervalList`, not `RawPosition`) — `src/spyglass/common/common_behav.py:1045-1053`
- `DLCPoseEstimation.make` calls the converter and falls back to video timestamps — `src/spyglass/position/v1/position_dlc_pose_estimation.py:255-269`
