# Changing `position_bin_size` from 2 cm to 5 cm — what re-runs, what you reuse

## TL;DR

`position_bin_size` is **not** a top-level attribute of `DecodingParameters`. It lives nested inside the `decoding_params` LONGBLOB (specifically inside the `environments=[Environment(place_bin_size=...)]` list that gets pickled into the row). Because `DecodingParameters` is a `dj.Lookup` keyed only by `decoding_param_name`, you cannot "change the bin size in place" without breaking DataJoint's contract that primary keys uniquely identify a row's contents. So the practical answer depends on whether you mutate the existing row or insert a new one — and only the **decoding fits themselves** are sensitive to the bin size. Everything upstream (position, spikes, waveform features) is reusable.

## What the schema actually looks like

`DecodingParameters` (in `spyglass.decoding.v1.core`):

```
decoding_param_name : varchar(80)   # PK — just a name
---
decoding_params     : LONGBLOB      # entire model spec, including environments[i].place_bin_size
decoding_kwargs = NULL : LONGBLOB
```

`position_bin_size` (the value the user sets) is one of the kwargs that ends up inside an `Environment(...)` object inside `decoding_params["environments"]`. It is consumed in `ClusterlessDecodingV1.fetch_environments` / `SortedSpikesDecodingV1.fetch_environments` (`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/v1/clusterless.py:475` and `…/sorted_spikes.py:418`), where the classifier is rebuilt and `initialize_environments(position=…)` is called — that is the step that constructs the place-bin grid.

## Downstream tables that depend on `DecodingParameters`

Direct foreign-key children (grep for `-> DecodingParameters`):

- `ClusterlessDecodingSelection` (`decoding/v1/clusterless.py:83`)
- `ClusterlessDecodingV1` (computed; `…:95`) — produces `results_path` (xarray `.nc`) and `classifier_path` (pickled model)
- `SortedSpikesDecodingSelection` (`decoding/v1/sorted_spikes.py:48`)
- `SortedSpikesDecodingV1` (computed; `…:61`) — same outputs

And further downstream:

- `DecodingOutput` merge table (`decoding/decoding_merge.py`) part-tables `ClusterlessDecodingV1` and `SortedSpikesDecodingV1`. Each merge row is a UUID pointing at one fit, so a new fit will get a new `merge_id`.

## What re-runs and what you reuse

### Has to be re-fit (these depend on the actual numerical bin grid)

1. **`ClusterlessDecodingV1` and/or `SortedSpikesDecodingV1` rows** that reference the affected `decoding_param_name`. The likelihood (place fields / mark intensity functions), the discrete-state initial/transition matrices conditioned on bins, the posterior over position, and the saved `results_path` xarray and `classifier_path` pickle are all functions of the bin grid. None of those numerical outputs are reusable at a different bin size.
2. **Any `DecodingOutput` merge entries** sourced from the rows in (1). These are not "recomputed" — they are inserted at fit time — so deleting and re-inserting the underlying `…DecodingV1` row leaves a stale merge entry unless you delete it via the merge-table API.

### Can be reused as-is (no recompute)

Everything **upstream** of `DecodingParameters` is unaffected because none of those tables join on `decoding_param_name`:

- `IntervalList` (encoding/decoding intervals).
- `PositionGroup` and `PositionOutput` — raw/processed position is **not** binned at this stage; binning happens inside the classifier. So `TrodesPosV1`, `DLCPosV1`, `IntervalLinearizedPosition`, etc. all remain valid.
- `SpikeSortingOutput` / `SortedSpikesGroup` (sorted-spikes path).
- `UnitWaveformFeatures` / `UnitWaveformFeaturesGroup` (clusterless path) — waveform features are per-spike, not per-bin.
- `Session`, `Nwbfile`, the recording-side merge tables.

### Selection rows

`ClusterlessDecodingSelection` / `SortedSpikesDecodingSelection` rows that point at the changed param name don't store any numerical bin-dependent content, just FKs. If you keep the same `decoding_param_name`, the selection rows can stay; only the computed children must be deleted+repopulated. If you create a new `decoding_param_name` for the 5 cm variant (recommended — see below), you'll insert new selection rows.

## How to actually do this — two options

### Option A (recommended): insert a *new* `DecodingParameters` row

Build a copy of the existing model spec with `place_bin_size=5.0` in each `Environment(...)`, give it a new `decoding_param_name` (e.g. `<old_name>_bin5cm`), `insert1` it, then insert new selection rows pointing at the new name and `populate()`. This preserves the 2 cm fits and their merge entries — useful if you want to compare 2 cm vs 5 cm posteriors (which is itself a reasonable sanity check: posterior credible intervals should widen mildly, ~constant peak likelihood per cell).

### Option B: mutate the existing row

If you *replace* the blob under the same `decoding_param_name`, you must first delete every dependent row (because the recorded fits no longer match what the row claims). The cascade is:

1. `(DecodingOutput.ClusterlessDecodingV1 + .SortedSpikesDecodingV1) & key` — drop the merge entries (use the `_Merge` delete helpers, not raw `delete()`, so the master row goes too).
2. `ClusterlessDecodingV1 & key` and/or `SortedSpikesDecodingV1 & key` — delete the computed rows. This also removes the on-disk `results_path` `.nc` and `classifier_path` files via the `filepath@analysis` store; you can also call `DecodingOutput.cleanup()` afterwards to sweep orphan `.nc` files.
3. (Optionally) `ClusterlessDecodingSelection` / `SortedSpikesDecodingSelection` rows if you want to start clean.
4. Update the `DecodingParameters` row, then re-insert selection rows and `populate()`.

Option B loses the 2 cm results. Prefer A.

## Caveats / things to verify

- `DecodingParameters` overrides `insert()` / `fetch1()` to convert the model classes to/from dicts — when constructing the new params, you can pass either the `non_local_detector` classifier instance (e.g. `ContFragClusterlessClassifier(environments=[Environment(place_bin_size=5.0)])`) or the equivalent dict; the table's `insert` will normalize.
- If `decoding_kwargs` carries `environment_labels` for multi-environment decoding, every `Environment` in the list must be updated with the new bin size; otherwise the model will mix bin grids across environments.
- The `place_bin_size` argument in `non_local_detector.Environment` is in the same units as the position columns of `PositionGroup.fetch_position_info` (cm in standard Frank-lab pipelines). Confirm units before assuming "5" means 5 cm.
- Rough cost extrapolation: state-space size scales like `1/bin_size` (1D) or `1/bin_size^2` (2D). Going 2 cm → 5 cm shrinks the bin count by ~2.5x (1D) / ~6.25x (2D); fits should be faster and use less memory, not more, so re-running is cheaper than the original 2 cm fit.

## Files I looked at

- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/v1/core.py` (DecodingParameters definition, lines 24-126; PositionGroup 130+).
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/v1/clusterless.py` (Selection 83, V1 95, fetch_environments 475).
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/v1/sorted_spikes.py` (Selection 48, V1 61, fetch_environments 418).
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/decoding_merge.py` (DecodingOutput merge, part tables).
