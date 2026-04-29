# Fetching Trodes position via `PositionOutput`

You want the merge-wrapper-routed call so downstream consumers see only `merge_id`s, not part-specific keys. That's a two-step pattern: resolve the `merge_id` from your `(nwb_file_name, interval_list_name, trodes_pos_params_name)` triple via the part, then restrict `PositionOutput` by that `merge_id` and call `fetch1_dataframe()` on the master.

```python
from spyglass.position import PositionOutput

# 1. Resolve the merge_id from the part-table fields you actually know.
#    `trodes_pos_params_name` is required to disambiguate which TrodesPosV1
#    selection row you mean — without it a session can match multiple
#    parameter variants and `fetch1` will raise.
part_key = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
    "trodes_pos_params_name": "default",
}

merge_key = (PositionOutput.TrodesPosV1 & part_key).fetch1("KEY")
# merge_key is now {"merge_id": <uuid>} — safe to pass to any
# PositionOutput-keyed downstream code.

# 2. Fetch the dataframe through the merge master.
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

The dispatcher on the master (`PositionOutput.fetch1_dataframe`, `position/position_merge.py:81`) routes to `TrodesPosV1.fetch1_dataframe()` once it sees the `merge_id` resolves to the `TrodesPosV1` part — that's exactly what you want for a merge-wrapper-routed call.

## Equivalent helper: `merge_get_part`

If you'd rather not name the part class explicitly, use the merge helper:

```python
merge_key = PositionOutput.merge_get_part(part_key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```

`merge_get_part` (`utils/dj_merge_tables.py:580`) walks the parts, finds the one whose heading covers your restriction (`TrodesPosV1` here), and returns its native part table restricted by `part_key`. It raises `ValueError` if your restriction matches more than one part — which is why including `trodes_pos_params_name` matters: it nails down both *which* part and *which* row.

## A few sanity checks before `fetch1`

You said the pipeline has already been run, so populate isn't the concern — but `fetch1()` on a partial restriction is a top-3 footgun. Quick guards:

```python
# How many TrodesPosV1 rows match? Should be exactly 1.
print(len(PositionOutput.TrodesPosV1 & part_key))

# Confirm the params row exists (and 'default' is the canonical name).
PositionOutput.TrodesPosV1 & part_key  # render in a notebook, or .fetch(as_dict=True)
```

If `len(...)` is 0: the populate didn't reach the merge layer for this `(session, interval, params)` combo — re-check `TrodesPosSelection` and that `TrodesPosV1.populate(part_key)` actually inserted. If it's >1: you have multiple `trodes_pos_params_name` variants for that interval and need to pick one (the `default` filter should already do that, so `>1` here would be unexpected).

## What NOT to do

- **Don't** restrict the master by part-table fields directly:

  ```python
  PositionOutput & {"nwb_file_name": "j1620210710_.nwb"}   # silent no-op
  ```

  `PositionOutput`'s heading is just `merge_id` (plus the part-source bookkeeping); DataJoint silently drops unknown attributes from a dict restriction, so this returns the *whole* `PositionOutput` table, not your row. Common Mistake #6 in the skill.

- **Don't** call `(PositionOutput & part_key).fetch1_dataframe()` directly with the part-table fields for the same reason.

- **Don't** reach into `TrodesPosV1.fetch1_dataframe()` directly when you specifically want the merge-wrapper path — it works, but then downstream code has to know "this came from Trodes" instead of carrying a generic `merge_id`.

## Sources

- `spyglass/position/position_merge.py:81` — `PositionOutput.fetch1_dataframe` dispatcher
- `spyglass/position/v1/position_trodes_position.py:241` — `TrodesPosV1.make` calls `PositionOutput._merge_insert(...)`, which is why a populated `TrodesPosV1` row guarantees a corresponding `PositionOutput.TrodesPosV1` row
- `spyglass/utils/dj_merge_tables.py:580` — `merge_get_part` signature and multi-source error
- Skill references: `position_pipeline.md` (per-source method matrix), `position_trodes_v1_pipeline.md` (canonical example), `merge_methods.md` (silent-wrong-count footgun on master restriction)
