# Prerequisites for `ClusterlessDecodingV1.populate(key)`

`ClusterlessDecodingV1` sits at the bottom of three converging
sub-pipelines. A `key` containing only `nwb_file_name` is dramatically
under-specified: `ClusterlessDecodingSelection`'s heading carries
`nwb_file_name`, `waveform_features_group_name`, `position_group_name`,
`decoding_param_name`, `encoding_interval`, `decoding_interval`, and
`estimate_decoding_params` (sources: `decoding/v1/clusterless.py:83`,
`decoding/v1/core.py:130`, plus the FK to `DecodingParameters` and to
`IntervalList`). All seven need to resolve to a single row before
`populate()` will do anything; the upstream rows the FKs point to must
already exist.

Below is the checklist, grouped by sub-pipeline. Treat it as
inspect-then-build — at each branch, query the relevant table
restricted by `nwb_file_name` (or the running `key`) before inserting,
so you reuse existing rows instead of duplicating them.

## A. Common ingest (root of every pipeline)

These are prerequisites for *anything* downstream of NWB ingestion;
covered by `02_Insert_Data.ipynb` / `populate_all_common`.

- [ ] **`Session & {"nwb_file_name": nwb_file}`** — session is registered.
  - Verify: `len(Session & {"nwb_file_name": nwb_file}) == 1`.
- [ ] **`IntervalList & {"nwb_file_name": nwb_file}`** — at least the
      intervals you intend to use as `encoding_interval` and
      `decoding_interval`.
  - Verify: `(IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_list_name")`.
  - The two interval names you pass into the selection key must each
    appear here (they can be the same name or different).
- [ ] **`Electrode` / `ElectrodeGroup`** — populated by ingest; needed
      for `SortGroup`.

## B. Spike sorting → waveform features → group

The `waveform_features_group_name` slot in your selection key resolves
to a `UnitWaveformFeaturesGroup` row, which transitively requires the
spike-sorting chain to have run (sources:
`decoding/v1/clusterless.py:83`).

- [ ] **`SortGroup`** rows for this `nwb_file_name` (one sort group per
      shank for clusterless — multi-shank groups fail at
      `SpikeSortingRecording.populate` with
      "contact positions are not unique").
  - Build via `SortGroup().set_group_by_shank(nwb_file_name=nwb_file)`.
- [ ] **`SpikeSortingRecordingSelection` + `SpikeSortingRecording`
      populated.** Use
      `SpikeSortingRecordingSelection.insert_selection({...})` (it
      generates the `recording_id` UUID and is rerun-tolerant —
      normalize its dict-or-list return).
- [ ] **`ArtifactDetectionParameters` row exists** (call
      `ArtifactDetectionParameters().insert_default()` once if not),
      then **`ArtifactDetectionSelection` + `ArtifactDetection`
      populated.** Required if you ever fetch through the merge layer
      with the default `restrict_by_artifact=True`.
- [ ] **`SpikeSorterParameters` row** for your sorter / param name
      (e.g. `"mountainsort4"` / `"franklab_tetrode_hippocampus_30KHz"`,
      or `"clusterless_thresholder"` / `"default_clusterless"` for the
      thresholder path).
- [ ] **`SpikeSortingSelection` + `SpikeSorting` populated.**
- [ ] **`CurationV1`** — at minimum an initial curation anchored to the
      `sorting_id` (no edits is fine). Use
      `CurationV1.insert_curation(sorting_id=..., description="initial")`.
- [ ] **`SpikeSortingOutput.CurationV1`** — publish the curation row
      into the merge table:
      `SpikeSortingOutput.insert((CurationV1 & curation_key).fetch("KEY", as_dict=True), part_name="CurationV1")`.
- [ ] **`WaveformFeaturesParams` row** (defaults: `"amplitude"`,
      `"amplitude, spike_location"`).
- [ ] **`UnitWaveformFeaturesSelection` + `UnitWaveformFeatures`
      populated** — combines a `SpikeSortingOutput` merge_id with a
      `features_param_name`.
- [ ] **`UnitWaveformFeaturesGroup` row** with the
      `waveform_features_group_name` you plan to use, plus its part
      `UnitWaveformFeaturesGroup.UnitFeatures` linking the
      `UnitWaveformFeatures` keys.
  - Build via
    `UnitWaveformFeaturesGroup().create_group(nwb_file_name, group_name, keys)`.
  - Verify: `len(UnitWaveformFeaturesGroup & {"nwb_file_name": nwb_file, "waveform_features_group_name": group_name}) == 1`.

## C. Position → group

The `position_group_name` slot resolves to a `PositionGroup` row whose
part links to `PositionOutput` merge IDs (source:
`decoding/v1/core.py:130`).

