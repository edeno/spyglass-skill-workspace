# Upstream tables required for a `DecodingOutput.ClusterlessDecodingV1` row

A `DecodingOutput.ClusterlessDecodingV1` part-table entry points at a
`ClusterlessDecodingV1` master row. To reach that row from raw NWB
you have to walk three converging branches (spike features, position,
parameters), each of which roots back at the common-ingestion tables.

Below is an enumeration grouped by branch, with the foreign-key
parents on each Selection / Computed table called out so you can see
exactly which tables must already be populated.

---

## 1. Common ingestion (root of every branch)

These are the entry points from raw NWB; they have to exist before
anything else can be inserted.

- `Nwbfile` — the raw NWB file registered into Spyglass.
- `Session` — session-level metadata, FK on `Nwbfile`.
- `IntervalList` — named time intervals for the session (used several
  times downstream: recording window, sort window, encoding interval,
  decoding interval).
- `Electrode` — per-channel electrode table (FK on `Session`).
- `Raw` — the raw electrical-series pointer for the session.
- `LabTeam` — team / personnel table referenced by the recording
  selection.

---

## 2. Spike-sorting / waveform-features branch

This is the heaviest branch. Each Selection table has multiple FK
parents that must already be populated.

### 2a. Recording

- `SortGroup` (Manual) and its `SortGroup.SortGroupElectrode` part
  (FK on `Session`, `Electrode`) — defines which channels go into
  which sort group.
- `SpikeSortingPreprocessingParameters` (Lookup) — filtering /
  referencing / whitening params.
- `SpikeSortingRecordingSelection` (Manual) — FK parents are
  `Raw`, `SortGroup`, `IntervalList`, `SpikeSortingPreprocessingParameters`,
  `LabTeam`. **All five must be present.**
- `SpikeSortingRecording` (Computed) — populated from the Selection.

### 2b. Sorting

- `SpikeSorterParameters` (Lookup) — sorter name + params dict.
- `SpikeSortingSelection` (Manual) — FK parents are
  `SpikeSortingRecording`, `SpikeSorterParameters`, `IntervalList`
  (the sort interval, often distinct from the recording interval).
- `SpikeSorting` (Computed) — populated from the Selection.

### 2c. Curation and merge

- `CurationV1` (Manual) — FK on `SpikeSorting`. Holds the curation
  labels / merge groups.
- `SpikeSortingOutput` (Merge) — the master merge table. The
  relevant part for a v1 clusterless flow is
  `SpikeSortingOutput.CurationV1`, whose part-table FK is on
  `CurationV1`.

(Note: `MetricCuration` / `MetricCurationSelection` are an *optional*
side-loop that can feed labels into a downstream `CurationV1` insert,
but `SpikeSortingOutput.CurationV1` only references `CurationV1`
itself. They are not part of the must-have chain to produce a
`ClusterlessDecodingV1` row.)

### 2d. Waveform features (clusterless-specific)

- `WaveformFeaturesParams` (Lookup) — which features (amplitude,
  spatial location, …) to extract.
- `UnitWaveformFeaturesSelection` (Manual) — FK parents are
  `SpikeSortingOutput` (proj to `spikesorting_merge_id`) and
  `WaveformFeaturesParams`.
- `UnitWaveformFeatures` (Computed) — populated from the Selection;
  produces the per-spike feature arrays consumed by the clusterless
  decoder.
- `UnitWaveformFeaturesGroup` (Manual) and its `UnitFeatures` part
  — FK on `Session`; the part has FKs on
  `UnitWaveformFeaturesGroup` and `UnitWaveformFeatures`. This is
  the "bundle of feature streams" that `ClusterlessDecodingSelection`
  actually points at.

---

## 3. Position branch

`ClusterlessDecodingSelection` requires a `PositionGroup`. To get
there from raw NWB you must already have populated *one* of the
position-pipeline outputs that `PositionOutput` (the position merge
table) wraps — typically `TrodesPosV1` (from raw head-position data
in the NWB) or `DLCPosV1` (from a DeepLabCut-tracked video). Then:

