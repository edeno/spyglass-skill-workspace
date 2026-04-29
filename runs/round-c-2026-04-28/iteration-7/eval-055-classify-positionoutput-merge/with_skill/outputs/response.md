# `PositionOutput` is a **merge table**, not a Computed table

That's why you can't find a `populate()` — merge masters don't have one in the usual sense. Rows arrive via a different mechanism.

## What it is, concretely

`PositionOutput` is one of Spyglass's five **merge masters** (`src/spyglass/position/position_merge.py:24`). It inherits from `_Merge` + `SpyglassMixin`, not from `dj.Computed` or `dj.Manual`. Its job is to unify several upstream position pipelines under a single key space so that downstream tables (ripple detection, decoding, MUA, etc.) can take a foreign key into "position" without caring which source produced it.

The five Spyglass merge masters all share this shape:

| Merge master | Unifies |
|---|---|
| `SpikeSortingOutput` | v0 + v1 sorting |
| `LFPOutput` | `LFPV1`, `ImportedLFP`, ... |
| **`PositionOutput`** | **`TrodesPosV1`, `DLCPosV1`, `CommonPos`, `ImportedPose`** |
| `LinearizedPositionOutput` | linearization outputs |
| `DecodingOutput` | `ClusterlessDecodingV1`, `SortedSpikesDecodingV1` |

## How to recognize a merge master at a glance

- Its **only primary-key column is `merge_id`** (a UUID); secondary attribute is `source` (a string naming the part).
- It has nested **part tables** named after each upstream source — e.g. `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`, `PositionOutput.CommonPos`, `PositionOutput.ImportedPose`.
- No `make()` method, no `populate()` workflow on the master itself.
- Quick programmatic check:

  ```python
  from spyglass.utils.dj_merge_tables import Merge
  isinstance(PositionOutput(), Merge)   # True
  ```

## How rows actually get in

Rows in a merge master are written **as a side effect of populating one of its upstream sources**. The flow is:

1. You populate the upstream Computed table normally — e.g. `TrodesPosV1.populate(key)` or `DLCPosV1.populate(key)`. This is where the real work happens (computing the position trace, smoothing, etc.).
2. The upstream pipeline (or a notebook step right after it) inserts a corresponding row into `PositionOutput` and the matching part table — typically through `PositionOutput.insert1(...)` or the helper `PositionOutput().merge_populate("TrodesPosV1")` (`_Merge.merge_populate(source, keys=None)`), which copies new rows from the named source part into the master + part.
3. The master row gets a freshly minted `merge_id` (UUID); the part-table row carries the upstream's full primary key plus that `merge_id`. The two stay in lockstep.

So if you're seeing populated rows in `PositionOutput` and wondering where they came from: look at which **part** they live in (`source` column), then trace back to that pipeline's populate step. That's the actual computation; the merge insert is bookkeeping that happens alongside it.

If `TrodesPosV1` (or whichever upstream) has rows but `PositionOutput` is empty for that key, the merge insert step was skipped — `merge_get_part(key)` will raise `ValueError: Found 0 potential parts: []` (`src/spyglass/utils/dj_merge_tables.py:634`). The fix is to run the merge insert (often `PositionOutput.insert([{...}], part_name="TrodesPosV1")` or `merge_populate`).

## Working with `PositionOutput` in queries

A few footguns the skill flags specifically for merge masters — relevant the moment you start fetching:

- **Don't restrict the master with upstream fields.** `PositionOutput & {"nwb_file_name": f}` silently returns the *whole* table because `nwb_file_name` isn't on the master's heading. Use `PositionOutput.merge_restrict({"nwb_file_name": f})` or `PositionOutput.merge_get_part({"nwb_file_name": f})`.
- **Canonical fetch pattern:**

  ```python
  merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
  df = (PositionOutput & merge_key).fetch1_dataframe()
  ```

- **Destructive ops are classmethods** — pass the restriction as an argument: `PositionOutput.merge_delete(merge_key)`, **not** `(PositionOutput & merge_key).merge_delete()` (the `& merge_key` gets silently dropped and the call would target the whole table).

## TL;DR

`PositionOutput` has no `populate()` because it's a `_Merge`-derived master, not a `dj.Computed`. Rows land in it via inserts triggered by upstream pipeline populates (`TrodesPosV1`, `DLCPosV1`, `CommonPos`, `ImportedPose`) — either by direct `PositionOutput.insert(...)` calls in the pipeline / notebook or via `PositionOutput().merge_populate("<SourceName>")`. The "real" computation lives in the upstream sources; the merge master just gives downstream tables one stable foreign key target across all of them.
