# What `SortGroup().set_group_by_electrode_group(nwb_file_name=...)` does, and why it conflicts with multi-shank probes

## What the call actually does

`SortGroup` lives in `spyglass.spikesorting.spikesorting_recording` (v0 pipeline) and is mirrored in the v1 pipeline (`spyglass.spikesorting.v1.recording.SortGroup`). It is the table that defines **groups of electrodes that get sorted together**: every downstream spike-sorting recording, sorting, and curation entry is keyed on a `(nwb_file_name, sort_group_id)` pair. A `sort_group_id` is the unit of work for the sorter — one sort group → one recording extractor → one sort → one set of units.

`set_group_by_electrode_group(nwb_file_name=nwb_file)` is a convenience helper on `SortGroup` that auto-populates `SortGroup` and its part table `SortGroup.SortGroupElectrode` from the NWB file's `electrode_groups`. Concretely:

1. It looks up the rows of `Electrode` for that `nwb_file_name`.
2. It groups them by `electrode_group_name` — i.e. the `ElectrodeGroup` they belong to inside the NWB file (which in turn comes from the probe / shank structure declared at ingestion time).
3. For each unique `electrode_group_name`, it inserts one row into `SortGroup` with `sort_group_id` set to that group name (cast to int) and `sort_reference_electrode_id` defaulted (typically -1 = no common reference, or set to the group's reference electrode from the NWB metadata).
4. For every electrode in that group, it inserts a row into `SortGroup.SortGroupElectrode` linking that electrode_id to the new `sort_group_id`.

So the **definition of a sort group it produces is: "one NWB ElectrodeGroup = one sort group"**. All channels that share an `electrode_group_name` will be bundled into one recording and sorted together as a single unit.

There are two sibling helpers on the same table that produce *different* groupings:

- `set_group_by_shank(nwb_file_name=...)` — groups by `(electrode_group_name, probe_shank)`, i.e. one sort group per shank rather than per probe.
- Manual insertion — you can also build `SortGroup` rows by hand, e.g. one channel per group (single-channel sorting), or arbitrary user-defined bundles.

These three modes (per-electrode-group, per-shank, manual) all populate the same `SortGroup` table; the choice just determines how channels are bundled.

## Why it goes wrong on a multi-shank probe

The NWB-side `ElectrodeGroup` is generally **one entry per probe**, not one per shank. So on a 4-shank silicon probe:

- The NWB file has a single `ElectrodeGroup` (e.g. `"0"`) covering all 4 shanks.
- `set_group_by_electrode_group()` therefore creates **one** `SortGroup` containing **all** channels across **all 4 shanks**.

That's a problem for both spike sorting and clusterless decoding:

### Spike sorting

Modern density sorters (MountainSort4/5, Kilosort, IronClust, SpyKING CIRCUS) need accurate channel geometry to do their template matching / drift correction / channel-neighborhood logic. A unit's waveform is expected to appear on a **local** cluster of nearby channels, not on channels separated by a shank gap (often hundreds of microns to a millimeter). When you hand the sorter all 4 shanks as one recording:

- The geometry the sorter sees is a single 2-D layout that includes large empty horizontal gaps between shanks; channel-neighbor radii get badly miscalibrated.
- You can get spurious "units" that appear to have energy across multiple shanks, which is physically impossible — a real spike does not bridge a 250 µm shank gap.
- Some sorters silently degrade (Kilosort's drift correction in particular is not designed for disjoint shanks in one batch); others outright error on geometry.
- Even when it runs, runtime and memory blow up because the sorter is doing an N-channel problem instead of four (N/4)-channel problems that could be parallelized.

The correct unit-of-work for spike sorting on a multi-shank probe is **one shank per sort group** — that's exactly what `set_group_by_shank()` exists to do.

### Clusterless decoding

Clusterless decoding (`spyglass.decoding.v1.clusterless.UnitWaveformFeatures` → `ClusterlessDecodingV1`) takes spike *events* (threshold crossings) and their *waveform features* (amplitudes/marks) per sort group, then builds a generative model of "given a spike with these features on this group, where was the animal". The sort group is the spatial unit the decoder treats as one "tetrode-like" channel cluster:

- It assumes all channels in a sort group are co-localized — features are pooled into a single multivariate mark vector for that group.
- If your sort group spans 4 shanks, you've collapsed 4 spatially distinct populations of neurons into a single "virtual tetrode". The decoder can no longer use shank identity as information; spikes from shank 0 and shank 3 (which may sample completely different cells in different parts of the structure) get pooled into one feature distribution.
- This both reduces the effective dimensionality of the decoding problem (you lose the per-shank place-field tiling) and produces meaningless mark distributions because waveform amplitudes from a spike on shank 0 will be ~0 on shanks 1–3, biasing the per-group amplitude statistics in ways that don't reflect any single neuron's behavior.
- Threshold-crossing detection is also affected: most clusterless pipelines detect on the per-group max-amplitude trace, and that max will be dominated by whichever shank is closest to a firing cell, with no way to recover where on the probe that was.

So for clusterless decoding the same fix applies: groups must be **per shank** (or finer — some workflows split each shank into smaller bundles of nearby channels), not per probe.

## What to do instead

For a multi-shank probe, replace

```python
SortGroup().set_group_by_electrode_group(nwb_file_name=nwb_file)
```

with

```python
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)
```

This requires that the NWB ingestion populated shank information correctly (the `Electrode` table needs a usable `probe_shank` / shank-index column, which is set when the probe is registered through the Frank-lab probe insertion path — `ndx-franklab-novela` `Probe`/`Shank` objects, or Spyglass `Probe`/`ProbeShank`/`ProbeElectrode` entries before NWB ingest). If that information is missing, you have to either re-ingest with proper probe metadata or insert `SortGroup` rows manually, one per shank, listing the relevant electrode_ids.

Quick sanity check before sorting / decoding:

```python
(SortGroup.SortGroupElectrode & {"nwb_file_name": nwb_file}).fetch(
    "sort_group_id", "electrode_id", as_dict=True
)
```

You should see one `sort_group_id` per shank, with channel counts matching the per-shank channel count of your probe (e.g. 32 channels × 4 shanks → 4 sort groups of 32 electrodes each), not a single sort group with 128 electrodes.

## TL;DR

`set_group_by_electrode_group` makes one sort group per NWB `ElectrodeGroup`. Because NWB conventionally uses one `ElectrodeGroup` per probe, on a multi-shank probe this lumps every shank into a single sort group. That's wrong for spike sorting (geometry / neighbor radius / drift assumptions break) and for clusterless decoding (the sort group is the unit of feature pooling, so you collapse spatially distinct populations into one mark distribution). Use `set_group_by_shank` instead, or build `SortGroup` rows manually so each sort group corresponds to a single shank.
