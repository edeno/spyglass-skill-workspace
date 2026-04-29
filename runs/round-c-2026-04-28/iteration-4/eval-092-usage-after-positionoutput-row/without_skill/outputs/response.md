# Working with a `PositionOutput` merge entry

Once you have a `merge_id` for a row in `PositionOutput`, the merge table itself only stores the foreign-key pointer back to whichever upstream "part" table actually computed the position (e.g. `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`, `PositionOutput.CommonPos`, etc.). The next step is almost always to **resolve that pointer and pull out the actual position data** as a pandas DataFrame or NWB object.

## 1. The standard pattern: `fetch1_dataframe`

Spyglass merge tables expose helpers that hide the "which part table?" dispatch for you. Given a single `merge_id`, the most common next call is:

```python
from spyglass.position import PositionOutput

key = {"merge_id": "<your-uuid-here>"}

# Pandas DataFrame indexed by time, with columns like
# position_x, position_y, orientation, velocity_x, velocity_y, speed
pos_df = (PositionOutput & key).fetch1_dataframe()
```

`fetch1_dataframe` on the merge table walks to the correct part table, finds the analysis NWB file it produced, and returns the position time series as a DataFrame. This is the workhorse you'll use 90% of the time.

## 2. If you want the underlying NWB object instead

```python
nwb_list = (PositionOutput & key).fetch_nwb()
# nwb_list[0] is a dict-like with the pynwb Position / Spatial Series objects
position_obj = nwb_list[0]["position"]   # pynwb.behavior.Position
```

Use this when you need timestamps/units/metadata that the flat DataFrame drops, or when you want to feed the raw `SpatialSeries` into another pipeline.

## 3. Find out *which* upstream method produced it

Sometimes you want to know whether this row came from Trodes online tracking, DLC, or a common/imported source — e.g. to branch on processing assumptions:

```python
parent = PositionOutput.merge_get_parent(key)        # restricted parent part table
parent_key = PositionOutput.merge_get_parent(key).fetch1("KEY")
# or, to get the source table class itself:
source = PositionOutput.merge_get_part(key)
print(source.table_name)
```

## 4. Typical downstream uses

A `PositionOutput` row is usually an *input* to something else. The common next moves are:

- **Plot it** — `pos_df.plot(x="position_x", y="position_y")` for a quick trajectory check, or overlay `speed` vs. time to sanity-check tracking gaps.
- **Linearize** — feed `merge_id` into `LinearizationSelection` / `LinearizedPositionV1` (in `spyglass.linearization`) to project 2D position onto a track graph.
- **Decoding / replay** — `PositionOutput` `merge_id` is the canonical position handle for `spyglass.decoding` (e.g. `DecodingParameters` + `ClusterlessDecodingV1` / `SortedDecodingV1`); you pass the `merge_id` directly into the decoder's selection table.
- **Align with spikes / LFP / DIO** — join on `nwb_file_name` + `interval_list_name` (fetch them from the parent part table via `merge_get_parent`) to pull the matching epoch from `IntervalList`, then restrict spike/LFP tables to the same interval before resampling onto `pos_df.index`.

## 5. Quick sanity checks before you use it

Cheap things worth doing once on a fresh `merge_id`:

```python
print((PositionOutput & key).fetch1())          # confirms the row exists & is unique
parent = PositionOutput.merge_get_parent(key)
print(parent)                                    # which part table, which params
pos_df = (PositionOutput & key).fetch1_dataframe()
print(pos_df.shape, pos_df.index[0], pos_df.index[-1])
print(pos_df.isna().mean())                      # NaN fraction per column
```

Specifically check: NaN fraction in `position_x/y` (gaps in tracking), the time range vs. the epoch you expected, and whether `speed` looks physically plausible (no >5 m/s spikes for a rat). If any of those look off, the issue is in the upstream pipeline (Trodes/DLC config), not in how you're consuming the merge row.

---

**Short answer:** call `(PositionOutput & {"merge_id": ...}).fetch1_dataframe()` to get the position time series, then either plot/inspect it or pass the same `merge_id` into the next stage (linearization or decoding). Use `PositionOutput.merge_get_parent(key)` if you need to know which upstream method produced it.
