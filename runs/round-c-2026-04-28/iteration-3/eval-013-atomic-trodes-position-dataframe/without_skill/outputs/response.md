# Fetching the Trodes position dataframe through `PositionOutput`

The merge wrapper `PositionOutput` exposes a `fetch1_dataframe()` that
dispatches to whichever upstream part is selected by your restriction.
To use the wrapper (so downstream code only ever needs a `merge_id`),
you do this in two steps:

1. Resolve the `merge_id` for your session/interval/params by
   restricting the **part table** `PositionOutput.TrodesPosV1`.
2. Restrict `PositionOutput` itself by that key and call
   `fetch1_dataframe()` on the merge master.

The first step needs `trodes_pos_params_name` because there is one
`PositionOutput.TrodesPosV1` row per `(nwb_file_name,
interval_list_name, trodes_pos_params_name)` triple — without it you
risk hitting multiple param entries and getting a `fetch1` error.

```python
from spyglass.position import PositionOutput

restriction = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
    "trodes_pos_params_name": "default",
}

# Step 1: resolve the merge key from the part table.
# `.fetch1("KEY")` returns just the primary-key dict (i.e. {"merge_id": ...}),
# which is what the merge wrapper wants.
merge_key = (PositionOutput.TrodesPosV1 & restriction).fetch1("KEY")

# Step 2: route through the merge master.
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```

`position_df` will be a pandas `DataFrame` indexed by time with the
standard Trodes position columns (`position_x`, `position_y`,
`orientation`, `velocity_x`, `velocity_y`, `speed`, exact set depends
on your `default` params).

## Why this shape and not a direct `TrodesPosV1` fetch

`PositionOutput.fetch1_dataframe()` (defined in
`spyglass/position/position_merge.py`) internally does
`merge_restrict` + `merge_get_parent` to find the upstream source
table for the matched `merge_id`, then calls `.fetch1_dataframe()` on
that source. So calling it on `(PositionOutput & merge_key)` gives
you the same dataframe you would have gotten from
`(TrodesPosV1 & ...).fetch1_dataframe()`, but downstream callers only
need the opaque `merge_id` — they don't have to know the row came from
Trodes vs. DLC vs. CommonPos.

## A one-liner alternative (same result)

If you'd rather not name `merge_key` explicitly, you can chain it.
The merge wrapper's helpers work too:

```python
merge_key = PositionOutput.merge_get_part(restriction, restrict_part=False).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```

but the explicit `PositionOutput.TrodesPosV1 & restriction` form is
the most readable and is what most internal Spyglass code uses.

## Sanity checks before you trust the dataframe

- Confirm exactly one row matched:
  `len(PositionOutput.TrodesPosV1 & restriction) == 1`. If zero, the
  pipeline didn't actually populate this combo (the
  `(nwb_file_name, interval_list_name, trodes_pos_params_name)` triple
  may not match a `TrodesPosSelection` entry). If >1, your
  restriction is under-specified.
- `position_df.index` should be monotonically increasing time in
  seconds; spot-check `position_df.head()` and the time span against
  the interval bounds in `IntervalList`.
