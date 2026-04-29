# `Found 0 potential parts: []` — what it actually means

The error literally means what it says: `merge_get_part` walked every part table under `PositionOutput` and **zero of them had a row** matching your restriction. The `[]` is the list of matching part-table names — it's empty, not "ambiguous." So this is a *zero-source* error, not a *multi-source* error.

It is **not** saying "your `IntervalPositionInfo` rows don't exist." It's saying those rows were never propagated up into the merge part table `PositionOutput.CommonPos`. The merge master and the upstream source live in different rows in different tables.

Source: `src/spyglass/utils/dj_merge_tables.py:636` raises `f"Found {len(sources)} potential parts: {sources}"`. With zero matches, `len(sources) == 0` and `sources == []`.

## Confirm with one diagnostic

```python
len(PositionOutput.CommonPos & {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
})
# 0  ← confirms the merge-part row is missing
```

Compare with the upstream source (which you say has rows):

```python
from spyglass.common.common_position import IntervalPositionInfo

len(IntervalPositionInfo & {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
})
# >0  ← upstream populated, but never inserted into the merge
```

If the first is 0 and the second is non-zero, you've reproduced exactly the situation `Found 0 potential parts: []` is reporting.

## Why this happens specifically for `IntervalPositionInfo`

This is an **asymmetry** in the position pipeline that bites people. Not all three position sources auto-insert into `PositionOutput`:

| Source table | Auto-inserts into its `PositionOutput` part? | Where |
|---|---|---|
| `TrodesPosV1` | **Yes** | `make()` ends by calling `PositionOutput._merge_insert(...)` (`src/spyglass/position/v1/position_trodes_position.py:241`) |
| `DLCPosV1` | **Yes** | `make()` ends by calling `PositionOutput._merge_insert(...)` (`src/spyglass/position/v1/position_dlc_selection.py:82`) |
| `IntervalPositionInfo` (= `PositionOutput.CommonPos`'s source, aliased as `CommonPos` in `position_merge.py:5`) | **No** | `make()` ends at `self.insert1(key)` (`src/spyglass/common/common_position.py:145`); there is no `PositionOutput._merge_insert` call |

The mapping itself lives in `src/spyglass/position/position_merge.py:14-20`:

```python
source_class_dict = {
    "IntervalPositionInfo": CommonPos,   # i.e., PositionOutput.CommonPos's source
    "DLCPosV1": DLCPosV1,
    "TrodesPosV1": TrodesPosV1,
    "ImportedPose": ImportedPose,
    "DLCPoseEstimation": DLCPoseEstimation,
}
```

So when you populate `TrodesPosV1` or `DLCPosV1`, the merge part table is filled as a side effect of `make()` and `merge_get_part` "just works." When you populate `IntervalPositionInfo` (the legacy `common` position pipeline), nothing pushes those rows into `PositionOutput.CommonPos` for you.

That's why `IntervalPositionInfo` has rows but `merge_get_part` finds nothing.

## Fix: do the merge insert explicitly

After populating `IntervalPositionInfo`, push the keys into the merge yourself, naming the part with `part_name='CommonPos'`:

```python
from spyglass.common.common_position import IntervalPositionInfo
from spyglass.position.position_merge import PositionOutput

restriction = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
}

# 1. Confirm the upstream rows exist
rows = (IntervalPositionInfo & restriction).fetch("KEY", as_dict=True)
assert len(rows) > 0, "IntervalPositionInfo not populated for this restriction"

# 2. Push them into the merge part table (CommonPos)
PositionOutput._merge_insert(rows, part_name="CommonPos")

# 3. Now merge_get_part will resolve
part = PositionOutput.merge_get_part(restriction)
merge_key = part.fetch1("KEY")
df = (PositionOutput & merge_key).fetch1_dataframe()
```

A few things to note:

- **Don't** "fix" this by re-running `IntervalPositionInfo.populate(...)` — `populate` alone will not fill the merge, because the `make()` method doesn't have the merge-insert step. Re-running it changes nothing for `merge_get_part`.
- **Don't** call `PositionOutput.insert(...)` directly on the master. The merge master only has `merge_id` and `source` in its heading; you need both the master row and the matching part row, and `_merge_insert` handles both atomically (`src/spyglass/utils/dj_merge_tables.py:302`).
- `part_name` is the **CamelCase part name** (`"CommonPos"`), not the source class name. You need it here because passing the bare `IntervalPositionInfo` keys is otherwise ambiguous in principle — `_merge_insert` lets you pin the target part explicitly.

## TL;DR

- The error says zero, not many. `merge_get_part` found no part-table rows for your restriction.
- `IntervalPositionInfo`'s `make()` does **not** auto-insert into `PositionOutput.CommonPos`, unlike `TrodesPosV1`'s and `DLCPosV1`'s `make()` methods which do call `PositionOutput._merge_insert(...)`.
- Confirm with `len(PositionOutput.CommonPos & restriction) == 0`.
- Fix with `PositionOutput._merge_insert(rows, part_name='CommonPos')` after populating `IntervalPositionInfo`, then retry `merge_get_part`.
