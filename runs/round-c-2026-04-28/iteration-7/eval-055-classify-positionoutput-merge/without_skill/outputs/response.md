# `PositionOutput` is a **merge table**, not a regular computed table

That's why it has no `populate()` method — merge tables don't compute anything themselves. They're a Spyglass-specific pattern that unifies several upstream "source" pipelines under one downstream identity, and rows get inserted *by* those upstream pipelines (or by you calling a helper), not by a `make()` function.

## What a merge table actually is

In Spyglass, `PositionOutput` lives in `spyglass.position.position_merge` and is built on the `_Merge` superclass (from `spyglass.utils.dj_merge_tables`). The pattern looks roughly like:

```python
@schema
class PositionOutput(_Merge, SpyglassMixin):
    definition = """
    merge_id: uuid
    ---
    source: varchar(32)
    """

    class TrodesPosV1(SpyglassMixin, dj.Part):
        definition = """
        -> master
        ---
        -> TrodesPosV1
        """

    class DLCPosV1(SpyglassMixin, dj.Part):
        definition = """
        -> master
        ---
        -> DLCPosV1
        """

    class CommonPos(SpyglassMixin, dj.Part):
        definition = """
        -> master
        ---
        -> IntervalPositionInfo
        """
```

The master table has only `merge_id` (a UUID) and a `source` string identifying which upstream pipeline produced this row. Each *part table* points back to one specific upstream pipeline's terminal table (`TrodesPosV1`, `DLCPosV1`, `IntervalPositionInfo`, etc.). The merge table is essentially a "type-tagged union" of all the ways position can be computed in Spyglass.

## How rows get in there

You don't `populate()` a merge table. You insert into it explicitly using the `_Merge` helper method `insert()` (sometimes called `insert1` in older versions), which takes a key from one of the upstream source tables and atomically:

1. mints a new `merge_id` UUID,
2. inserts a row into the master with `source = "TrodesPosV1"` (or whichever),
3. inserts a row into the corresponding part table referencing the upstream key.

Typical usage:

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import TrodesPosV1

key = (TrodesPosV1 & {"nwb_file_name": "...", "trodes_pos_params_name": "default",
                      "interval_list_name": "pos 0 valid times", "epoch": 1}).fetch1("KEY")

PositionOutput.insert([key], part_name="TrodesPosV1")
# or in newer Spyglass:
PositionOutput.insert1({**key, "source": "TrodesPosV1"})
```

After that, downstream tables (decoders, linearization, ripple detection, etc.) restrict on `PositionOutput` by `merge_id` rather than caring which upstream pipeline produced the position. That's the whole point of the pattern — downstream code is decoupled from "did this come from Trodes or DLC?".

## Useful methods you do get from `_Merge`

Because `populate()` doesn't apply, the merge superclass gives you a different toolkit:

- `PositionOutput.insert(...)` / `insert1(...)` — the way new rows arrive.
- `PositionOutput.merge_view()` — joined view across master + all parts; handy for "what's in here?".
- `PositionOutput.merge_restrict(restriction)` — restrict across all parts at once.
- `PositionOutput.merge_get_part(restriction)` — given a master-side restriction, return the *specific part* (and therefore the upstream table) that row came from.
- `PositionOutput.merge_get_parent(restriction)` — walk one step further up to the actual upstream table row.
- `PositionOutput.fetch_nwb(restriction)` — fetch the NWB-backed analysis output regardless of source.

## Why this design exists

Two reasons that come up constantly in Spyglass:

1. **Multiple equivalent pipelines.** Position can come from raw Trodes online tracking, offline Trodes reprocessing, or DeepLabCut. They produce the same *kind* of thing (animal position over time) and downstream consumers shouldn't fork.
2. **Versioning without breaking downstream.** A new `TrodesPosV2` can be added as a new part table without touching `ClusterlessDecodingV1`, which only knows about `PositionOutput.merge_id`.

You'll see the exact same pattern for `LFPOutput`, `SpikeSortingOutput`, `RippleTimesOutput`, `PositionGroupOutput`, etc. Anything ending in `*Output` in Spyglass is almost certainly a merge table.

## Practical implication for your workflow

If you were trying to "populate `PositionOutput`", what you actually want is:

1. Run `populate()` on the upstream pipeline you care about — e.g. `TrodesPosV1.populate(key)` or the DLC chain.
2. Once the upstream row exists, call `PositionOutput.insert([upstream_key], part_name="TrodesPosV1")` (or the equivalent `insert1` form in your version).
3. Then downstream tables that depend on `PositionOutput` will see the `merge_id` and can be populated normally.

If you want, point me at the downstream table that's complaining about a missing `PositionOutput` entry and I can sketch the exact insert call for your key.
