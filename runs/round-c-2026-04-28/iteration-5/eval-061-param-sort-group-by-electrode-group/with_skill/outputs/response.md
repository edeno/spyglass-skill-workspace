# `SortGroup().set_group_by_electrode_group(...)` — what it does, and why it breaks clusterless decoding on multi-shank probes

## Short answer

`set_group_by_electrode_group` is a **v0-only** method. It does not exist on the v1 `SortGroup` class — `spyglass.spikesorting.v1.SortGroup` declares only `set_group_by_shank` (`src/spyglass/spikesorting/v1/recording.py:50-95`). If you call it on a v1 `SortGroup` instance you'll get `AttributeError`. If you're explicitly running it on `spyglass.spikesorting.v0.spikesorting_recording.SortGroup` it does run, but it makes one sort group per **electrode group** (i.e. per probe / per device), which is the wrong granularity for v1 clusterless decoding (and breaks even the v1 spike-sorting recording stage) on multi-shank probes.

## What "sort group" means, and what `set_group_by_electrode_group` actually does

A `SortGroup` row in Spyglass defines the set of channels that get spike-sorted together. The PK is `(nwb_file_name, sort_group_id)` and the `SortGroup.SortGroupElectrode` part table lists which `electrode_id`s are in each group. Downstream — `SpikeSortingRecording`, `SpikeSorting`, `UnitWaveformFeatures` — populate per `sort_group_id`, so the sort-group definition controls the channel-bundle granularity for the entire pipeline.

The key distinction is what is grouped together:

- **`set_group_by_shank` (v1, `src/spyglass/spikesorting/v1/recording.py:50-95` → `spyglass.spikesorting.utils.get_group_by_shank`, `utils.py:13-120`)**: walks every NWB electrode, splits each `electrode_group_name` *and* each unique `probe_shank` into its own `sort_group_id`. A 4-shank probe in one electrode group becomes **4 sort groups**. Single-shank devices (tetrodes) are one group apiece.
- **`set_group_by_electrode_group` (v0 only, `src/spyglass/spikesorting/v0/spikesorting_recording.py:94-139`)**: walks `np.unique(electrodes["electrode_group_name"])` and inserts **one sort group per electrode group** — `for e_group in e_groups: ... self.insert1(sg_key)` with no inner shank loop. A 4-shank probe registered as a single electrode group becomes **1 sort group containing all 4 shanks' channels**. The method also deletes existing groups for the session before re-inserting (`(SortGroup & {"nwb_file_name": nwb_file_name}).delete()` at line 104), which cascades to any downstream rows on those groups.

So a v0 sort group = "one electrode group's channels"; a v1 sort group = "one shank's channels". For tetrodes the two are equivalent (one shank per electrode group). For polymer / silicon probes with more than one shank per device they are very different.

## Why this conflicts with v1 clusterless decoding (and v1 spike sorting) on multi-shank probes

There are two distinct conflicts on a multi-shank probe.

### 1. The method doesn't exist on v1's `SortGroup`

The v1 clusterless workflow runs through `spyglass.spikesorting.v1` (`SortGroup`, `SpikeSortingRecording`, `SpikeSorting`, `CurationV1`, then `SpikeSortingOutput.CurationV1`, then `UnitWaveformFeatures` → `UnitWaveformFeaturesGroup` → `ClusterlessDecodingV1`). The v1 `SortGroup` class only exposes `set_group_by_shank` as a classmethod. There is no `set_group_by_electrode_group`. So the literal call in the question — assuming the `SortGroup` symbol comes from `spyglass.spikesorting.v1` (the only version supported for new clusterless work) — raises `AttributeError`. To reproduce the v0 behavior on v1 you'd have to hand-build sort-group rows that bundle multiple shanks together, which leads to the second conflict.

### 2. SpikeInterface rejects multi-shank sort groups: "contact positions are not unique"

