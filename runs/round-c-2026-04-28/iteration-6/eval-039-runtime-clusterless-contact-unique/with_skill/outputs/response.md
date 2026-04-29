# `ValueError: contact positions are not unique` — the grouper isn't broken; the sort groups are wrong for clusterless

Short answer: SpikeInterface is correct to reject, and there's no bug in the v1 grouper. For clusterless / waveform-based v1 pipelines, **a sort group must contain electrodes from exactly one shank**. Manually inserting whole-probe sort groups (multiple shanks per `sort_group_id`) on a polymer probe puts duplicate `(x, y)` contact positions into the same recording, and `SpikeSortingRecording.populate` aborts with the error you're seeing.

## Why this fails

When `SpikeSortingRecording.populate` builds the SpikeInterface recording for one `sort_group_id`, it pulls the contact `(x, y)` of every electrode in that group from the probe geometry. A polymer probe re-uses the same in-shank geometry on each shank — the within-shank `(x, y)` of shank 0's site 1 equals the within-shank `(x, y)` of shank 1's site 1. SpikeInterface requires unique contact positions per recording (this is what makes per-channel waveforms meaningful for clusterless), so it raises `ValueError: contact positions are not unique`.

This is not "more units in the group" — clusterless decoding doesn't sort units. It uses spike amplitudes/waveform features per electrode, so the constraint is geometric, not unit-count. Cramming more shanks into a group doesn't give you more signal; it just breaks the ingest.

## Fix: regroup by shank

The only sort-group helper exposed on v1 `SortGroup` is `set_group_by_shank`, which gives you exactly the shape clusterless needs: tetrodes get one group; multi-shank polymer probes get one group **per shank**.

```python
from spyglass.spikesorting.v1 import SortGroup

# This DELETES the current SortGroup rows for nwb_file (and cascades
# to anything downstream that already referenced them) and rebuilds
# them one-shank-per-group. Make sure that's what you want before
# running it.
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)
```

Source: `src/spyglass/spikesorting/v1/recording.py:50-95` (definition + the existing-rows delete-and-rebuild branch at lines 81-86).

There is no `set_group_by_electrode_group` on v1 `SortGroup` — that helper only exists on the **v0** class (`src/spyglass/spikesorting/v0/spikesorting_recording.py:94`), and even on v0 it groups by `electrode_group_name`, which on a polymer probe collapses all shanks of the probe into one group — i.e. it would have produced exactly the same multi-shank-group footgun. Don't port that v0 pattern into v1 clusterless work.

## Verify before re-running

After regrouping, confirm each `sort_group_id` covers a single shank:

```python
from spyglass.spikesorting.v1 import SortGroup
from spyglass.common.common_ephys import Electrode

key = {"nwb_file_name": nwb_file}

# 1. Inspect the part table directly.
(SortGroup.SortGroupElectrode & key).fetch(format="frame")

# 2. Count distinct shanks per sort_group_id by joining to Electrode
#    (Electrode carries probe_shank).
import datajoint as dj
rows = dj.U("sort_group_id", "probe_shank") & (
    (SortGroup.SortGroupElectrode & key) * Electrode
)
rows.fetch(format="frame").reset_index().groupby("sort_group_id")["probe_shank"].nunique()
```

Every `sort_group_id` should map to exactly one `probe_shank`. If any group still shows more than one shank, regroup before inserting `SpikeSortingRecordingSelection` rows — otherwise the same `populate` will fail again.

## What to do downstream

Once `SortGroup` is one-shank-per-group, the rest of the v1 flow is unchanged. You'll have one `SpikeSortingRecordingSelection` row per shank instead of one per probe; clusterless decoding consumes those per-shank sortings via `SpikeSortingOutput`, and the `ClusterlessDecodingV1` selection will pick them up the same way it picks up tetrode sortings. If you want the *analysis* to span the whole probe, that aggregation lives at the decoding-group / `UnitWaveformFeaturesGroup` layer, not at `SortGroup`.

## Summary

- Not a SpikeInterface bug and not a grouper bug — manually-inserted multi-shank sort groups are invalid input for clusterless.
- v1 `SortGroup` only exposes `set_group_by_shank` (`src/spyglass/spikesorting/v1/recording.py:51`); use it.
- Verify with `(SortGroup.SortGroupElectrode & key)` joined to `Electrode.probe_shank` — one shank per `sort_group_id`.
- Then re-run `SpikeSortingRecording.populate(...)`; the contact-position check will pass.
