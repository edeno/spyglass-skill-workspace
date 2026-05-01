# Cascade from a `trodes_pos_params_name` swap on `TrodesPosSelection`

Short version: changing the name on a `TrodesPosSelection` row from `default` to `default_decoding` is a *new* selection key, not an in-place edit. None of the existing rows under `default` get touched. The "what gets recomputed" is everything you re-insert and re-populate by hand under the new name; everything else stays exactly where it was.

The skill's parameter-swap cascade template has four slots — new row(s), downstream branches that must be re-selected and re-populated, sibling/upstream branches that are NOT affected, and a verification step. Walking each:

## How the swap actually lands in the DB

The PK of `TrodesPosSelection` is `(nwb_file_name, interval_list_name, trodes_pos_params_name)` (`position/v1/position_trodes_position.py`, also documented in `position_trodes_v1_pipeline.md`). So:

- `default` → `default_decoding` is **a different primary key**, not a mutation of the same row. If you actually `update1` the name field, you're shifting the row to a new PK and orphaning provenance. The clean shape is `insert1` of a new selection row with `trodes_pos_params_name="default_decoding"`, leaving the `default` row untouched.
- That assumes `TrodesPosParams` already has a row called `default_decoding`. If not, insert it first — build the params dict by merging your overrides into `TrodesPosParams().default_params` (don't construct from scratch, you'll miss required keys) and `insert1` under the new name.

## Slot 1 — The new rows you create

Re-populating against the new selection mints fresh rows, alongside (not replacing) the old ones:

1. **`TrodesPosParams`**: 1 new row (`trodes_pos_params_name="default_decoding"`) — only if it doesn't already exist.
2. **`TrodesPosSelection`**: 1 new row at `(nwb_file_name, interval_list_name, "default_decoding")`. The old `default` selection row stays.
3. **`TrodesPosV1`**: 1 new row, same PK, computed against the new params blob. `make()` writes a fresh `AnalysisNwbfile` and inserts the row.
4. **`PositionOutput.TrodesPosV1` + `PositionOutput`**: 1 new merge entry with a brand-new UUID `merge_id`. This is the load-bearing fact for downstream cascade — `TrodesPosV1.make()` calls `PositionOutput._merge_insert([orig_key], part_name=self.camel_name, skip_duplicates=True)` at `position/v1/position_trodes_position.py:241`, and `_merge_insert` mints a UUID. So the new run has a *different* `merge_id` than the `default` run, even for the same session/interval.

The `default` merge entry — old `merge_id`, old downstream rows — is unaffected.

## Slot 2 — Downstream branches that must be re-selected and re-populated under the new merge_id

These are the tables that FK to `PositionOutput.proj(pos_merge_id='merge_id')` (verified by grepping the source for `PositionOutput.proj(pos_merge_id` and `pos_merge_id` references in selection definitions):

| Pipeline | Selection table to insert | Computed table to populate | Auto-merges? |
| --- | --- | --- | --- |
| Linearization v1 | `LinearizationSelection` (PK includes `pos_merge_id`, `track_graph_name`, `linearization_param_name`) — `linearization/v1/main.py:103` | `LinearizedPositionV1.populate(key)` | Yes — `make()` calls `LinearizedPositionOutput._merge_insert(...)` (`linearization/v1/main.py:184`), so a new `LinearizedPositionOutput` `merge_id` is minted. |
| Ripple detection v1 | `RippleTimesV1` itself takes `pos_merge_id` in its PK (`ripple/v1/ripple.py:186`: `-> PositionOutput.proj(pos_merge_id='merge_id')`); the upstream `RippleLFPSelection` does NOT depend on position, so you do not re-select LFP/electrodes. | `RippleTimesV1.populate(key)` with a fully-scoped key including the new `pos_merge_id` and your existing `RippleLFPSelection` + `RippleParameters` keys. | No merge layer for ripple times. |
| MUA detection v1 | `MuaEventsV1` has `-> PositionOutput.proj(pos_merge_id='merge_id')` in its definition (`mua/v1/mua.py:67`); you may need a new `MuaEventsParameters` selection row that ties together the MUA params + the new `pos_merge_id` (check the actual selection-table shape in your install). | `MuaEventsV1.populate(key)` | Verify per pipeline. |
| Decoding v1 (sorted + clusterless) | `DecodingParameters` rows are independent. The `pos_merge_id` is consumed by the part table `<Decoding>SelectionV1.Position` — `-> PositionOutput.proj(pos_merge_id='merge_id')` at `decoding/v1/core.py:142`. So you insert into the `*SelectionV1` master AND its `.Position` part with the new `pos_merge_id`. | `ClusterlessDecodingV1.populate(key)` and/or `SortedSpikesDecodingV1.populate(key)` | New entries appear in `DecodingOutput`. |

If you don't actually run all of these — say you only swapped params because you care about decoding — only the decoding selection + populate has to happen. The other downstream pipelines stay on the `default` merge_id until you separately re-select.

