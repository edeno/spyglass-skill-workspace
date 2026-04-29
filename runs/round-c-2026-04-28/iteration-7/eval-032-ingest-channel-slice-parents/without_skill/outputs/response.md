# `ChannelSliceRecording: channel_ids contains channels not in the parent recording`

That assertion is raised by **SpikeInterface**, not Spyglass — it comes from `ChannelSliceRecording.__init__` in `spikeinterface.core.channelslice`, which sanity-checks that every ID you ask for is actually present in the parent recording's `channel_ids` array. Spyglass's `SpikeSortingRecording.make()` does that slice when it builds the per–sort-group recording: it takes the `NwbRecordingExtractor` for the session and slices it down to the electrodes in the `SortGroup.SortGroupElectrode` rows for `key`. If even one of those electrode IDs isn't in the NWB recording's `channel_ids`, you get exactly this AssertionError.

So the question is: **why don't the IDs Spyglass is asking for line up with the IDs in the NWB extractor?** With a fresh ingest of `j1620210710.nwb` that ran cleanly, there are a small number of plausible root causes. Walk them in this order — they're cheap to check and they cover ~95% of cases.

## 1. SortGroup got built off a different `Electrode` set than the NWB recording exposes

`SpikeSortingRecording` materializes the recording extractor from the **raw NWB** (`Nwbfile` → `NwbRecordingExtractor`, which reads the broadband `ElectricalSeries`). The `channel_ids` it exposes are the **electrode IDs on that series only**. But `SortGroup.SortGroupElectrode` is populated from the full `Electrode` table, which contains every electrode in the NWB file — including ones that may not be in the broadband series.

If your NWB has electrodes in `nwbfile.electrodes` that are *not* referenced by the broadband `ElectricalSeries.electrodes` DynamicTableRegion (for example: reference/ground rows, headstage-only channels, or LFP-only channels on a separate series), `SortGroup` will happily include them and then the slice will explode.

Check:

```python
import pynwb
from spyglass.common import Electrode, SortGroup
from spikeinterface.extractors import NwbRecordingExtractor

nwb_file_name = 'j1620210710_.nwb'  # Spyglass-mangled name
key = {'nwb_file_name': nwb_file_name, 'sort_group_id': <the one that crashed>}

# What Spyglass thinks the sort group contains:
sg_electrodes = (SortGroup.SortGroupElectrode & key).fetch('electrode_id')
print('SortGroup wants:', sorted(sg_electrodes))

# What the NwbRecordingExtractor actually exposes:
abs_path = (Nwbfile & {'nwb_file_name': nwb_file_name}).fetch1('nwb_file_abs_path')
rec = NwbRecordingExtractor(abs_path, electrical_series_path='acquisition/e-series')  # adjust path
print('NWB recording has:', sorted(rec.channel_ids.tolist()))

print('Missing:', sorted(set(sg_electrodes) - set(rec.channel_ids.tolist())))
```

The `Missing` set is exactly what trips the assert. If it's non-empty, the fix is to either (a) drop those electrodes from `SortGroup.SortGroupElectrode` for this session, or (b) re-run sort-group setup with a filter (e.g. `bad_channel == False` and only electrodes in the broadband group).

## 2. Wrong `ElectricalSeries` — Spyglass is reading from LFP, not broadband (or vice versa)

If the NWB file has more than one `ElectricalSeries` (e.g. raw + LFP), the `NwbRecordingExtractor` Spyglass builds will pick one. With `ndx-franklab-novela`–style files, the raw broadband series is usually `acquisition/e-series` and is what `SpikeSortingRecording` should use. If your file's broadband series is named or pathed unusually, Spyglass may have grabbed the LFP series, which only has a subset of channels — and then the spike-sorting sort group's electrode list won't fit.

Check by listing the series in the NWB file:

```python
with pynwb.NWBHDF5IO(abs_path, 'r', load_namespaces=True) as io:
    nwb = io.read()
    for name, obj in nwb.acquisition.items():
        if hasattr(obj, 'electrodes'):
            print(name, obj.data.shape, '→ electrodes:',
                  obj.electrodes.data[:].tolist())
```

If there's only one and #1 above came up empty, skip this and go to #3.

## 3. Type mismatch on channel IDs (int vs str vs np.int64)

SpikeInterface compares channel IDs with strict equality, and `ChannelSliceRecording` does the membership check on the `channel_ids` numpy array. If `SortGroup.SortGroupElectrode.electrode_id` is being fetched as plain Python `int` but the NWB `ElectricalSeries.electrodes` ids are stored as `np.int64` *strings* (this happens on some older NWB writers), the membership test fails even though the values look identical when printed.

Force-check the dtypes:

```python
print(rec.channel_ids.dtype, type(rec.channel_ids[0]))
print(sg_electrodes.dtype, type(sg_electrodes[0]))
```

If one side is `<U…` (unicode) and the other is integer, that's your bug. The fix is upstream of Spyglass — the NWB writer should be storing electrode IDs as integers — but you can patch around it by converting the SortGroup IDs to match the NWB extractor's dtype before populate.

## 4. `bad_channel` electrodes weren't filtered

`SortGroup.set_group_by_shank()` (and friends) usually filter out `bad_channel == True` rows, but if you populated `SortGroup` manually or used a custom helper, it's easy to include an electrode that's marked bad and absent from the broadband stream. That presents identically to #1.

## 5. Probe / electrode-group mismatch in the NWB itself

If `j1620210710.nwb` was rebuilt or re-converted recently, double-check that the NWB's `electrode_groups` and the channel map on the broadband `ElectricalSeries` agree. NWB allows `electrodes` rows that aren't referenced by any `ElectricalSeries.electrodes` region — those rows still show up in `Electrode` after Spyglass ingest and will silently leak into `SortGroup` if you don't filter on group membership.

## What to do right now

1. Run the diff in section 1 — print `set(SortGroup wants) - set(NWB recording has)`. That single print tells you which of the five branches above you're in.
2. If the missing set is non-empty: figure out *why* those electrodes are in `SortGroup` for this session. Usually it's a reference channel, a bad channel, or a channel on a different ElectricalSeries.
3. Fix the membership in `SortGroup.SortGroupElectrode` (delete the offending rows under a transaction) and re-run `SpikeSortingRecording.populate(key)`. You do **not** need to re-ingest the NWB; `SortGroup` is downstream of `Electrode` and is safe to repopulate.
4. If the missing set is empty but you still crash, you're in case #3 (dtype) — print the dtypes and convert.

## A note on "ingest ran cleanly"

A clean ingest only guarantees that `Nwbfile`, `Electrode`, `ElectrodeGroup`, etc. were inserted without raising. It does **not** guarantee that every `Electrode` row corresponds to a channel in the broadband `ElectricalSeries` — the ingest doesn't cross-check that. So a clean ingest is fully consistent with this crash; the mismatch surfaces the first time something tries to actually open the recording extractor and slice it, which is `SpikeSortingRecording.make()`. Don't take "ingest worked" as evidence the electrode table is sound for spike sorting.
