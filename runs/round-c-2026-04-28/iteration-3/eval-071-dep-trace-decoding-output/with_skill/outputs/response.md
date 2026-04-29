# Upstream dependencies of `DecodingOutput.ClusterlessDecodingV1`

To regenerate a `DecodingOutput.ClusterlessDecodingV1` row from raw NWB, every table in the chain below must already have the corresponding entry. Each `->` is an explicit DataJoint foreign key declared in `definition`. I cite the source declaration so you can verify each link.

The chain has three independent branches that fan into `ClusterlessDecodingSelection`:

1. recording / sorting / waveform-features branch (the spike data)
2. position branch (the behavioral covariate)
3. parameters + intervals (the decoding configuration)

Plus the merge-table layer at the top.

---

## 0. Top of the chain — the merge layer you already know

`DecodingOutput` is a DataJoint merge table; its `ClusterlessDecodingV1` part is just a pointer:

```text
DecodingOutput.ClusterlessDecodingV1
  -> master                 # DecodingOutput (merge_id UUID)
  -> ClusterlessDecodingV1  # the source row
```

Source: `src/spyglass/decoding/decoding_merge.py:26-30`.

So the real question is: what must exist for a `ClusterlessDecodingV1` row to exist?

---

## 1. Raw-data tables (the "from raw NWB" floor)

These are the bottom of every Spyglass branch — every other table eventually descends from them.

