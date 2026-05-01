# What happens when you swap `trodes_pos_params_name` from `default` to `default_decoding`

Short version: swapping the param name on `TrodesPosSelection` creates a **new primary key** for that selection row, which means a brand new compute fans out through `TrodesPosV1` and the `PositionOutput` merge table. Everything downstream that already pointed at the *old* `merge_id` (`default`) is undisturbed; it does not get re-run, and it does not get re-pointed automatically. New downstream rows only appear where you (or `populate()`) insert new selection-side rows that reference the new `merge_id`.

## The selection key changes, so it is a new entry, not an edit

`TrodesPosSelection` is a manual table whose primary key is

```
-> RawPosition
-> TrodesPosParams      # i.e. trodes_pos_params_name
```

(see `position/v1/position_trodes_position.py:107-116`). So `(nwb_file_name, interval_list_name, trodes_pos_params_name)` is the PK. Going from `"default"` to `"default_decoding"` is not an in-place modification — it is a different row. In practice you should:

1. Make sure a `TrodesPosParams` row with `trodes_pos_params_name = "default_decoding"` already exists (insert it via `TrodesPosParams.insert1({...})` if not).
2. Insert the new `TrodesPosSelection` row (same `RawPosition` key, new param name).
3. Call `TrodesPosV1.populate(...)`.

Old rows (`default`) keep existing alongside the new ones. If you actually want to replace, you have to delete the old chain explicitly — and that delete will cascade through everything downstream that referenced the old `merge_id`, which is usually *not* what you want.

## The cascade on populate

Here is what gets recomputed (new rows) the moment you `populate()` after inserting the new selection:

### 1. `TrodesPosV1` — recomputed (new row)

`make()` reads `TrodesPosParams & key` and runs `calculate_position_info(...)` with those params (`position_trodes_position.py:192-243`). New params → new smoothing / upsampling / max-speed / LED-front behavior → a new analysis NWB file with new `position_object_id`, `orientation_object_id`, `velocity_object_id`. The numerical values of position, head direction, velocity, and speed will differ from the `default` row.

### 2. `PositionOutput` (merge table) — new merge row

The last step of `TrodesPosV1.make()` is:

```python
PositionOutput._merge_insert([orig_key], part_name=self.camel_name, skip_duplicates=True)
```

(`position_trodes_position.py:238-243`). That mints a fresh `merge_id` (UUID) in `PositionOutput` and a corresponding part-table row in `PositionOutput.TrodesPosV1`. The old `default` merge row stays exactly where it is — the swap creates a sibling, not a replacement.

### 3. `TrodesPosVideo` — new row if you populate it

`TrodesPosVideo` is `dj.Computed` keyed directly off `TrodesPosV1` (`position_trodes_position.py:291-303`). If you populate it for the new key, you get a new overlay video file (the filename includes the `trodes_pos_params_name`, see line ~373). If you don't populate it, nothing happens here. The old video for `default` is untouched.

### 4. Downstream of `PositionOutput` — only if you re-bind to the new `merge_id`

Everything below `PositionOutput` keys off `merge_id`, **not** off `trodes_pos_params_name`. So none of these tables auto-discover the new params. You have to insert new selection-side rows pointing at the new `merge_id` before `populate()` will compute anything new. Concretely:

- **`LinearizationSelection` → `LinearizedPositionV1` → `LinearizedPositionOutput`** (`linearization/v1/main.py:100-186`). `LinearizationSelection` is a `dj.Lookup` with `-> PositionOutput.proj(pos_merge_id='merge_id')` plus `TrackGraph` and `LinearizationParameters`. New row only if you insert it. If you do, `LinearizedPositionV1.populate()` produces a new linearized analysis NWB, and `LinearizedPositionOutput` gets a new merge row.