- `PositionOutput` — the position merge table (one of its parts:
  `TrodesPosV1`, `DLCPosV1`, or `CommonPos`-style imported).
- `PositionGroup` (Manual) — FK on `Session`.
- `PositionGroup.Position` part — FK on `PositionGroup` and
  `PositionOutput` (projected to `pos_merge_id`); ties one or more
  position streams into a named group.

---

## 4. Decoding-specific tables

- `DecodingParameters` (Lookup) — decoder class name + params
  (state-space model config, transition matrix kind, observation
  model, etc.).
- `ClusterlessDecodingSelection` (Manual) — FK parents are
  `UnitWaveformFeaturesGroup`, `PositionGroup`, `DecodingParameters`,
  and `IntervalList` *twice* (once projected as
  `encoding_interval`, once as `decoding_interval`).
- `ClusterlessDecodingV1` (Computed) — FK on
  `ClusterlessDecodingSelection`; this is the actual master row.
- `DecodingOutput.ClusterlessDecodingV1` — the merge part you started
  from; FK on `ClusterlessDecodingV1`.

---

## Regeneration order from raw NWB

If you are rebuilding from scratch, the topological order is roughly:

1. Insert the NWB file -> `Nwbfile`, which auto-populates
   `Session`, `Electrode`, `Raw`, and the session's `IntervalList`s.
2. Make sure `LabTeam` has the team you'll reference.
3. Define `SortGroup` (+ part) and pick / insert
   `SpikeSortingPreprocessingParameters`.
4. Insert `SpikeSortingRecordingSelection` and populate
   `SpikeSortingRecording`.
5. Pick / insert `SpikeSorterParameters`, insert
   `SpikeSortingSelection`, populate `SpikeSorting`.
6. Insert `CurationV1` (initial curation), then merge-insert into
   `SpikeSortingOutput` via the `CurationV1` part.
7. Pick / insert `WaveformFeaturesParams`, insert
   `UnitWaveformFeaturesSelection`, populate `UnitWaveformFeatures`.
8. Define `UnitWaveformFeaturesGroup` (+ `UnitFeatures` part) bundling
   the relevant `UnitWaveformFeatures` rows.
9. Run the position pipeline of your choice (Trodes or DLC) so
   `PositionOutput` has an entry; define `PositionGroup` (+
   `Position` part) referencing it.
10. Pick / insert `DecodingParameters`.
11. Insert `ClusterlessDecodingSelection` (referencing the feature
    group, position group, decoding params, and the two
    `IntervalList` projections).
12. Populate `ClusterlessDecodingV1`. The `DecodingOutput` merge
    part is inserted as part of that populate step.

---

## Quick reference: full set of must-have upstream tables

Common: `Nwbfile`, `Session`, `IntervalList`, `Electrode`, `Raw`,
`LabTeam`.

Spike-sorting branch: `SortGroup`, `SpikeSortingPreprocessingParameters`,
`SpikeSortingRecordingSelection`, `SpikeSortingRecording`,
`SpikeSorterParameters`, `SpikeSortingSelection`, `SpikeSorting`,
`CurationV1`, `SpikeSortingOutput` (merge, via the `CurationV1` part).

Waveform features: `WaveformFeaturesParams`,
`UnitWaveformFeaturesSelection`, `UnitWaveformFeatures`,
`UnitWaveformFeaturesGroup`.

Position: one of `TrodesPosV1` / `DLCPosV1` / etc. -> `PositionOutput`
-> `PositionGroup`.

Decoding: `DecodingParameters`, `ClusterlessDecodingSelection`,
`ClusterlessDecodingV1`.

`MetricCuration` and `MetricCurationSelection` are deliberately
omitted — they are an optional metric-driven curation side-path
that ultimately produces a `CurationV1` row, but
`SpikeSortingOutput.CurationV1` only requires `CurationV1` itself,
so they are not on the must-have chain for a clusterless decoding
row to exist.
