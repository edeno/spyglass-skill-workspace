# Ingesting `j1620210710.nwb` into Spyglass

The entry point is `spyglass.data_import.insert_sessions`, but there's setup it expects you to have done first. Walking through the full flow:

## 1. Confirm prerequisites

- **Spyglass installed and `SPYGLASS_BASE_DIR` set.** All ingestion paths derive from this. If you haven't done this yet, see `00_Setup.ipynb` and `scripts/install.py` (the canonical fast path); ask if you need help on that step.
- **The NWB file must live in `$SPYGLASS_RAW_DIR`** (usually `$SPYGLASS_BASE_DIR/raw/`). `insert_sessions` looks there by basename — passing a path like `/data/testuser/j1620210710.nwb` is silently downgraded to just the basename, so the function will look for `j1620210710.nwb` in the raw dir and fail with "file not found" if it's not there.

So the first concrete action is:

```bash
mv /data/testuser/j1620210710.nwb "$SPYGLASS_RAW_DIR"/
# or symlink if you'd rather keep the original where it is:
ln -s /data/testuser/j1620210710.nwb "$SPYGLASS_RAW_DIR"/j1620210710.nwb
```

If you're not sure `SPYGLASS_BASE_DIR` / `SPYGLASS_RAW_DIR` are set correctly, run:

```bash
python skills/spyglass/scripts/verify_spyglass_env.py \
  --check base_dir_resolved --check subdirs_exist_writable
```

## 2. (Optional) Pre-insert any custom hardware lookups

If `j1620210710.nwb` references a probe type / device / lab that isn't already in the DB, the corresponding ingestion sub-step will raise. Lookup-table inserts (which are idempotent and shared across sessions) are the one place where `skip_duplicates=True` is appropriate, e.g.:

```python
from spyglass.common import ProbeType

ProbeType.insert1(
    {
        "probe_type": "tetrode_12.5",        # whatever your file uses
        "probe_description": "...",
        "manufacturer": "...",
        "num_shanks": 1,
    },
    skip_duplicates=True,
)
```

Most lab-standard rat tetrode rigs are already registered, so you can usually skip this and just react if ingestion complains about a missing device/probe.

## 3. Run `insert_sessions`

```python
import spyglass.data_import as sgi

sgi.insert_sessions("j1620210710.nwb")
```

Just the basename — it resolves against `$SPYGLASS_RAW_DIR`. This walks the NWB and populates the common tables: `Session`, `Subject`, `Electrode`, `ElectrodeGroup`, `Raw`, `DIOEvents`, `RawPosition`, `TaskEpoch`, and registers the file under `Nwbfile`.

By default (`raise_err=False`, `rollback_on_fail=False`), per-table errors are logged to `InsertError` and ingestion keeps going — you get a partial DB state on failure. Two stricter modes if you want them:

- `sgi.insert_sessions("j1620210710.nwb", raise_err=True)` — raise on first error (good for stepping through with a debugger). Note: doesn't roll back, so partial state is still possible.
- `sgi.insert_sessions("j1620210710.nwb", rollback_on_fail=True)` — on any logged error, super-delete the `Nwbfile` row so you can retry cleanly. Mutually exclusive with `raise_err=True`.

Don't pass `skip_duplicates=True` to `insert_sessions` — it raises `TypeError`. If the file is already in `Nwbfile` and you want to reingest, use `reinsert=True` (destructive — see step 5).

## 4. Verify it landed — use the COPY filename

This is the single most common ingestion footgun: Spyglass copies the NWB on ingestion and registers the **copy** under `Nwbfile` with `_` appended before `.nwb`. You pass the raw filename to `insert_sessions`; every downstream query uses the copy filename.

```python
from spyglass.common import Session, Nwbfile
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

nwb_copy = get_nwb_copy_filename("j1620210710.nwb")  # "j1620210710_.nwb"

# Did the file register?
Nwbfile & {"nwb_file_name": nwb_copy}

# What got into Session?
Session & {"nwb_file_name": nwb_copy}

# Sanity-check the experimenter is wired up — needed for downstream deletes
Session.Experimenter & {"nwb_file_name": nwb_copy}
```

Spot-check a few related tables too — `IntervalList & {"nwb_file_name": nwb_copy}`, `Electrode & {"nwb_file_name": nwb_copy}`, `TaskEpoch & {"nwb_file_name": nwb_copy}` — to confirm the expected rows are there. If `TaskEpoch` rows are missing for some epochs, that's usually `nwbfile.epochs.tags` or `task_table.task_epochs` having non-numeric values; the matcher silently drops those.

If you want a topology view of everything that just got populated downstream of `Session` for this file, use:

```bash
python skills/spyglass/scripts/db_graph.py path --down Session
```

`Session.descendants()` returns names / `FreeTable` objects, not a restrictable relation, so you can't just write `Session.descendants() & {...}`.

## 5. If something goes wrong

A few common failure modes specific to a fresh ingest:

- **"... is already in Nwbfile table"** — the file registered before. `insert_sessions("...", reinsert=False)` (the default) is a **no-op with a warning** in this case, not a re-run. To actually redo ingestion, pass `reinsert=True`. That's destructive: it cascades the delete through every downstream row that FKs `Nwbfile` (Session for that file, IntervalList rows, all populate-tier outputs). Back up `analysis/` files first if you care about them.
- **`PermissionError` on a delete or reinsert** — Spyglass's `cautious_delete` is team-gated. If the message mentions "experimenter", `Session.Experimenter` is empty for that session — fix that first. Otherwise the deleter and the session's experimenter need to share a `LabTeam`. Don't reach for `super_delete()` / `force_permission=True`; coordinate with the owner.
- **Device/probe lookup mismatch** (`PopulateException: Data acquisition device properties ... do not match`) — a `DataAcquisitionDevice` with the same name already exists with different secondary values. Compare with `DataAcquisitionDevice & {'data_acquisition_device_name': name}`; either reconcile the NWB metadata to the DB row, or rename the device for this session. Don't `.delete()` the DB row — other sessions depend on it.
- **`ValueError: Name has unsupported format ...`** during `LabMember` insert — `decompose_name` only accepts `'First Last'` or `'Last, First'`. A three-token experimenter name like `'Kyu Hyun Lee'` fails; rewrite to `'Lee, Kyu Hyun'` in the NWB or pre-insert the `LabMember` row by hand.
- **Stale electrode metadata / `original_reference_electrode = -1`** — happens when the trodes-to-nwb output uses a generic `pynwb.ecephys.ElectrodeGroup` rather than `ndx_franklab_novela.Probe`. The right fix is to rewrite the NWB to use the franklab Probe extension and re-ingest with `reinsert=True`; don't patch already-ingested rows in place.

## TL;DR

```python
# Move the file into the raw dir first:
#   mv /data/testuser/j1620210710.nwb $SPYGLASS_RAW_DIR/

import spyglass.data_import as sgi
from spyglass.common import Session, Nwbfile
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

sgi.insert_sessions("j1620210710.nwb")

nwb_copy = get_nwb_copy_filename("j1620210710.nwb")  # "j1620210710_.nwb"
print(Nwbfile & {"nwb_file_name": nwb_copy})
print(Session & {"nwb_file_name": nwb_copy})
print(Session.Experimenter & {"nwb_file_name": nwb_copy})
```

That's the full first-contact flow. Once `Session` is populated for the copy filename, you're ready to start whichever pipeline you need next (spike sorting, position, LFP, …) — each starts from a `nwb_copy_file_name`-keyed selection insert.
