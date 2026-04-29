# `KeyError: 'head_position_x'` from `_upsample` — DLC isn't missing the column, your `position_variables` override is the bug

Short version: **DLC's output is fine.** `DLCPosV1.fetch1_dataframe()` already emits a column literally named `position_x` (and `position_y`), the same names Trodes positions emit. `PositionGroup.create_group`'s default `position_variables=['position_x', 'position_y']` matches both upstream sources without modification. Overriding it with `['head_position_x', 'head_position_y']` points at columns that **do not exist on the merge-fetched DataFrame**, and `_upsample` raises `KeyError` while iterating those names. Don't re-run DLC populate — drop the override on `PositionGroup`.

## Evidence

`DLCPosV1.fetch1_dataframe()` constructs its DataFrame with this exact column list (`src/spyglass/position/v1/position_dlc_selection.py:175-191`):

```python
def fetch1_dataframe(self) -> pd.DataFrame:
    ...
    COLUMNS = [
        "video_frame_ind",
        "position_x",
        "position_y",
        "orientation",
        "velocity_x",
        "velocity_y",
        "speed",
    ]
```

There is no `head_position_x` / `head_position_y` here. The body-part naming you may be remembering lives upstream in the DLC pose tables (the per-bodypart pose blobs); by the time the centroid/head-position step has produced a `DLCPosV1` row and you call `fetch1_dataframe()` on it, the columns are flattened to the unprefixed `position_x` / `position_y` so they line up with `TrodesPosV1.fetch1_dataframe()`.

`PositionGroup.create_group` defaults to those exact names (`src/spyglass/decoding/v1/core.py:145-152`):

```python
def create_group(
    self,
    nwb_file_name: str,
    group_name: str,
    keys: list[dict],
    position_variables: list[str] = ["position_x", "position_y"],
    upsample_rate: float = np.nan,
):
```

And here's the line that actually raises your `KeyError` (`src/spyglass/decoding/v1/core.py:289-292`, inside `_upsample`):

```python
if position_variable_names is None:
    position_variable_names = position_df.columns
for column in position_variable_names:
    is_nan = position_df[column].isna().to_numpy().astype(int)
```

`position_df` is whatever `(PositionOutput & {"merge_id": pos_merge_id}).fetch1_dataframe()` returns — for your DLC source, the seven columns above. `position_variable_names` comes straight from `(PositionGroup & key).fetch1("position_variables")`, i.e. the override you supplied. The first iteration tries `position_df['head_position_x']`, that label isn't in the columns, pandas raises `KeyError: 'head_position_x'`, and you see it bubble out of `_upsample` / `fetch_position_info` (called from the decoding `make()`).

(Side note on when the error fires: `_upsample` only runs when `upsample_rate` is non-NaN — i.e. you set one when creating the group. If `upsample_rate` is NaN, `fetch_position_info` returns the DataFrame untouched and the same `KeyError` would instead fire later, in the decoding `make()` body when it slices the returned DataFrame by `position_variable_names`. Either way, the fix is the same.)

## Concrete diagnostic

Confirm the actual columns on the fetched DataFrame before changing anything:

```python
from spyglass.position.v1 import DLCPosV1

# `key` here should restrict DLCPosV1 to exactly one row — typically the
# same key you stashed in PositionGroup.Position via PositionOutput.DLCPosV1.
cols = list((DLCPosV1 & key).fetch1_dataframe().columns)
print(cols)
# Expected:
# ['video_frame_ind', 'position_x', 'position_y',
#  'orientation', 'velocity_x', 'velocity_y', 'speed']
```

If that list contains `position_x` and `position_y` (it should), DLC's output is correct and the only problem is the `PositionGroup.position_variables` override.

If — and only if — that list does NOT contain `position_x` / `position_y`, that would be a real DLC output problem (something went wrong upstream of `DLCPosV1.fetch1_dataframe()`); but that's not what your symptom indicates, and the `_upsample` traceback by itself doesn't prove it.

## Fix

Recreate the `PositionGroup` row with the **default** `position_variables`. Don't pass the head-prefixed names at all:

```python
from spyglass.decoding import PositionGroup
from spyglass.position.v1 import DLCPosV1

# Sanity-check the columns the merge-fetched DLC DataFrame actually exposes.
cols = list((DLCPosV1 & key).fetch1_dataframe().columns)
# DLCPosV1 typically emits position_x, position_y (alongside orientation,
# velocity_x, velocity_y, speed, video_frame_ind).
assert "position_x" in cols and "position_y" in cols, cols

PositionGroup().create_group(
    nwb_file_name=nwb_file_name,
    group_name=position_group_name,
    keys=[merge_key],                              # PositionOutput.DLCPosV1 merge entries
    position_variables=["position_x", "position_y"],   # the default — no override
    # upsample_rate=...   # only set if you actually need upsampling
)
```

You'll need to delete the existing (broken) `PositionGroup` row first if one exists with the head-prefixed override; `create_group` is a no-op when the group key already exists (it logs and returns instead of overwriting — see `core.py:158-163`).

Then re-insert the `ClusterlessDecodingSelection` row pointing at the corrected `PositionGroup` and re-populate:

```python
from non_local_detector import __version__ as non_local_detector_version

selection_key = {
    "nwb_file_name": nwb_file_name,
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)
```

## What NOT to do

- **Don't re-run DLC populate.** The DLC outputs already have the columns the decoder expects; rerunning won't change `position_x` / `position_y`.
- **Don't try to "rename" columns inside `DLCPosV1`** to satisfy the override. The shared decoding pipeline is built around the unprefixed names; Trodes and DLC both emit them precisely so `PositionGroup` can handle either source uniformly.
- **Don't keep the head-prefixed names "for clarity" and patch around the `KeyError`.** The `position_variables` field is a hard contract with the upstream DataFrame's columns — there's no mapping layer.