A note on naming: `default_decoding` strongly suggests this swap is for the decoding pipeline. The smoothing settings used for decoding are typically tighter / no-upsample compared to the more general `default`. That doesn't change the cascade mechanics, but it does mean ripple / MUA may not need re-running unless you specifically want them on the same position trace as decoding.

## Slot 3 — Branches that stay exactly as they are (and what you should reuse)

Unless you go change them yourself, none of this is invalidated:

- **All upstream of position**: `Session`, `Nwbfile`, `IntervalList`, `RawPosition`, `VideoFile` — completely untouched. The new `TrodesPosV1` row reads the same `RawPosition` and the same interval.
- **The `default` branch end-to-end**: the `default` `TrodesPosSelection` row, the `default` `TrodesPosV1` row, the `default` `PositionOutput.TrodesPosV1` part row and its old `merge_id`, and every downstream row under that old `merge_id` (existing `LinearizedPositionV1`, `RippleTimesV1`, decoding entries, etc.) all stay. Anything you have already published / cited against the old `merge_id` is stable.
- **LFP / LFPBand**: not on the position branch at all. `LFPV1`, `LFPBandV1`, `LFPOutput`, `LFPBandSelection` are unaffected.
- **Spike sorting**: `SpikeSortingRecording`, `SpikeSorting`/`SpikeSortingV1`, `CurationV1`, `SpikeSortingOutput`, `SortedSpikesGroup`, `UnitWaveformFeatures` — entirely upstream/orthogonal to position. No re-sorting.
- **Decoding artifacts that are position-independent**: `PositionGroup`, `UnitWaveformFeaturesGroup`, `DecodingParameters` rows themselves don't change. You're inserting *new* `*SelectionV1` rows that *reference* the new `pos_merge_id` while reusing the same parameter / unit / waveform rows.
- **DLC pipeline**: separate source feeding the same merge table. Not invalidated.
- **The old `merge_id` is still queryable**: `(PositionOutput & {"merge_id": old_merge_id}).fetch1_dataframe()` still works after the swap. Old downstream rows still resolve.

## Slot 4 — How to verify the cascade scope before you commit

Two equally valid ways:

**From a Python session (live DB or just the imports):**

```python
from spyglass.position.v1 import TrodesPosV1
for tbl in TrodesPosV1().descendants(as_objects=True):
    print(tbl.full_table_name)
```

`descendants()` walks the FK graph; the union of names you get back is the maximal cascade scope. Anything not in that list is guaranteed not to need recomputation.

**From the bundled scripts:**

```bash
# Source-only (no DB connection needed):
python skills/spyglass/scripts/code_graph.py path --down TrodesPosV1
python skills/spyglass/scripts/code_graph.py path --down PositionOutput

# Live DB topology + row counts:
python skills/spyglass/scripts/db_graph.py path --down PositionOutput
```

Cross-check the union against the slot-2 list above; anything new in your install (custom analyses you've added) shows up there.

## Practical recipe

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import (
    TrodesPosParams, TrodesPosSelection, TrodesPosV1,
)

nwb_file = "<your file>"
interval = "pos 1 valid times"

# 1. Make sure the new params row exists.
defaults = TrodesPosParams().default_params
custom = {**defaults, "speed_smoothing_std_dev": 0.100}  # whatever you actually want
TrodesPosParams.insert1(
    {"trodes_pos_params_name": "default_decoding", "params": custom},
    skip_duplicates=True,
)

# 2. New selection row (NOT an update on the old one).
new_key = {
    "nwb_file_name": nwb_file,
    "interval_list_name": interval,
    "trodes_pos_params_name": "default_decoding",
}
TrodesPosSelection.insert1(new_key, skip_duplicates=True)

# 3. Populate -> writes TrodesPosV1 row + a NEW PositionOutput merge_id.
TrodesPosV1.populate(new_key)

# 4. Grab the new merge_id explicitly. The old default row's merge_id still exists.
new_pos_merge_id = (
    PositionOutput.merge_get_part(new_key).fetch1("merge_id")
)
print("new pos_merge_id:", new_pos_merge_id)

# 5. From here, re-select + re-populate ONLY the downstream pipelines you
#    actually want under the new params. Each one takes pos_merge_id in
#    its PK; reuse your existing non-position keys.
```

A couple of anti-patterns to avoid:

- Do **not** `update1` the `trodes_pos_params_name` field on the existing `TrodesPosSelection` row. That mutates the PK in place and silently breaks provenance for all the existing downstream rows that resolve through the old `merge_id`.
- Do **not** delete the `default` rows "to clean up" before the new pipeline is running. The `default` `merge_id` is a stable identifier — anything you've already shared, exported, or cached uses it. Run the new pipeline alongside, and only consider deletion after you're confident downstream consumers have moved over (and that goes through the inspect-before-destroy workflow, not a quick `.delete()`).
- Do **not** call `.populate()` on a downstream table with a partial restriction like `{"trodes_pos_params_name": "default_decoding"}`. That field doesn't exist on the downstream PK; downstream tables only see `pos_merge_id`. Build the populate key with the actual `pos_merge_id` from step 4.