- [ ] **One of the position sources is populated and surfaced via
      `PositionOutput`**:
  - Trodes: `TrodesPosParams` → `TrodesPosSelection` →
    `TrodesPosV1.populate` (auto-merges to `PositionOutput.TrodesPosV1`).
  - DLC: full 7-step DLC chain → `DLCPosV1.populate` (auto-merges to
    `PositionOutput.DLCPosV1`).
  - Imported pose: `ImportedPose().insert_from_nwbfile(nwb_file)`, then
    manually `PositionOutput.insert([key], part_name="ImportedPose")`
    (no `_merge_insert`).
  - Verify a merge row exists:
    `PositionOutput.merge_restrict({"nwb_file_name": nwb_file})`.
- [ ] **`PositionGroup` row** with the `position_group_name` you plan to
      use, plus its part linking the `PositionOutput` `merge_id`(s).
  - Build via
    `PositionGroup().create_group(nwb_file_name, group_name, keys, position_variables=[...], upsample_rate=...)`.
  - **Gotcha**: `position_variables` must match the columns of the
    upstream merged DataFrame. Defaults `["position_x", "position_y"]`
    work for `TrodesPosV1` and `DLCPosV1` out-of-the-box; do **not**
    rename them to body-part-prefixed columns (raises `KeyError` in
    `_upsample` or downstream when the make body slices the DataFrame).
  - Confirm column names with
    `list((DLCPosV1 & key).fetch1_dataframe().columns)`.

## D. Decoding parameters

- [ ] **`DecodingParameters` row** with the `decoding_param_name` you
      plan to use.
  - The stock defaults are version-suffixed
    (`decoding/v1/core.py:48`): names like
    `f"contfrag_clusterless_{non_local_detector_version}"`. They are
    **not auto-inserted at module import** — call
    `DecodingParameters().insert_default()` once
    (`decoding/v1/core.py:68`), or query first:
    `(DecodingParameters & 'decoding_param_name LIKE "contfrag_clusterless%"').fetch1("decoding_param_name")`.
  - Don't hard-code a bare `"contfrag_clusterless"`; build the name
    from `from non_local_detector import __version__` so it tracks the
    installed library.

## E. Final selection insert

Once A–D are satisfied, `ClusterlessDecodingSelection.insert1` will
accept this key and `ClusterlessDecodingV1.populate` can run:

```python
from non_local_detector import __version__ as non_local_detector_version

selection_key = {
    "nwb_file_name": nwb_file,
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,   # from IntervalList
    "decoding_interval": decoding_interval_name,   # from IntervalList
    "estimate_decoding_params": 0,                 # explicit; default is 1
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)
```

`estimate_decoding_params` defaults to `1` in the table definition
(`clusterless.py:90`). Set it explicitly: the True branch
(`clusterless.py:289`) runs Baum-Welch parameter estimation; the False
branch (`clusterless.py:333`) does fixed-parameter inference. They are
materially different paths, not just a flag — pick deliberately.

## Quick verification helpers

If you only have `nwb_file_name`, the fastest way to spot what's
missing is to walk the chain restricting by it:

```python
from spyglass.common import Session, IntervalList
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.position import PositionOutput
from spyglass.decoding import (
    PositionGroup, DecodingParameters, ClusterlessDecodingSelection,
)
from spyglass.decoding.v1.waveform_features import UnitWaveformFeaturesSelection
from spyglass.decoding import UnitWaveformFeaturesGroup

f = {"nwb_file_name": nwb_file}
print("Session:                ", len(Session & f))
print("Intervals:              ", len(IntervalList & f))
print("SpikeSortingOutput:     ", len(SpikeSortingOutput.merge_restrict(f)))
print("UnitWaveformFeaturesSel:", len(UnitWaveformFeaturesSelection & f))
print("UnitWaveformFeaturesGrp:", len(UnitWaveformFeaturesGroup & f))
print("PositionOutput:         ", len(PositionOutput.merge_restrict(f)))
print("PositionGroup:          ", len(PositionGroup & f))
print("DecodingParameters:     ", len(DecodingParameters))   # not session-scoped
print("ClusterlessDecodingSel: ", len(ClusterlessDecodingSelection & f))
```

A zero in any row above the selection table is a missing prerequisite;
walk back into the corresponding section (B, C, or D) to populate it.

## Notes / unconfirmed

- Line numbers above (`decoding/v1/clusterless.py:83`,
  `decoding/v1/core.py:130`, etc.) are quoted from the skill's
  reference files; they're against the Spyglass version the skill was
  last validated on. If your installed version is much newer, the
  *names* (tables, attributes, methods) are the load-bearing claims —
  the line numbers may have drifted. Confirm with
  `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`
  and grep there if a number doesn't resolve.
- The checklist assumes the standard Frank-lab clusterless flow
  (mountainsort or `clusterless_thresholder` upstream of
  `UnitWaveformFeatures`). Imported (pre-sorted) spikes flow through
  `SpikeSortingOutput.ImportedSpikeSorting` instead, but the rest of
  the chain (waveform features → group → decoding) is identical.