Even if you imported v0's helper or hand-rolled equivalent rows on v1's `SortGroup`, putting a multi-shank probe's channels into a single sort group breaks v1's `SpikeSortingRecording.populate`:

> Clusterless sorting requires one sort group per shank. Sort groups spanning multiple shanks produce duplicate `(x, y)` contact positions, which SpikeInterface rejects at `SpikeSortingRecording.populate` with `ValueError: contact positions are not unique`.

The mechanism: SpikeInterface attaches a probe geometry to the recording from the per-electrode `(rel_x, rel_y)` coordinates in `Probe.Electrode`. Across shanks of the same device the relative coordinates are typically defined per-shank, so two channels from different shanks can share the same `(x, y)` pair. SpikeInterface requires each channel to have a unique 2D contact position; when a sort group bundles two shanks together, the duplicate `(x, y)` rows trip the validation and the populate fails.

This is why the v1 pipeline made the design choice to split by shank by default, and why the v1 `SortGroup` simply doesn't carry the v0 grouper forward — the v0 shape is incompatible with the SpikeInterface-backed waveform/feature extraction that clusterless decoding depends on (`UnitWaveformFeatures` consumes the `SpikeSorting` outputs that share the same per-shank geometry).

### 3. Even if it "worked," it would mix shank coordinates into clusterless waveform features

Clusterless decoding decodes from per-spike waveform features (typically `amplitude` plus `spike_location`) extracted in the geometry of one sort group. If a sort group spanned multiple shanks, `spike_location` coordinates would not be on a single physical surface — features from shank A and shank B would land in the same coordinate system without a meaningful mapping, contaminating the `UnitWaveformFeaturesGroup` that feeds `ClusterlessDecodingV1`. Per-shank grouping keeps the feature space coherent for each contributing channel set.

## What to do instead

For a v1 clusterless (or sorted-spikes) workflow on any probe — tetrode or multi-shank — use the v1 grouper:

```python
from spyglass.spikesorting.v1 import SortGroup
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)
```

Inspect the result to confirm one shank per group before populating downstream:

```python
(SortGroup.SortGroupElectrode & {"nwb_file_name": nwb_file})
# — verify each sort_group_id contains exactly one shank.
```

If rows from more than one shank appear under any `sort_group_id`, regroup before inserting `SpikeSortingRecordingSelection`. Note that `set_group_by_shank` deletes existing `SortGroup` rows for the session before re-inserting (it cascades to any downstream selections / sortings on those groups) — re-running it after you've already populated downstream tables for this session will tear those rows out, so use it deliberately.

## Bottom line

`set_group_by_electrode_group` is a v0 helper that defines one sort group per probe/device; the v1 pipeline replaced it with `set_group_by_shank`, which defines one sort group per shank. On a multi-shank probe the v0 shape (a) doesn't exist on the v1 `SortGroup` class, (b) would create duplicate `(x, y)` contact positions that SpikeInterface rejects in `SpikeSortingRecording.populate`, and (c) would mix shank-local feature coordinates that clusterless decoding can't interpret coherently. Use `set_group_by_shank` for v1 spike sorting and clusterless decoding.

### Sources

- v1 `SortGroup` (only `set_group_by_shank` exposed): `src/spyglass/spikesorting/v1/recording.py:33-95`
- v0 `set_group_by_electrode_group` (one group per electrode group): `src/spyglass/spikesorting/v0/spikesorting_recording.py:94-139`
- Per-shank splitting logic: `spyglass.spikesorting.utils.get_group_by_shank`, `src/spyglass/spikesorting/utils.py:13-120`
- "contact positions are not unique" + "Clusterless sorting requires one sort group per shank": skill reference `references/spikesorting_v1_pipeline.md` (Step 1: Recording Preprocessing).
- Clusterless flow that consumes the per-shank sort groups: `references/decoding_pipeline.md` (Clusterless Decoding Flow).
