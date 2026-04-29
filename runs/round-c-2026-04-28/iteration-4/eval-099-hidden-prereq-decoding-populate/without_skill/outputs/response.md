# Prerequisites for `ClusterlessDecodingV1.populate(key)`

A `key` containing only `nwb_file_name` is far from sufficient. `ClusterlessDecodingV1` sits at the *top* of a long dependency chain — its primary key is essentially `(merge IDs for spike features + position) + interval + group + decoding params`. Every one of those upstream rows must already exist or `populate` will silently no-op (DataJoint requires the full restriction to match a row in the table's "key source").

Below is a checklist organized by the four upstream branches that feed clusterless decoding: **(A) NWB ingestion, (B) waveform-feature spikes, (C) position, (D) decoding spec**. At the end is the actual decoding selection row you need.

---

## A. NWB ingestion / session metadata

These come from `spyglass.common` and are populated when you first ingest the NWB file.

- [ ] `Nwbfile` has a row for `nwb_file_name` (set by `insert_sessions(...)` or `Nwbfile().insert_from_relative_file_name(...)`).
- [ ] `Session` row exists for that `nwb_file_name` (auto-populated from the NWB file).
- [ ] `IntervalList` rows for the session — at minimum the encoding interval and decoding interval you intend to use (e.g. `"02_r1"`, `"pos 1 valid times"`, etc.). These are auto-inserted from the NWB epochs but you should confirm by name.
- [ ] `LabMember`, `Lab`, `Institution`, `Subject` — usually auto-populated, just sanity-check with `Session & key`.

Quick check:

```python
from spyglass.common import Nwbfile, Session, IntervalList
print(Nwbfile & {"nwb_file_name": nwb_file_name})
print(Session & {"nwb_file_name": nwb_file_name})
print(IntervalList & {"nwb_file_name": nwb_file_name})
```

---

## B. Spike-feature (clusterless) branch

Clusterless decoding doesn't use sorted units — it uses **waveform features** (typically amplitudes / mark vectors) per spike, computed from spike-sorted-but-uncurated detections. The chain is:

`Raw / Electrode → SpikeSortingRecording → SpikeSorting → CurationV1 → SpikeSortingOutput (merge) → UnitWaveformFeatures → UnitWaveformFeaturesGroup`.

Concretely you need:

- [ ] **Sort groups defined**: `SortGroup` populated for `nwb_file_name` (groups tetrodes / probe shanks).
- [ ] **Recording selection + recording**: `SpikeSortingRecordingSelection` row, then `SpikeSortingRecording.populate()` done. This requires picking an interval (`sort_interval_name`) and a preprocessing param set (`preproc_param_name`).
- [ ] **Artifact detection** (if used): `ArtifactDetectionSelection` + `ArtifactDetection` populated, producing an `artifact_removed_interval_list_name`.
- [ ] **Spike sorting**: `SpikeSortingSelection` row (with sorter + sorter params + the artifact-removed interval) and `SpikeSorting.populate()`. For clusterless, sorters like `clusterless_thresholder` (mountainsort4 thresholder) are typical.
- [ ] **Curation**: a `CurationV1` row — for clusterless you usually insert the *uncurated* sort directly via `CurationV1.insert_curation(sorting_id, ...)` so that downstream tables have a curation handle. No manual unit labeling is required.
- [ ] **Merge entry**: `SpikeSortingOutput` merge table has a row pointing at that `CurationV1` entry. `merge_id` here is what feeds the decoder.
- [ ] **Waveform features**: `UnitWaveformFeaturesSelection` + `UnitWaveformFeatures.populate()` — this computes the per-spike marks (amplitudes on each channel of the group) used as the clusterless features.
- [ ] **Feature group**: a `UnitWaveformFeaturesGroup` (sometimes called `WaveformFeaturesGroup` / `UnitWaveformFeaturesGroup`) that bundles the per-tetrode `merge_id`s into a single named group via `.create_group(...)`. The decoder consumes the group, not individual tetrodes.

Quick check:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.decoding.v1.waveform_features import (
    UnitWaveformFeatures, UnitWaveformFeaturesGroup,
)
print(UnitWaveformFeatures & {"nwb_file_name": nwb_file_name})
print(UnitWaveformFeaturesGroup & {"nwb_file_name": nwb_file_name})
```

---

## C. Position branch

The decoder needs a continuous position trace over the encoding interval (this is the "covariate" the decoder learns spike-feature -> position mappings for).

- [ ] **Raw position** ingested (`RawPosition`).
- [ ] A populated position pipeline producing a `PositionOutput` merge row. Either:
  - `TrodesPosV1`: `TrodesPosParams` + `TrodesPosSelection` + `TrodesPosV1.populate()`, or
  - `DLCPosV1`: full DLC chain (`DLCProject` → `DLCModelTraining` → `DLCPoseEstimation` → `DLCSmoothInterp` → `DLCCentroid` / `DLCOrientation` → `DLCPosV1`).
- [ ] The `PositionOutput` merge table has a `merge_id` for that position result. This `merge_id` is what the decoder consumes.
- [ ] **(2D decoding only) Track graph / environment**: a `TrackGraph` row describing the maze topology, used to build the `Environment` that the decoder discretizes onto. Linearization tables (`LinearizationParameters`, `TrackGraph`, `LinearizedPositionV1`) are needed if you're doing 1D decoding on a linearized track.

Quick check:

```python
from spyglass.position import PositionOutput
print(PositionOutput.merge_get_part(restriction={"nwb_file_name": nwb_file_name}))
```

---

## D. Decoding parameters / selection

These are the rows that *don't* depend on the session — they're reusable specs — but the selection row that joins them does.

- [ ] **`DecodingParameters`** row — a named parameter set describing the state-space model (e.g. transition matrix type, environment discretization, observation model: `ClusterlessAlgorithm` such as `ClusterlessGPU` / `ClusterlessKDE`, etc.). Inserted once and reused.
- [ ] **`PositionGroup`** row — a named bundle of `PositionOutput.merge_id`s (often just one) created via `PositionGroup().create_group(...)`. The decoder consumes the group, not a raw merge_id.
- [ ] **`UnitWaveformFeaturesGroup`** row — analogous bundle of spike-feature merge IDs (already covered in §B).
- [ ] **Encoding interval**: an `IntervalList` `interval_list_name` to fit the model on (e.g. a run epoch).
- [ ] **Decoding interval**: an `IntervalList` `interval_list_name` to decode over (often the same run epoch, or a sleep epoch for replay).
- [ ] **`ClusterlessDecodingSelection`** row — this is the row you actually insert. Its primary key combines: `nwb_file_name`, `waveform_features_group_name`, `position_group_name`, `decoding_param_name`, `encoding_interval`, `decoding_interval`, and an `estimate_decoding_params` flag. Once this row exists, `ClusterlessDecodingV1.populate(key)` will fit and decode.

---

## Putting it together

Your final `populate` key needs (at minimum) something like:

```python
key = {
    "nwb_file_name": nwb_file_name,
    "waveform_features_group_name": "tetrodes_run1",
    "position_group_name": "trodes_run1",
    "decoding_param_name": "contfrag_clusterless",
    "encoding_interval": "02_r1",
    "decoding_interval": "02_r1",
    "estimate_decoding_params": False,
}
ClusterlessDecodingV1.populate(key)
```

If you started with only `{"nwb_file_name": ...}`, the practical order to bring a new session online is:

1. `insert_sessions` -> `Nwbfile`, `Session`, `IntervalList`, `RawPosition`.
2. Position pipeline -> `PositionOutput` merge row -> `PositionGroup`.
3. `SortGroup` -> `SpikeSortingRecording` -> (`ArtifactDetection`) -> `SpikeSorting` -> `CurationV1` -> `SpikeSortingOutput` merge -> `UnitWaveformFeatures` -> `UnitWaveformFeaturesGroup`.
4. Insert / pick a `DecodingParameters` row.
5. Insert `ClusterlessDecodingSelection`.
6. `ClusterlessDecodingV1.populate(key)`.

## Common silent-failure modes

- `populate` returns immediately with no work done -> the selection row doesn't exist, or the key over-restricts (typo in a group name).
- "no rows in key source" -> an upstream merge (`PositionOutput` / `SpikeSortingOutput`) has no entry for this session.
- Encoding/decoding interval names don't match anything in `IntervalList` for that `nwb_file_name`.
- `UnitWaveformFeaturesGroup` was created but is empty (no `merge_id`s added) -> decoder fits on zero spikes.
- Position trace and spike features don't overlap in time on the encoding interval -> fit fails or returns NaNs.

(Exact table/column names may differ slightly — `WaveformFeaturesGroup` vs `UnitWaveformFeaturesGroup`, `decoding_param_name` vs `decoding_parameter_name` — between Spyglass versions; check `ClusterlessDecodingSelection.heading` on your install for the authoritative primary key.)
