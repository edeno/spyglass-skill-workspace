# `Found 0 potential parts: []` from `merge_get_part` — what it really means

## Decoding the error

The message looks confusing because Spyglass's merge-table code reuses one error path for both "too few" and "too many" matches. The relevant block in `spyglass/utils/dj_merge_tables.py` (around line 634) is:

```python
if not multi_source and len(sources) != 1:
    raise ValueError(
        f"Found {len(sources)} potential parts: {sources}\n\t"
        + "Try adding a restriction before invoking `get_part`.\n\t"
        + "Or permitting multiple sources with `multi_source=True`."
    )
```

So the same `ValueError` gets raised whenever the count is anything other than 1 — including zero. The "Try adding a restriction… `multi_source=True`" hint in the message is misleading in your case: those tips are for the *too many* case. Your case is the *too few* case.

`Found 0 potential parts: []` literally means: **for the restriction you supplied, there are zero rows in any of the `PositionOutput` part tables (`PositionOutput.CommonPos`, `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`, `PositionOutput.ImportedPose`, `PositionOutput.DLCPoseEstimation`).** It does *not* mean "I found multiple ambiguous matches and gave up."

## Why your `IntervalPositionInfo` rows didn't help

Here is the gotcha that is biting you. `IntervalPositionInfo` and `PositionOutput.CommonPos` are **two different tables**. Look at `spyglass/position/position_merge.py`:

```python
# position_merge.py:5
from spyglass.common.common_position import IntervalPositionInfo as CommonPos

# position_merge.py:14-20
source_class_dict = {
    "IntervalPositionInfo": CommonPos,
    "DLCPosV1":              DLCPosV1,
    "TrodesPosV1":            TrodesPosV1,
    "ImportedPose":           ImportedPose,
    "DLCPoseEstimation":      DLCPoseEstimation,
}
```

So the *source* table for `PositionOutput.CommonPos` is `IntervalPositionInfo` — but having rows in `IntervalPositionInfo` does **not** by itself give you rows in `PositionOutput.CommonPos`. The merge part table is downstream of the source; somebody (or some `make()`) has to actively insert into it.

This is where the per-pipeline asymmetry shows up:

- **`TrodesPosV1.make()`** ends with an explicit `PositionOutput._merge_insert(...)` call — so populating `TrodesPosV1` *also* populates `PositionOutput.TrodesPosV1` automatically (see `position/v1/position_trodes_position.py` around line 238–241).
- **`DLCPosV1.make()`** does the same — its docstring even says "Inserts the key into the table, and the PositionOutput Merge table" (`position/v1/position_dlc_selection.py` around line 62; the `_merge_insert` call is around line 85).
- **`IntervalPositionInfo.make()`** does **not** do this. It populates `IntervalPositionInfo` and stops. Nothing in the common module knows about `PositionOutput`.

That asymmetry is why the Trodes and DLC flows feel seamless — you just `populate()` and everything downstream "just works" — but the `CommonPos` flow needs a manual second step. Easy to miss if you've been using one of the V1 pipelines and assume the same applies here.

## Diagnostic: confirm zero rows in the part table

Before doing anything else, run this — it should return `0`:

```python
restriction = {'nwb_file_name': 'j1620210710_.nwb',
               'interval_list_name': '02_r1'}

len(PositionOutput.CommonPos & restriction)        # 0  -> merge insert missing
len(IntervalPositionInfo  & restriction)           # >0 -> source rows exist
```

If `IntervalPositionInfo` has the rows but `PositionOutput.CommonPos` is empty for the same restriction, you've confirmed the diagnosis: source populated, merge part not. Worth also checking the other parts so you know nothing is hiding there:

```python
for part_name in ['CommonPos', 'TrodesPosV1', 'DLCPosV1',
                  'ImportedPose', 'DLCPoseEstimation']:
    n = len(getattr(PositionOutput, part_name) & restriction)
    print(part_name, n)
```

If every part comes back `0`, that's exactly what `Found 0 potential parts: []` was telling you.

## Fix: insert the source rows into the merge part table explicitly

You want `PositionOutput._merge_insert`, with `part_name='CommonPos'`, fed the rows from `IntervalPositionInfo`. Roughly:

```python
from spyglass.position import PositionOutput
from spyglass.common.common_position import IntervalPositionInfo

restriction = {'nwb_file_name': 'j1620210710_.nwb',
               'interval_list_name': '02_r1'}

# 1. Make sure IntervalPositionInfo is populated for this session.
#    (Skip if you've already done this.)
IntervalPositionInfo.populate(restriction)

# 2. Push those rows into the merge.
rows = (IntervalPositionInfo & restriction).fetch('KEY')
PositionOutput._merge_insert(rows, part_name='CommonPos')
```

After that, `PositionOutput.merge_get_part(restriction)` will find the row and return the `CommonPos` part table.

## Things *not* to do

- **Don't** call `PositionOutput.insert(...)` directly on the master. Merge masters in Spyglass are designed to be inserted into via `_merge_insert`, which (a) generates the `merge_id` UUID, (b) sets the `source` field correctly, and (c) inserts the matching part-table row in one transaction. Hand-inserting into the master leaves the parts inconsistent.
- **Don't** assume "I just need to `IntervalPositionInfo.populate(...)` again." Re-populating the source won't help — it doesn't touch `PositionOutput.CommonPos`. The missing step is the explicit `_merge_insert`.
- **Don't** try `multi_source=True` to silence the error. That argument is for the opposite problem (a restriction that matches multiple part tables); with zero matches it will just return `None` and your downstream code will fail later in a more confusing way.

## TL;DR

`Found 0 potential parts: []` = the merge has no part-table row for your restriction. For `IntervalPositionInfo` → `PositionOutput.CommonPos`, the source's `make` doesn't auto-insert into the merge (unlike `TrodesPosV1` and `DLCPosV1`). Confirm with `len(PositionOutput.CommonPos & restriction) == 0`, then fix with `PositionOutput._merge_insert(rows, part_name='CommonPos')`.
