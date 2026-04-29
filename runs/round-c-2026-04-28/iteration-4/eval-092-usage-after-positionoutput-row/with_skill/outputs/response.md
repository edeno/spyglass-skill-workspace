# Next steps for a `PositionOutput` `merge_id`

`PositionOutput` is one of the five Spyglass merge masters (`src/spyglass/position/position_merge.py:24`). Its only primary-key column is `merge_id`, so a bare `merge_id` is enough to address a row, but what you do next depends on whether you want the **data** or the **part-table identity** behind it.

The `merge_key` below is the dict `{"merge_id": "..."}`.

## 1. Treat the merge_id as an opaque restriction

Wrap it as a dict and pass it to `&`. Don't pull fields out of it; treat it as opaque. The canonical shape is:

```python
merge_key = {"merge_id": merge_id}            # opaque restriction

# Sanity check cardinality before fetch1 — full-PK restriction is unique,
# but it's still cheap to confirm the row exists:
assert len(PositionOutput & merge_key) == 1
```

## 2. Most common: fetch the position dataframe

`PositionOutput.fetch1_dataframe()` is a dispatcher (`position/position_merge.py:81`) that delegates to whichever part the entry resolves to (`TrodesPosV1`, `DLCPosV1`, or `CommonPos`). For Trodes/DLC/CommonPos entries you get back a DataFrame with columns `position_x`, `position_y`, `orientation`, `velocity_x`, `velocity_y`, `speed`:

```python
df = (PositionOutput & merge_key).fetch1_dataframe()
```

Caveat: if the merge entry is from `ImportedPose`, `fetch1_dataframe` is **not implemented** on that part — use `PositionOutput.fetch_pose_dataframe(merge_key)` (the merge-level dispatcher routes to `ImportedPose.fetch_pose_dataframe`) or for DLC use the same dispatcher to get per-bodypart pose.

## 3. Find out *which* part table the entry came from

If you need to know whether this is Trodes, DLC, CommonPos, or ImportedPose — for example, to branch on source-specific columns — use `merge_get_part`:

```python
part = PositionOutput.merge_get_part(merge_key)   # raises if 0 or >1 sources
# part is one of PositionOutput.TrodesPosV1, .DLCPosV1, .CommonPos, .ImportedPose
source = PositionOutput.get_source_from_key(merge_key)   # CamelCase string
```

Note the classmethod-restriction-discard footgun: call `PositionOutput.merge_get_part(merge_key)`, **not** `(PositionOutput & merge_key).merge_get_part()` — the latter silently drops the restriction and runs against the whole table.

## 4. Walk one further to the source/parent table

`merge_get_parent` returns the actual upstream Computed/Manual table (e.g. `TrodesPosV1` itself), in case you need attributes that live there but not on the merge part:

```python
parent = PositionOutput.merge_get_parent(merge_key)   # FreeTable view
parent_rows = parent.fetch(as_dict=True)
```

## 5. Use the merge_id as a key into downstream pipelines

`PositionOutput` is upstream of several pipelines. They consume your `merge_id` via the projected-FK rename pattern — i.e. they expect `pos_merge_id`, not `merge_id`, in the populate key:

- **Ripple detection** (`RippleTimesV1`, `ripple.py:186`): `-> PositionOutput.proj(pos_merge_id='merge_id')`.
- **MUA detection** (`MuaEventsV1`, `mua.py:67-68`): also renames `merge_id` to `pos_merge_id`.
- **Linearization** (`LinearizedPositionV1`) and decoding pipelines that condition on position likewise FK to `PositionOutput`.

So a typical downstream insert looks like:

```python
selection_key = {
    "pos_merge_id": merge_id,            # NOT "merge_id"
    # ... other PK fields for the selection table
}
SomeDownstreamSelection.insert1(selection_key)
SomeDownstreamComputed.populate(selection_key)
```

To detect the rename for any specific consumer, read its `definition` and look for `.proj(foo='merge_id')` inside an FK line — `foo` is what your populate key needs.

## 6. Fetch the underlying NWB object (only if the part is NWB-backed)

```python
nwb_objs = (PositionOutput & merge_key).fetch_nwb()
```

## TL;DR

If you don't yet know what you want to *do* with the entry, the single most useful next call is:

```python
df = (PositionOutput & {"merge_id": merge_id}).fetch1_dataframe()
```

That gives you the position time series. From there, branch into ripple/MUA/linearization/decoding by passing `pos_merge_id=merge_id` into the relevant downstream selection table.