| Table | Why it's required | Source |
|---|---|---|
| `Nwbfile` | Holds the raw `.nwb` file path; everything downstream FKs through it via `Session`. | `common/common_nwbfile.py:45-46` |
| `Session` | `-> Nwbfile`. The session row keyed by `nwb_file_name`. Every group/selection table below inherits `nwb_file_name` transitively from here. | `common/common_session.py:19-24` |
| `IntervalList` | `-> Session`. Holds named time intervals. Used in *three* distinct slots downstream (Raw's interval, the recording-selection interval, the sorting-selection interval, and both `encoding_interval` / `decoding_interval` on `ClusterlessDecodingSelection`). | `common/common_interval.py:24-27` |
| `Electrode` (and `ElectrodeGroup`) | Per-channel metadata. Required as the FK target of `SortGroup.SortGroupElectrode`. | `common/common_ephys.py:31-79` |
| `Raw` | `-> Session`, `-> IntervalList`. The `ElectricalSeries` reference; direct FK parent on `SpikeSortingRecordingSelection`. | `common/common_ephys.py:276-280` |
| `LabTeam` | Direct FK parent on `SpikeSortingRecordingSelection`; gates team-based permissions on the recording. | `common/common_lab.py:160-161` |

These are populated by `insert_sessions(...)` + `populate_all_common(...)` from a raw NWB file.

---

## 2. Recording + sorting + curation branch

This is the spike-sorting v1 chain that ends at `SpikeSortingOutput.CurationV1`. **Each Selection table has multiple FK parents — they cannot be collapsed to a single Selection / Computed pair.**

### 2a. Recording

```text
SpikeSortingRecordingSelection
  -> Raw
  -> SortGroup
  -> IntervalList
  -> SpikeSortingPreprocessingParameters
  -> LabTeam
```

Source: `src/spyglass/spikesorting/v1/recording.py:147-156`.

So before you can insert into `SpikeSortingRecordingSelection`, *all five* of those parent rows must exist:

- `SortGroup` (`-> Session`, plus part `SortGroupElectrode -> Electrode`) — `recording.py:34-48`
- `SpikeSortingPreprocessingParameters` (Lookup; `default` is shipped in `contents`) — `recording.py:99-138`
- `LabTeam`, `IntervalList`, `Raw` — see § 1.

Then:

```text
SpikeSortingRecording
  -> SpikeSortingRecordingSelection
```

Source: `recording.py:185-189`.

### 2b. Sorting

```text
SpikeSortingSelection
  -> SpikeSortingRecording
  -> SpikeSorterParameters
  -> IntervalList
```

Source: `src/spyglass/spikesorting/v1/sorting.py:198-206`.

- `SpikeSorterParameters` is a Lookup of per-sorter parameter blobs (`sorting.py:84-...`).
- The `IntervalList` here is *separate* from the one on `SpikeSortingRecordingSelection` — it constrains which time range is sorted within the recording.

Then:

```text
SpikeSorting
  -> SpikeSortingSelection
```

Source: `sorting.py:233-237`.

### 2c. Curation

```text
CurationV1
  -> SpikeSorting
  curation_id=0
  ---
  parent_curation_id=-1
  -> AnalysisNwbfile
  ...
```

Source: `src/spyglass/spikesorting/v1/curation.py:30-41`.

`CurationV1` is `dj.Manual`, populated by the classmethod `CurationV1.insert_curation(sorting_id, ...)` (`curation.py:43-...`). A `curation_id=0` row is the no-edits baseline; nothing else is required to produce one.

> **Important — `MetricCuration` is NOT a must-have on this chain.** `MetricCuration` (`spikesorting/v1/metric_curation.py`) is downstream of its own `MetricCurationSelection` and only feeds *back into* `CurationV1` if a user chooses to insert a metric-driven curation row. The merge-table source map (`spikesorting_merge.py:26-47`) shows `SpikeSortingOutput.CurationV1 -> CurationV1` directly — there is no `-> MetricCuration` link on the must-have chain. So a baseline `CurationV1` row produced from `SpikeSorting` is sufficient; metric curation is optional.

### 2d. Spike-sorting merge layer

```text
SpikeSortingOutput.CurationV1
  -> master              # SpikeSortingOutput (merge_id UUID)
  -> CurationV1
```

Source: `src/spyglass/spikesorting/spikesorting_merge.py:34-47`.

This is what the clusterless waveform-features branch FK's to — not `CurationV1` directly.

### 2e. Clusterless waveform features

```text
UnitWaveformFeaturesSelection
  -> SpikeSortingOutput.proj(spikesorting_merge_id="merge_id")
  -> WaveformFeaturesParams
```

Source: `src/spyglass/decoding/v1/waveform_features.py:103-108`.

- `WaveformFeaturesParams` is a Lookup (`features_param_name`); stock values include `"amplitude"` and `"amplitude, spike_location"` (`waveform_features.py:21-79`).

Then:

```text
UnitWaveformFeatures
  -> UnitWaveformFeaturesSelection
  ---
  -> AnalysisNwbfile
  object_id
```

Source: `waveform_features.py:111-123`.

Finally the group that `ClusterlessDecodingSelection` actually FKs to:

```text
UnitWaveformFeaturesGroup
  -> Session
  waveform_features_group_name

UnitWaveformFeaturesGroup.UnitFeatures (part)
  -> UnitWaveformFeaturesGroup
  -> UnitWaveformFeatures
```

Source: `src/spyglass/decoding/v1/clusterless.py:44-55`.

So the full clusterless waveform-features chain is:

```text
SpikeSortingOutput  +  WaveformFeaturesParams
        \                   /
   UnitWaveformFeaturesSelection
              |
       UnitWaveformFeatures
              |   (one row per (sort, params) pair)
              v
   UnitWaveformFeaturesGroup       <-- ClusterlessDecodingSelection FKs to this
       (+ part UnitFeatures linking each UnitWaveformFeatures row into the group)
```

---

## 3. Position branch

```text
PositionGroup
  -> Session
  position_group_name
  ----
  position_variables = NULL
  upsample_rate = NULL

PositionGroup.Position (part)
  -> PositionGroup
  -> PositionOutput.proj(pos_merge_id='merge_id')
```

Source: `src/spyglass/decoding/v1/core.py:130-143`.

So `PositionGroup` itself depends only on `Session`, but its `.Position` part requires at least one `PositionOutput` merge row. `PositionOutput` is the position-tracking merge master, with parts:

```text
PositionOutput.{DLCPosV1, TrodesPosV1, CommonPos, PoseV2, ImportedPose}
```

Source: `src/spyglass/position/position_merge.py:26-89`.

For "regenerate from raw NWB" you need at least *one* of those source classes populated, depending on which position pipeline you used (`TrodesPosV1` for the LED pipeline, `DLCPosV1` for DeepLabCut, `CommonPos` / `PoseV2` / `ImportedPose` otherwise) — each has its own selection / parameter / interval upstream chain that you'd need to reproduce to land a `PositionOutput` merge row, but at the level of "what must exist for `PositionGroup.Position`", a single populated `PositionOutput` row is the requirement.

---

## 4. Decoding-selection branch (the leaf)

```text
ClusterlessDecodingSelection
  -> UnitWaveformFeaturesGroup
  -> PositionGroup
  -> DecodingParameters
  -> IntervalList.proj(encoding_interval='interval_list_name')
  -> IntervalList.proj(decoding_interval='interval_list_name')
  estimate_decoding_params = 1 : bool
```

Source: `src/spyglass/decoding/v1/clusterless.py:83-91`.

- `DecodingParameters` (Lookup; `decoding/v1/core.py:38-43`) — holds `decoding_params` (model init) and `decoding_kwargs` (runtime kwargs) as sibling top-level blobs. Stock defaults are version-suffixed (e.g. `contfrag_clusterless_{non_local_detector_version}`); they are *not* auto-inserted at module import — you must call `DecodingParameters().insert_default()` (`core.py:68`) once.
- The two `IntervalList.proj(...)` lines re-use the same `IntervalList` table twice (once renamed `encoding_interval`, once renamed `decoding_interval`). Both interval names must exist as rows in `IntervalList` for the same `nwb_file_name`.

Then:

```text
ClusterlessDecodingV1
  -> ClusterlessDecodingSelection
  ---
  results_path  : filepath@analysis
  classifier_path : filepath@analysis
```

Source: `clusterless.py:94-101`. Populated by `ClusterlessDecodingV1.populate(selection_key)`.

And finally:

```text
DecodingOutput.ClusterlessDecodingV1
  -> master  # DecodingOutput
  -> ClusterlessDecodingV1
```

Source: `decoding/decoding_merge.py:19-30`.

---

## Required-tables checklist (grouped by branch)

To regenerate one `DecodingOutput.ClusterlessDecodingV1` row from raw NWB, every entry below must exist:

**Raw / common (§ 1)**
- [ ] `Nwbfile`
- [ ] `Session`
- [ ] `IntervalList` — at minimum the `Raw` interval, the recording-selection interval, the sorting-selection interval, plus the two named intervals used as `encoding_interval` and `decoding_interval`
- [ ] `ElectrodeGroup`, `Electrode`
- [ ] `Raw`
- [ ] `LabTeam`

**Spike-sorting / curation branch (§ 2a-d)**
- [ ] `SortGroup` (and `SortGroup.SortGroupElectrode` part for each electrode)
- [ ] `SpikeSortingPreprocessingParameters`
- [ ] `SpikeSortingRecordingSelection`  (FKs: `Raw`, `SortGroup`, `IntervalList`, `SpikeSortingPreprocessingParameters`, `LabTeam`)
- [ ] `SpikeSortingRecording`
- [ ] `SpikeSorterParameters`
- [ ] `SpikeSortingSelection` (FKs: `SpikeSortingRecording`, `SpikeSorterParameters`, `IntervalList`)
- [ ] `SpikeSorting`
- [ ] `CurationV1`
- [ ] `SpikeSortingOutput` + its `CurationV1` part

**Clusterless waveform-features chain (§ 2e)**
- [ ] `WaveformFeaturesParams`
- [ ] `UnitWaveformFeaturesSelection` (FKs: `SpikeSortingOutput`, `WaveformFeaturesParams`)
- [ ] `UnitWaveformFeatures`
- [ ] `UnitWaveformFeaturesGroup` (+ `UnitFeatures` part rows)

**Position branch (§ 3)**
- [ ] At least one populated `PositionOutput` source (e.g. `TrodesPosV1` or `DLCPosV1` — with its own upstream chain)
- [ ] `PositionOutput` merge row
- [ ] `PositionGroup` (+ `Position` part row pointing to the `PositionOutput.merge_id`)

**Decoding-specific (§ 4)**
- [ ] `DecodingParameters`
- [ ] `IntervalList` rows for both `encoding_interval` and `decoding_interval`
- [ ] `ClusterlessDecodingSelection`
- [ ] `ClusterlessDecodingV1`
- [ ] `DecodingOutput` + `DecodingOutput.ClusterlessDecodingV1` part

**Optional (NOT on the must-have chain)**
- `MetricCuration`, `MetricCurationSelection` — only required if you chose a metric-driven curation; a baseline `CurationV1` row from `SpikeSorting` is sufficient.

---

## Quick verification recipe

If you want to see for a specific `merge_id` exactly which upstream rows it points to, you can chase the FK trail with restrictions:

```python
from spyglass.decoding import DecodingOutput
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection, ClusterlessDecodingV1, UnitWaveformFeaturesGroup,
)
from spyglass.decoding.v1.core import PositionGroup, DecodingParameters
from spyglass.decoding.v1.waveform_features import (
    UnitWaveformFeatures, UnitWaveformFeaturesSelection, WaveformFeaturesParams,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.v1 import (
    CurationV1, SpikeSorting, SpikeSortingSelection,
    SpikeSortingRecording, SpikeSortingRecordingSelection,
    SortGroup, SpikeSortingPreprocessingParameters, SpikeSorterParameters,
)
from spyglass.common import Session, IntervalList, Electrode, Raw, Nwbfile, LabTeam

merge_key = {"merge_id": "<the uuid>"}
# Walk back one hop at a time:
sel = (ClusterlessDecodingSelection
       & (ClusterlessDecodingV1
          & (DecodingOutput.ClusterlessDecodingV1 & merge_key))).fetch1()
# sel now contains nwb_file_name, waveform_features_group_name, position_group_name,
# decoding_param_name, encoding_interval, decoding_interval, estimate_decoding_params.
# Restrict each upstream table by the relevant subset of those keys to confirm rows exist.
```

For a fully programmatic FK-graph walk you can also use the bundled `db_graph.py` against a live DB or `code_graph.py` against the source tree.
