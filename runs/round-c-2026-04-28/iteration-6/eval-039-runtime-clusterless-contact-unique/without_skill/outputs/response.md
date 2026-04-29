# `ValueError: contact positions are not unique` from `SpikeSortingRecording.populate`

Short answer: this is not a SpikeInterface bug and the grouper isn't broken — the error is coming from how you built the sort groups. Specifically, lumping multiple shanks of a polymer probe into a single `sort_group_id` is what trips it.

## What the error actually means

The error is raised by SpikeInterface when it builds a `ChannelSparsity`/probe object for the recording slice that corresponds to one sort group. SpikeInterface requires the `(x, y)` (and sometimes `z`) contact coordinates inside a single recording/probe to be **unique**, because waveform extraction, channel sparsity, and PCA features all rely on a one-to-one mapping between channels and physical locations.

A polymer / multi-shank probe (e.g. Neuropixels, four-shank silicon probes) has its shanks laid out so that **each shank reuses the same set of `y`-coordinates** — every shank has, say, contacts at `y = 0, 20, 40, ...`. The `x` coordinate differs only between shanks, *but the per-shank position grid is intentionally repeated*. So the moment you put electrodes from more than one shank into a single `sort_group_id`, the resulting recording has multiple channels at identical `(x, y)` positions and SpikeInterface refuses it with exactly the message you're seeing.

That's why the failure surfaces at `SpikeSortingRecording.populate` and not earlier — `populate` is the point where the per-group recording is materialized through SpikeInterface's probe machinery.

## Why your manual `SortGroup` insert hit this

You wrote that you manually inserted into `SortGroup` and `SortGroup.SortGroupElectrode` so that "each group spans a whole probe (multiple shanks together)". That's the trigger:

- One `sort_group_id` ⇒ one SpikeInterface recording at sort time.
- That recording inherits the contact positions of every electrode you put in the part table.
- Multi-shank ⇒ duplicated `(x, y)` ⇒ uniqueness check fails.

For density-based clustering this would also be conceptually wrong (waveforms aren't comparable across shanks because the contacts aren't physically near each other), but the *mechanical* reason `populate` blows up is just the position-uniqueness check.

## The fix: one sort group per shank, via the v1 helper

For the v1 pipeline, the supported way to build sort groups is:

```python
from spyglass.spikesorting.v1 import SortGroup

SortGroup().set_group_by_shank(nwb_file_name=nwb_file_name)
```

This is the only sort-group helper exposed on v1 `SortGroup` (see `src/spyglass/spikesorting/v1/recording.py:51`). Its docstring is explicit:

> Electrodes from probes with multiple shanks (e.g. polymer probes) are placed in **one group per shank**.

That's exactly the invariant SpikeInterface needs and exactly the invariant your manual insert violated.

A note on intent: you said you wanted "more units grouped together for the clusterless analysis." That's a reasonable instinct, but *clusterless* decoding doesn't need bigger sort groups — it works on per-channel waveform features (amplitudes / marks) directly, and those are still computed across all shanks/channels at decode time. The sort-group boundaries only control how SpikeSorting / WaveformExtraction slice the recording; making them too large breaks the geometry assumption without giving you any extra signal in the decoder.

(For context, the older v0 pipeline at `spyglass/spikesorting/v0/spikesorting_recording.py:94` did expose a `set_group_by_electrode_group` helper that grouped a whole `electrode_group_name` together. There's no v1 equivalent — and even on v0 it would have produced this same multi-shank-group footgun on a polymer probe. Don't try to port it over.)

## Verifying you're back to one shank per group

Before re-running `SpikeSortingRecording.populate`, inspect the part table to confirm each `sort_group_id` covers exactly one shank:

```python
from spyglass.spikesorting.v1 import SortGroup
import pandas as pd

key = {"nwb_file_name": nwb_file_name}

df = (SortGroup.SortGroupElectrode & key).fetch(format="frame").reset_index()

# How many distinct shanks (probe_shank) per sort_group_id?
shanks_per_group = (
    df.groupby("sort_group_id")["probe_shank"].nunique().sort_values(ascending=False)
)
print(shanks_per_group.head(20))
```

You want every value in `shanks_per_group` to be `1`. Anything `> 1` means that sort group still spans multiple shanks and `populate` will fail again on it.

If you previously inserted bad rows, clear them first and let the helper rebuild:

```python
(SortGroup & {"nwb_file_name": nwb_file_name}).delete()
SortGroup().set_group_by_shank(nwb_file_name=nwb_file_name)
```

(`set_group_by_shank` itself will delete pre-existing groups for the file before inserting fresh ones — see the body of the method in `recording.py` — but if you also have downstream `SpikeSortingRecordingSelection` rows pointing at the old `sort_group_id`s you'll need to clean those up too, since they `-> SortGroup`.)

## Recap

- Not a SpikeInterface bug, not a grouper bug — it's the manual multi-shank `SortGroup` rows.
- Multi-shank polymer probes have repeated `(x, y)` across shanks; SpikeInterface enforces unique contact positions per recording.
- For v1 clusterless (and v1 sorted-spikes), build sort groups with `SortGroup().set_group_by_shank(nwb_file_name=...)` — one shank per `sort_group_id`.
- Confirm with `(SortGroup.SortGroupElectrode & key).fetch(...)` and a `groupby("sort_group_id")["probe_shank"].nunique()` check before re-running `SpikeSortingRecording.populate`.