- **`PositionGroup.Position` → `ClusterlessDecodingV1` / `SortedSpikesDecodingV1`** (`decoding/v1/core.py:130-143`). `PositionGroup` is `dj.Manual` and its `Position` part references `PositionOutput.proj(pos_merge_id='merge_id')`. The decoding tables resolve position via `pos_merge_id`. If you want to decode against the new params, you need a new `PositionGroup` (or add the new `pos_merge_id` to an existing group) and a new `DecodingSelection` referencing that group. Then populate produces new decoding output. Existing decoders bound to the old `merge_id` are unchanged and still valid.

- **`RippleTimesV1`** (`ripple/v1/ripple.py:181-190`). PK includes `-> PositionOutput.proj(pos_merge_id='merge_id')`. Ripple times depend on position only via the speed used for the speed-threshold gate. If you want ripples computed against the new speed trace, insert a new `RippleTimesV1` selection row with the new `pos_merge_id`. Otherwise existing ripple rows stay tied to the old `merge_id`.

- **`MuaEventsV1`** (`mua/v1/mua.py:60-150`). Same story: keyed on `pos_merge_id`, used for a speed-threshold gate. New row only if you insert one.

- **`MoseqPoseGroup` / Behavior tables** (`behavior/v1/core.py`, `behavior/v1/moseq.py`). Reference `PositionOutput.proj(pose_merge_id='merge_id')`. These are pose-driven (DLC), so a TrodesPos param change is not the typical trigger here; but mechanically they too only react if you insert new group members pointing at the new merge_id.

## What does *not* recompute

- `RawPosition` and the upstream NWB ingestion — params live downstream of raw, so nothing about ingestion changes.
- The old `TrodesPosV1` row keyed on `default`, the old `PositionOutput` row, and every downstream child of that old `merge_id` (linearized, decoders, ripple, MUA, etc.) — all unaffected. They are still completely valid; the new params just spawn a parallel chain.
- Spike sorting, LFP, LFPBand, theta, intervals — none of these depend on `TrodesPosV1`, so they are completely orthogonal.

## Sanity checks before you populate

A few things worth confirming so you don't get surprised:

- Inspect the diff between the two param dicts: `(TrodesPosParams & {"trodes_pos_params_name": "default_decoding"}).fetch1("params")` vs the `default` set defined in `TrodesPosParams.default_params` (`position_trodes_position.py:65-78`). Common things `default_decoding` typically changes: `is_upsampled=1` and `upsampling_sampling_rate` set (e.g. 500 Hz), tighter or looser smoothing, possibly `led1_is_front`. Note `fetch1_dataframe` warns and drops `video_frame_ind` when `is_upsampled=1` (`position_trodes_position.py:255-272`), and `TrodesPosVideo` refuses to render when the source is upsampled (lines 357-363).
- If `default_decoding` upsamples, downstream consumers that also upsample (`PositionGroup` has its own `upsample_rate`) will be re-doing or compounding the work — make sure you understand where the resampling actually happens before you commit.
- Plot the new vs old position/speed traces on a small interval before you point any decoders at the new `merge_id`. Cheap insurance.

## TL;DR cascade map

```
TrodesPosSelection (new row, new param name)
  -> TrodesPosV1                              [NEW]   recompute
       -> AnalysisNwbfile                     [NEW]
       -> TrodesPosVideo (if populated)       [NEW]
       -> PositionOutput (merge_id = NEW)     [NEW]
            ~ LinearizationSelection -> LinearizedPositionV1 -> LinearizedPositionOutput   [only if you insert new selection rows pointing at NEW merge_id]
            ~ PositionGroup -> Clusterless/SortedSpikesDecoding                            [only if you insert new selection rows]
            ~ RippleTimesV1                                                                [only if you insert new selection rows]
            ~ MuaEventsV1                                                                  [only if you insert new selection rows]
            ~ Moseq / behavior tables (pose-based; usually N/A for trodes)                 [only if you insert new selection rows]
```

Old chain (rooted at the `default` `merge_id`) is untouched throughout.
