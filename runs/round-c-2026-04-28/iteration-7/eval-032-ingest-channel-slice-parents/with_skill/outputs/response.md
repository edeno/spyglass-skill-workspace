# `ChannelSliceRecording: channel ids are not all in parents` during `SpikeSortingRecording.populate`

## Short answer

This is almost certainly a mismatch between the **channel identifiers SpikeInterface reads from your NWB** and the **`electrode_id` values Spyglass stored at ingestion**. The trigger is a `channel_name` column on `nwb.electrodes`: from SpikeInterface 0.99 onward, the NWB recording extractor uses `channel_name` (when present) as the SpikeInterface `channel_ids`, instead of the integer `electrode_id`. Spyglass's `SortGroup.SortGroupElectrode` rows still hold integer `electrode_id`s, so when `SpikeSortingRecording.populate(...)` calls `BaseRecording.channel_slice(channel_ids=[...])` with those integers, none of them are in the parent recording's id set, and SpikeInterface trips its assertion.

The fact that `insert_sessions` ran cleanly is consistent with this: the conflict is between the *NWB* electrodes-table schema and *SpikeInterface*'s reader, not between the NWB and Spyglass's ingest. Ingestion wrote `electrode_id` rows correctly; the breakage is downstream, where SpikeInterface re-reads the file with a different channel-id convention.

(Source for the symptom-to-cause mapping: `skills/spyglass/references/ingestion.md` "Probe / electrode conflicts from the NWB" → `AssertionError: ChannelSliceRecording: channel ids are not all in parents` row.)

## Confirm it in 60 seconds

```python
import pynwb
with pynwb.NWBHDF5IO(path_to_nwb, "r") as io:
    nwb = io.read()
    print("colnames:", nwb.electrodes.colnames)
    if "channel_name" in nwb.electrodes.colnames:
        df = nwb.electrodes.to_dataframe()
        print(df[["channel_name"]].head())
```

If `channel_name` is in `colnames`, you've reproduced the cause. (If it's *not* there, the assertion has a different origin — see "If `channel_name` isn't the cause" below.)

You can also cross-check what SpikeInterface itself sees:

```python
from spikeinterface.extractors import NwbRecordingExtractor
rec = NwbRecordingExtractor(file_path=path_to_nwb)
print("SI channel_ids:", rec.channel_ids[:10], "dtype:", rec.channel_ids.dtype)
```

If those come back as strings (e.g. `'CH0'`, `'CH1'`, ...) rather than integers `[0, 1, ...]`, that's the smoking gun — Spyglass is asking for `[0, 1, 2, ...]` from a recording whose ids are strings.

And on the Spyglass side, the integers Spyglass is trying to slice with:

```python
from spyglass.spikesorting.v1 import SortGroup
(SortGroup.SortGroupElectrode & {"nwb_file_name": nwb_copy_file_name}).fetch("electrode_id")
```

These are what get fed to `recording.channel_slice(...)` inside `SpikeSortingRecording.populate`.

## Fix options (preferred → least preferred)

1. **Upgrade Spyglass.** Newer Spyglass releases handle `channel_name` explicitly in `common_ephys`. Verify on your install:

   ```bash
   python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"
   grep -n "channel_name" $(python -c 'import spyglass, os; print(os.path.dirname(spyglass.__file__))')/common/common_ephys.py
   ```

   If `channel_name` does not appear, your Spyglass predates the fix — `git pull && pip install -e .` (or upgrade your pinned version) is the cleanest path. After upgrading, re-run the recording populate; you do not need to re-ingest unless the new code stores additional fields.

2. **Rewrite the NWB to drop `channel_name` (or make it match `electrode_id`).** If you can't upgrade, regenerate the NWB without the `channel_name` column, then re-ingest with `reinsert=True`:

   ```python
   import spyglass.data_import as sgi
   sgi.insert_sessions("j1620210710.nwb", reinsert=True)
   ```

   Note `reinsert=True` is destructive: it cascades through `Nwbfile`'s descendants for that session (see `ingestion.md` "What `reinsert=True` actually does"). Inspect downstream rows first:

   ```bash
   python skills/spyglass/scripts/db_graph.py path --down Session
   ```

   And back up `analysis/*.nwb` if you want to keep any prior outputs.

3. **Pin SpikeInterface back to <0.99.** Possible but not recommended — the rest of the v1 pipeline expects current SpikeInterface, and you'll fight other API drift. Treat as a last resort.

## What *not* to do

- **Don't** hand-edit `SortGroup.SortGroupElectrode` rows to use string ids. The schema declares `electrode_id` as an integer (composite FK to `Electrode`), and the rest of Spyglass joins on it.
- **Don't** patch the recording-side `channel_ids` inside the `make()` body of an installed Spyglass — edits to `src/spyglass/...` desync your DB from other labs and `pip install -e .` silently reverts them (see SKILL.md Core Directive on not editing the installed package).
- **Don't** assume `insert_sessions` running cleanly means the NWB is "good enough" for downstream. Ingestion validates Spyglass's own invariants; SpikeInterface compatibility is a separate axis.

## If `channel_name` isn't the cause

If `nwb.electrodes.colnames` doesn't contain `channel_name`, the assertion text is generic and other causes are possible:

- `(SortGroup.SortGroupElectrode & key).fetch("electrode_id")` returns ids that no longer exist in the NWB electrodes table (e.g. you re-ingested a slimmer NWB without re-running `SortGroup().set_group_by_shank(...)`). Re-run the SortGroup setup.
- A custom preprocessing step earlier in your pipeline already sliced the recording, and `populate` is now slicing again with the original ids.

Drop the channel-id sets from both sides into the same scope and `set(spy_ids) - set(rec.channel_ids)` to see which ids are missing — that's the concrete diagnostic.

## TL;DR

Check `nwb.electrodes.colnames` for `channel_name`. If present, your NWB + SpikeInterface combination is using string channel ids while Spyglass is asking for integers. Upgrade Spyglass (preferred) or rewrite the NWB without `channel_name` and re-ingest with `reinsert=True`. Don't edit installed Spyglass source or hand-patch `SortGroup` rows.
