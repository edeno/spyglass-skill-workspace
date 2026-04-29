# Workflow position: between curation and clusterless decoding

You finished `SpikeSorting.populate()` + `CurationV1`. Clusterless decoding does NOT consume curated units directly — it consumes per-spike *waveform features* (amplitude, spike location) extracted from the spike-sorting output, grouped, and joined with position + parameters.

Here's the chain you still need to build, from `decoding_pipeline.md` § Clusterless Decoding Flow:

```text
SpikeSortingOutput (merge — your curated sort lands here)
        ↓
UnitWaveformFeaturesSelection            # uses WaveformFeaturesParams (e.g. "amplitude, spike_location")
        ↓
UnitWaveformFeatures (Computed)          # extracts per-spike features
        ↓
UnitWaveformFeaturesGroup (Manual)       # groups feature rows for a session
        ↓
ClusterlessDecodingSelection             # + PositionGroup + DecodingParameters + IntervalList
        ↓
ClusterlessDecodingV1 (Computed)
        ↓
DecodingOutput.ClusterlessDecodingV1     # merge layer for fetch_results / fetch_model
```

## The four things that come between curation and `ClusterlessDecodingV1.populate()`

1. **Get your curated sort into `SpikeSortingOutput`.** `CurationV1` results are exposed to downstream pipelines via the `SpikeSortingOutput` merge table (its `CurationV1` part). Confirm your curation rows are visible there before extracting features.

2. **Extract waveform features.** Pick a `WaveformFeaturesParams` row (defaults are `"amplitude"` and `"amplitude, spike_location"`), insert into `UnitWaveformFeaturesSelection` (keyed on the merge id from `SpikeSortingOutput` plus `features_param_name`), then `UnitWaveformFeatures.populate(...)`.
   ```python
   from spyglass.decoding.v1.waveform_features import (
       UnitWaveformFeaturesSelection, UnitWaveformFeatures, WaveformFeaturesParams,
   )
   ```

3. **Build a `UnitWaveformFeaturesGroup`.** This bundles one or more `UnitWaveformFeatures` entries (typically across tetrodes/probes) into a single grouping that the decoder ingests:
   ```python
   from spyglass.decoding import UnitWaveformFeaturesGroup
   UnitWaveformFeaturesGroup().create_group(
       nwb_file_name=nwb_file,
       group_name=features_group_name,
       keys=[...],   # list of UnitWaveformFeatures keys to include
   )
   ```

4. **Build the parallel "position side" + params + intervals** that `ClusterlessDecodingSelection` also needs. None of these come "for free" from the sort — you assemble them separately:
   - **`PositionGroup`** — created via `PositionGroup().create_group(nwb_file_name, group_name, keys, position_variables, upsample_rate)`. Note: `position_variables` defaults to `["position_x", "position_y"]`, which match both `TrodesPosV1` and `DLCPosV1` column names — don't override with body-part-prefixed names like `"head_position_x"` or you'll hit a `KeyError`.
   - **`DecodingParameters`** — call `DecodingParameters().insert_default()` once if you haven't; the stock clusterless preset is version-suffixed: `f"contfrag_clusterless_{non_local_detector_version}"`. Don't hard-code the bare prefix.
   - **`IntervalList`** rows for `encoding_interval` and `decoding_interval` (the time windows used to fit the encoding model and to decode, respectively).

After those four are in place, you build the `ClusterlessDecodingSelection` row and call `ClusterlessDecodingV1.populate(selection_key)`. Note `nwb_file_name` is required on the selection key — it's inherited transitively through both groups, and omitting it raises FK failures.

## A couple of gotchas worth flagging up front

- **`estimate_decoding_params`** defaults to `1` on the selection table. The `make()` handler has *very different* branches for `1` (Baum-Welch parameter estimation) vs `0` (fixed-parameter inference). Set it explicitly to `0` if you want plain decoding with the params from `DecodingParameters`.
- **Position variable names must match upstream DataFrame columns** — see the `PositionGroup` gotcha above. Verify with `list((DLCPosV1 & key).fetch1_dataframe().columns)` (or `TrodesPosV1`, depending on your tracker) before calling `create_group`.
- For the canonical end-to-end snippet, see `skills/spyglass/references/decoding_pipeline.md` § Canonical Example (Clusterless), and the tutorial notebooks `40_Extracting_Clusterless_Waveform_Features.ipynb` → `41_Decoding_Clusterless.ipynb`.

## Short answer

Curation → **`SpikeSortingOutput` (merge)** → **`UnitWaveformFeaturesSelection` + `UnitWaveformFeatures.populate()`** → **`UnitWaveformFeaturesGroup.create_group(...)`** → (in parallel: **`PositionGroup`**, **`DecodingParameters`**, encoding/decoding `IntervalList` rows) → **`ClusterlessDecodingSelection.insert1(...)`** → **`ClusterlessDecodingV1.populate(...)`** → fetch via **`DecodingOutput`**.
