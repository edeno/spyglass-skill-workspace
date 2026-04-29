# Counterfactual: swapping `trodes_pos_params_name` from `default` to `default_smooth_50`

## Short answer

You will not "modify" any existing rows. You'll **create a new parallel set of rows**, and almost nothing downstream will follow automatically. Specifically:

- A **new** `TrodesPosSelection` row is inserted (different PK).
- A **new** `TrodesPosV1` row is computed.
- A **new** `PositionOutput` row appears, with a **new `merge_id`** (UUID) under the `PositionOutput.TrodesPosV1` part.
- Every downstream table that was already populated against the old `merge_id` is **unchanged** and **still points at the `default` result**. Re-pointing them at `default_smooth_50` is a separate, manual step (new selection rows + populate, often per pipeline).

The old rows do not disappear and are not overwritten.

## Why — the keys make this mechanical

`TrodesPosSelection`'s primary key is the triple `(nwb_file_name, interval_list_name, trodes_pos_params_name)` (per the skill's Trodes reference). `trodes_pos_params_name` is part of the PK, so changing it doesn't update a row — it identifies a *different* row. `TrodesPosV1` inherits that PK, so the same logic propagates: a new selection PK gives a new computed PK.

`TrodesPosV1.make()` then calls `PositionOutput._merge_insert(...)` (`position/v1/position_trodes_position.py:241`), which mints a **fresh `merge_id` UUID** for the new (nwb_file, interval, params) combination. The old `merge_id` for the `default` run is untouched in `PositionOutput` and `PositionOutput.TrodesPosV1`.

## What "differs" downstream — and what doesn't

### Newly created rows (the only things that change after `populate()`):

1. `TrodesPosSelection` — one new row keyed by `trodes_pos_params_name="default_smooth_50"`.
2. `TrodesPosV1` — one new row, same key plus the computed analysis-NWB pointer. New `position_x/_y/orientation/velocity_x/velocity_y/speed` time series stored in a new analysis NWB file.
3. `PositionOutput` (master) — one new row with a new `merge_id`.
4. `PositionOutput.TrodesPosV1` (part) — one new row mapping that new `merge_id` to the new `TrodesPosV1` PK.

You can confirm with:

```python
PositionOutput.merge_restrict(
    {"nwb_file_name": nwb_file, "interval_list_name": "pos 1 valid times"}
)
# Should now show TWO entries (default + default_smooth_50), not one.
```

### Rows that DO NOT differ (common misconception)

Anything that previously consumed `PositionOutput` via the **old** `merge_id` keeps its old `merge_id` FK and therefore keeps consuming the `default` smoothing. Re-populating `TrodesPosV1` does **not** cascade through merge tables — merge tables are FK'd by `merge_id`, and the new run has a new UUID, so downstream rows simply don't match it.

In a typical Frank-lab pipeline graph, the position-driven downstream consumers include:

- `LinearizedPositionV1` / `LinearizedPositionOutput` (linearization is FK'd to `PositionOutput`)
- `RippleTimesV1` / position-based ripple gating that uses `speed` from `PositionOutput`
- `MuaEventsV1` (consumes position speed via `PositionOutput`)
- `ClusterlessDecodingV1` and `SortedSpikesDecodingV1` (their `*Selection` rows reference a `PositionOutput.merge_id`, sometimes via a `PositionGroup`)

None of those rows update on their own. To make any of them reflect the smoothed position, you need to:

1. Look up the new `merge_id`:
   ```python
   new_merge_key = PositionOutput.merge_get_part({
       "nwb_file_name": nwb_file,
       "interval_list_name": "pos 1 valid times",
       "trodes_pos_params_name": "default_smooth_50",
   }).fetch1("KEY")
   ```
2. Insert **new** selection rows for each downstream pipeline you care about, pointing at `new_merge_key["merge_id"]` (and any associated `*PositionGroup` if the pipeline uses one).
3. Re-`populate()` those pipelines.

Until you do that, `(PositionOutput & old_merge_id)` and every downstream row that already references it will return the **same numbers as before** — the change is invisible to them.

## A subtle point worth flagging

I have not verified the exact set of FK paths from `PositionOutput` to every downstream pipeline against the installed Spyglass source in this run; the Trodes reference and merge-table reference confirm the merge layer's behavior and the `_merge_insert` call site, but to enumerate the *actual* rows that need re-running for your install, run:

```python
from spyglass.position import PositionOutput
PositionOutput.descendants(as_objects=True)
```

That gives the authoritative list of tables whose new rows you'd need to insert + populate to propagate `default_smooth_50` through the rest of the graph. The list above (linearization, ripple, MUA, decoding) is the typical Frank-lab subset, not a guarantee for an arbitrary install.

## TL;DR

Changing `trodes_pos_params_name` and re-populating creates a parallel `TrodesPosV1` row and a new `PositionOutput.merge_id`. Nothing downstream re-runs. To get smoothed position into ripple/MUA/decoding/linearization you must insert new selection rows pointing at the new `merge_id` and populate each pipeline yourself.
