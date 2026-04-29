# `fetch1` returned 14 rows — too-loose restriction on a merge table

## Symptom

```
datajoint.errors.DataJointError:
    fetch1 should only be called on one tuple, but 14 were returned
```

triggered by

```python
(PositionOutput & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1_dataframe()
```

## What is actually going on

`PositionOutput` is a **merge master** (`spyglass.position.position_merge.PositionOutput`, defined at `src/spyglass/position/position_merge.py:26` as `class PositionOutput(_Merge, SpyglassMixin)`). The only column in its primary key is `merge_id` — a UUID. Its part tables (the actual data sources) are:

| Part | Source class |
| --- | --- |
| `PositionOutput.TrodesPosV1` | LED-based Trodes tracking |
| `PositionOutput.DLCPosV1` | DeepLabCut pose |
| `PositionOutput.CommonPos` | Legacy `IntervalPositionInfo` |
| `PositionOutput.ImportedPose` | Pre-computed pose from NWB |

So `{'nwb_file_name': 'j1620210710_.nwb'}` does **not** identify "the position for this session." It identifies *every* row that was ever inserted into `PositionOutput` for that NWB file — across every source (Trodes / DLC / CommonPos / ImportedPose), every interval (`02_r1`, `04_r2`, ...), and every parameter set (`default`, `default_decoding`, custom names). 14 rows is the cross-product of all of those for this session.

`PositionOutput.fetch1_dataframe()` (at `src/spyglass/position/position_merge.py:92`) calls `self.merge_restrict(self.proj()).proj()` and then a downstream `fetch1_dataframe()` on the resolved part — both of those expect exactly one row, so 14 rows blows up.

There is also a sharper version of this footgun lurking nearby: a restriction by a field that isn't on the master heading (here `nwb_file_name` — the master only has `merge_id`) is silently no-op'd by DataJoint; you only got an error here because a downstream call tried to collapse to one row. Always reach for `merge_restrict` / `merge_get_part` on merge masters; `&` alone is a footgun on them.

## Step 1 — discover what those 14 rows actually are

Don't guess at parameter names. Run the discovery first:

```python
from spyglass.position import PositionOutput

session_key = {'nwb_file_name': 'j1620210710_.nwb'}

# Walks the parts and resolves the session restriction properly:
PositionOutput.merge_restrict(session_key)

# More useful: see WHICH part each merge_id came from
PositionOutput.merge_get_part(session_key, multi_source=True, join_master=True)
```

`merge_get_part(..., multi_source=True)` returns one part-table view per source that has matches. From that you'll see, for each row, the source (Trodes vs DLC vs ImportedPose vs CommonPos), the `interval_list_name`, and the source-specific parameter name. That tells you whether the 14 = (e.g.) 2 sources x 7 intervals, 1 source x 7 intervals x 2 param sets, etc.

## Step 2 — narrow to one row

Two valid shapes, depending on what you want:

### (a) Stay source-agnostic — pick the one `merge_id` you want

```python
# Using merge_get_part to fetch a specific part row (whichever source),
# then taking its merge_id:
part = PositionOutput.merge_get_part({
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': 'pos 1 valid times',   # use a real one from step 1
})
merge_key = part.fetch1('KEY')   # {'merge_id': <uuid>}

df = (PositionOutput & merge_key).fetch1_dataframe()
```

This is the right shape if downstream code only needs "the position dataframe for this epoch" and shouldn't care whether it came from Trodes or DLC.

### (b) Build a fully-specified key against the source you actually want

This requires knowing the source — get it from step 1, don't assume. The PK fields differ per source:

- **Trodes** (`TrodesPosV1`, `position/v1/position_trodes_position.py:55`): PK is `nwb_file_name`, `interval_list_name`, `trodes_pos_params_name`.
- **DLC** (`DLCPosV1`): PK includes `nwb_file_name`, `interval_list_name`, `dlc_si_cohort_selection_name`, `dlc_pos_params_name`, etc. — multi-step pose-estimation chain, so the key is wider.
- **ImportedPose**: PK is `nwb_file_name`, `interval_list_name`. Note that `PositionOutput.fetch1_dataframe()` does NOT work for ImportedPose entries — call `ImportedPose().fetch_pose_dataframe(key)` directly, or use `PositionOutput.fetch_pose_dataframe()` which dispatches.

If step 1 confirmed Trodes:

```python
part = PositionOutput.TrodesPosV1 & {
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': '<one from step 1>',
    # plus the trodes_pos_params_name from step 1; do NOT hardcode 'default'
    # without confirming a row exists with that value
}
merge_key = (PositionOutput & part).fetch1('KEY')
df = (PositionOutput & merge_key).fetch1_dataframe()
```

The cardinality discipline: keep adding PK fields until `len((SourcePart & key)) == 1`, and only then collapse to a `merge_id` and call `fetch1_dataframe()`.

## Robust pattern going forward

Before any `fetch1`, `merge_get_part`, or `fetch1_dataframe` on a partial restriction:

```python
rel = SomeRel & key
n = len(rel)
assert n == 1, f"{n} rows match {key}; PK fields = {rel.primary_key}"
```

For merge masters specifically: never restrict the master with a non-`merge_id` field via `&`. Reach for `merge_restrict` (read-only view across parts) or `merge_get_part` (returns the part rows themselves). The master heading only has `merge_id`, and DataJoint silently drops attributes it doesn't recognize — so `len(PositionOutput & {'nwb_file_name': f})` would have given you the *whole* master table count, not 14, if `fetch1_dataframe` hadn't tripped over its own `merge_restrict` first.

## TL;DR

- `{'nwb_file_name': ...}` is not a unique key for `PositionOutput` — it's a merge table across 4 sources x N intervals x M parameter sets.
- Run `PositionOutput.merge_get_part({'nwb_file_name': ...}, multi_source=True, join_master=True)` first to see what the 14 rows are and which source each came from.
- Then either (a) narrow to one `merge_id` and call `(PositionOutput & merge_key).fetch1_dataframe()`, or (b) build a fully-specified key against the specific source part table the discovery step revealed.
- Don't assume Trodes — your prompt doesn't say which pipeline you populated. The discovery step tells you.
