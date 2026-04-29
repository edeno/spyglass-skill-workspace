# Getting your NWB file into Spyglass

Nice — `trodes_to_nwb` produces a Spyglass-friendly NWB (it's the canonical converter for Frank-lab Trodes/SpikeGadgets recordings, written specifically so the resulting file passes `spyglass.common`'s ingestion). The remaining work is mostly bookkeeping: put the file where Spyglass expects it, then call the one-shot insert helper.

Below is the end-to-end recipe, including the gotchas that bite people the first time.

---

## 1. Confirm Spyglass is set up

Before ingesting, you need:

- A working Spyglass install in a conda/uv env (`pip install spyglass-neuro` or a dev install).
- A reachable MySQL/MariaDB DataJoint server (local docker or a lab server). `dj.config['database.host']` etc. should already be set in `~/.datajoint_config.json` or `dj_local_conf.json`.
- The Spyglass directory tree configured. Spyglass reads `SPYGLASS_BASE_DIR` from the environment (or you can set it in code). The base dir contains subfolders Spyglass manages: `raw/`, `analysis/`, `recording/`, `sorting/`, `waveforms/`, `tmp/`, `video/`, etc.

Quick sanity check in Python:

```python
import os
import spyglass
from spyglass.settings import config

print(config["SPYGLASS_BASE_DIR"])   # e.g. /data/spyglass
print(config["SPYGLASS_RAW_DIR"])    # should be <BASE>/raw
```

If these are empty, set them before importing further Spyglass modules:

```python
import os
os.environ["SPYGLASS_BASE_DIR"] = "/data/spyglass"
# (optional) os.environ["SPYGLASS_RAW_DIR"] = "/data/spyglass/raw"
from spyglass.settings import SpyglassConfig
SpyglassConfig().load_config(force_reload=True)
```

`dj_local_conf.json` in your working directory can also carry `custom: {"spyglass_dirs": {"base": "/data/spyglass"}}` so you don't have to set env vars every time.

## 2. Move (or symlink) the NWB file into the raw dir

Spyglass only ingests files that live under `SPYGLASS_RAW_DIR` (default `<BASE>/raw/`). Don't ingest from `/data/testuser/...` directly — copy or symlink it in:

```bash
# pick one
cp  /data/testuser/j1620210710.nwb  /data/spyglass/raw/j1620210710.nwb
ln -s /data/testuser/j1620210710.nwb /data/spyglass/raw/j1620210710.nwb
```

Symlinks are fine and save disk for big recordings. Keep the original filename; Spyglass uses the basename as the primary key (`nwb_file_name`) downstream.

## 3. (Recommended) Validate the NWB first

Cheap insurance against mid-ingest failures:

```bash
python -m pynwb.validate /data/spyglass/raw/j1620210710.nwb
# stronger:
pip install nwbinspector
nwbinspector /data/spyglass/raw/j1620210710.nwb
```

`trodes_to_nwb` output should pass cleanly. If `nwbinspector` flags missing `experimenter`, `institution`, `subject.species`, fix the metadata YAML and re-export — Spyglass's `Session`, `Subject`, `Lab`, `Institution` tables read those fields and will silently insert blanks otherwise.

## 4. Insert with `insert_sessions`

This is the one call that does the heavy lifting. It populates `Nwbfile`, `Session`, `Subject`, `Institution`, `Lab`, `LabMember`, `Electrode`, `ElectrodeGroup`, `Probe`, `Raw`, `SampleCount`, `DIOEvents`, `TaskEpoch`, `StateScriptFile`, `VideoFile`, `IntervalList`, `SensorData`, etc. — basically everything in `spyglass.common` that can be derived from the NWB.

```python
from spyglass.common import Nwbfile
from spyglass.data_import import insert_sessions

# argument is the *basename* (relative to SPYGLASS_RAW_DIR), not an absolute path
insert_sessions("j1620210710.nwb")
```

What this actually does under the hood:

1. Copies the file to `<RAW_DIR>/j1620210710_.nwb` (note the trailing underscore — that's the "Spyglass copy" with stripped object IDs that downstream tables key off). The original stays put.
2. Inserts a row into `Nwbfile` with `nwb_file_name = "j1620210710_.nwb"`.
3. Calls each `populate_all_common`-style inserter in order, each pulling the relevant NWB groups.

You'll see a lot of log output. Warnings about missing optional fields (e.g. no DIO, no video) are usually fine; errors that abort the call are not — fix the underlying NWB and retry.

## 5. Verify the insert

```python
from spyglass.common import Nwbfile, Session, Electrode, Raw, IntervalList

key = {"nwb_file_name": "j1620210710_.nwb"}   # note the underscore

print(Nwbfile & key)
print(Session & key)
print((Electrode & key).fetch("electrode_id", "region_id"))
print(Raw & key)                               # raw ephys reference
print(IntervalList & key)                      # epochs / intervals
```

If `Session & key` returns a row and `Electrode & key` returns the expected channel count, ingestion succeeded. From there you can run the pipelines you care about — LFP (`LFPV1`), position (`TrodesPosV1` / `DLCPosV1`), spike sorting (`SpikeSortingRecording` → `SpikeSorting` → `CurationV1`), ripple detection (`RippleTimesV1`), decoding, etc.

## Common first-time gotchas

- **"File not found" on insert**: you passed a path instead of a basename, or the file isn't actually in `SPYGLASS_RAW_DIR`. Check `Nwbfile.get_abs_path("j1620210710_.nwb")` to see where Spyglass expects it.
- **`nwb_file_name` mismatch**: downstream tables key off the underscored copy (`j1620210710_.nwb`), not the original. Use that name in restrictions.
- **Duplicate insert error** (`Duplicate entry ... for key 'PRIMARY'`): the file's already partially ingested. To redo from scratch, drop with `(Nwbfile & key).delete()` (this cascades — say yes to the prompts only if you're sure).
- **Permissions**: `insert_sessions` writes the underscored copy into `RAW_DIR`. The user running Python needs write access there.
- **`dj.config['stores']`**: if your Spyglass install uses external stores (it usually does for `analysis/` and `raw/`), make sure the `stores` dict points at the same `SPYGLASS_BASE_DIR` you configured. Mismatch here causes `FileNotFoundError` deep in `fetch_nwb()` later.
- **DataJoint user perms**: you need `INSERT` on the `common_*` schemas. If you're on a shared lab server and ingestion fails with a privilege error, ask the admin.

## TL;DR

```python
# one-time setup: SPYGLASS_BASE_DIR set, NWB symlinked into <BASE>/raw/
from spyglass.data_import import insert_sessions
insert_sessions("j1620210710.nwb")

from spyglass.common import Session
print(Session & {"nwb_file_name": "j1620210710_.nwb"})
```

If the print returns a row, you're in. From there pick a pipeline (LFP, position, sorting, …) and start populating.
