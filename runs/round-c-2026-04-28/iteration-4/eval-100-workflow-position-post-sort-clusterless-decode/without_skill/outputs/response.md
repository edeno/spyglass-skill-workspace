# Workflow position: post-curation to clusterless decoding

Short version: **clusterless decoding does not consume `CurationV1` output**. If you want clusterless decoding, the spike sorting + curation work you just did is essentially on a different track. Clusterless decoding takes its spikes from a `UnitWaveformFeatures` table fed by `SpikeSortingOutput` (the merge table), with waveform features computed per-channel — it does not need accepted/curated unit IDs.

Here's the pipeline shape, and where you actually are.

## The two decoding tracks in Spyglass v1

Spyglass v1 has two parallel decoding pipelines under `spyglass.decoding.v1`:

1. **Sorted-spikes decoding** (`SortedSpikesDecodingV1`) — uses curated single units. This is the one that would consume the curation work you just did.
2. **Clusterless decoding** (`ClusterlessDecodingV1`) — uses *spike waveform features* on each detected spike, without committing to unit identities. Skips curation entirely.

## What feeds clusterless decoding

The clusterless path lives roughly in `spyglass.decoding.v1.clusterless` and `spyglass.spikesorting.analysis.v1.unit_waveform_features` (or the analogous `waveform_features` module). The chain is approximately:

```
SpikeSorting (v1)                    [you have this]
        |
        v
SpikeSortingOutput  (merge table)    [merge of v0 + v1 sorting outputs]
        |
        v
UnitWaveformFeaturesSelection
+ WaveformFeaturesParams             [pick which features — typically peak amplitude per channel, or PCA, etc.]
        |
        v
UnitWaveformFeatures.populate()      [computes per-spike features used as "marks"]
        |
        v
PositionGroup    (a grouping of position interval(s) for the decode)
DecodingParameters  (state-space model + observation model config)
ClusterlessDecodingSelection
        |
        v
ClusterlessDecodingV1.populate()
```

So the missing middle is:

1. **Insert your sorting result into `SpikeSortingOutput`**, the merge table — typically via `SpikeSortingOutput.insert([{...}], part_name="SpikeSortingV1")` (or the equivalent helper). This is what makes downstream tables agnostic to v0 vs v1.
2. **Pick (or insert) `WaveformFeaturesParams`** — defines what marks you want (commonly amplitude on each channel of a tetrode/probe group; sometimes PCA components).
3. **Insert into `UnitWaveformFeaturesSelection`** keying on the merge entry + your params, then `UnitWaveformFeatures.populate()`. This is the actual feature/mark extraction step. For clusterless you usually do this on the *uncurated* sort (or a permissive curation), because you want every detected spike, not just accepted units.
4. **Set up the decoding side**:
   - `PositionOutput` merge entry already exists for the interval you're decoding.
   - `PositionGroup` to bundle position sources for the decode.
   - `DecodingParameters` — the state-space / observation model config (typically built via `non_local_detector`'s `ClusterlessDecoder` / `NonLocalClusterlessDetector` parameter dataclasses, then inserted).
5. **Insert into `ClusterlessDecodingSelection`** linking the waveform-features key, position group, decoding params, and the encoding/decoding interval list, then `ClusterlessDecodingV1.populate()`.

## Practical notes / gotchas

- **You don't need `CurationV1` for the clusterless path**, but the `UnitWaveformFeatures` table is still keyed through the sorting output. In practice people often run waveform features on the *unmerged, minimally curated* sort (or the raw sort) so noise spikes are included as marks. Whether that matters for your science depends on the noise level — it's worth checking that `UnitWaveformFeaturesSelection` is pointing at the curation level you actually want.
- **`SpikeSortingOutput` is a merge table.** Don't query it with a normal join — use `SpikeSortingOutput.merge_get_part(key)` / `merge_restrict` to descend into the v1 part table.
- **Encoding vs decoding intervals**: clusterless decoding takes both. The encoding interval is where the place fields / mark distributions are learned; the decoding interval is what you actually decode. They can be the same (e.g. cross-validated) or different (encode on run, decode on rest).
- **Position must be in `PositionOutput`** (the merge for `TrodesPosV1` / `DLCPosV1`) and time-aligned to the spike data via the same `IntervalList`.

## TL;DR

Between your `CurationV1` and `ClusterlessDecodingV1.populate()`, the steps are:

`SpikeSortingOutput` (merge insert) → `WaveformFeaturesParams` → `UnitWaveformFeaturesSelection` → `UnitWaveformFeatures.populate()` → `PositionGroup` + `DecodingParameters` → `ClusterlessDecodingSelection` → `ClusterlessDecodingV1.populate()`.

Curation is optional/sidestepped on this track — if you wanted curation to matter for decoding, that's the *sorted*-spikes decoder (`SortedSpikesDecodingV1`), not the clusterless one.
