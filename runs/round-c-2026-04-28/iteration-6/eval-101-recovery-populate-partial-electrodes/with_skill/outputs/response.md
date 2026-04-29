## Don't re-run the ingest blindly — inspect what `populate_all_common` already told you

Your symptoms match the classic `populate_all_common` silent-skip pattern: `Session` / `IntervalList` / `Raw` / `Electrode` are populated, but `Electrode.probe_id` is null and `Probe` has no row for the relevant `probe_type`. That isn't usually a `Probe`-table-level fault — it's almost always an **upstream ancestor row** that failed silently, and `Probe` then couldn't insert because of a missing foreign key. The two upstream candidates are `ProbeType` (hard FK on `Probe`) and `DataAcquisitionDevice` (nullable FK on `Probe`).

The data on disk is fine — your tetrode metadata is in the NWB. The problem is that ingestion swallowed an exception and kept going.

### Step 1 — read `common_usage.InsertError` first (do not re-run yet)

`populate_all_common` is the common-ingest driver. By default (`raise_err=False`) it catches per-table exceptions and writes a short message per silently-skipped table to `common_usage.InsertError` instead of raising (`src/spyglass/common/populate_all_common.py:95, 120, 152`; the table is defined at `src/spyglass/common/common_usage.py:43`). The full traceback is gone, but the row tells you which table actually failed and the truncated error message — that's the diagnostic trail you need to preserve.

```python
from spyglass.common.common_usage import InsertError

# Restrict to this session — InsertError is global and accumulates.
rows = (InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(as_dict=True)
for r in rows:
    print(r["table"], "|", r["error_type"], "|", r["error_message"])
```

The `InsertError` row will name the actual failing table. You will almost always see one of:

- `ProbeType` failed (e.g. `DataJointError` on a missing `probe_description` or a row-format mismatch). `Probe` then can't insert because its hard FK to `ProbeType` (`src/spyglass/common/common_device.py:385`) won't resolve, and `Electrode.probe_id` ends up null.
- Less commonly, `DataAcquisitionDevice` failed (e.g. `PopulateException: Data acquisition device properties ... do not match`). `Probe` has a nullable FK to it (`common_device.py:386`), so this is a secondary cause to consider only if `ProbeType` looks clean.

`Probe` itself rarely fails on its own — when it appears "missing", the cause is one tier upstream.

If the `InsertError` query returns no rows for this session, two possibilities: (a) someone already ran `(InsertError & ...).delete()` on it, or (b) `populate_all_common` was called with `raise_err=True` or `rollback_on_fail=True` and you're missing the original log. Either way, jump to Step 2.

### Step 2 — re-run the affected tables with `raise_err=True` to surface the traceback

Once you know the failing table, force the real exception (`populate_all_common.py:159-161` exposes the kwarg). Use a fresh kernel so any cached connection state is reset.

```python
from spyglass.common import populate_all_common

# Pass the COPY filename (the one in Nwbfile, with the trailing
# underscore that insert_sessions appends). Don't re-run insert_sessions.
populate_all_common("j1620210710_.nwb", raise_err=True)
```

That will now raise on the first failure with the full traceback, and you can read the actual reason `ProbeType` (or whichever table it is) didn't insert.

### Step 3 — fix the root cause, then re-populate just the affected tables

What "fix" means depends on what the traceback says:

- **Missing `ProbeType` row**: pre-insert it manually. The canonical pattern (from `02_Insert_Data.ipynb`) requires `probe_description`:

  ```python
  from spyglass.common import ProbeType
  ProbeType.insert1(
      {
          "probe_type": "<the type name in your NWB>",
          "probe_description": "<human-readable description>",
          "manufacturer": "<...>",
          "num_shanks": <int>,
      },
      skip_duplicates=True,
  )
  ```

  Then re-run `populate_all_common("j1620210710_.nwb", raise_err=True)` and `Probe` / `Electrode.probe_id` should populate this time. (`skip_duplicates=True` is appropriate on this lookup-table insert — it is **not** appropriate on `insert_sessions`.)

- **`DataAcquisitionDevice` mismatch**: compare your NWB's device metadata against the existing DB row before changing anything:

  ```python
  from spyglass.common import DataAcquisitionDevice
  DataAcquisitionDevice & {"data_acquisition_device_name": "<name from NWB>"}
  ```

  Fix the NWB or rename the device per session. **Do not** delete the existing `DataAcquisitionDevice` row to "force" the match — other sessions FK to it.

- **Probe / electrode geometry or identity issue inside the NWB itself** (NaN `rel_x`/`rel_y`/`rel_z`, duplicate `electrode_id`s across probes, etc.): the NWB has to be fixed before re-ingest. See `Probe / electrode conflicts from the NWB` in `ingestion.md` for the inspection snippet.

### What NOT to do

- **Do not call `insert_sessions(..., reinsert=True)` before reading `InsertError`.** `reinsert=True` is destructive — it deletes the entire `Nwbfile` cascade for this session (`Session`, `IntervalList`, `Raw`, `Electrode`, plus any downstream populate-tier rows) and re-runs `populate_all_common` from scratch. If the underlying cause is the same `ProbeType` (or whatever) being absent, you'll re-trigger the same silent skip, lose the `InsertError` diagnostic trail, and still have a partial state — just a freshly partial state.
- **Do not bypass `cautious_delete` to wipe the `Session` / `IntervalList` / `Raw` / `Electrode` rows that ingested correctly.** `super_delete` / `force_permission=True` exist for genuine recovery situations (orphaned rows, stuck deletes), not for clearing rows that are fine. Those rows ingested correctly and downstream pipelines depend on them; deleting them cascades and just costs you re-ingest time.
- **Do not edit `Electrode` rows in-place** with `allow_direct_insert=True` to set `probe_id` after the fact. That bypasses the FK that defines the very identity you're trying to repair, and any downstream `make()` that already ran with `probe_id=NULL` won't be re-run automatically — the inconsistency persists.

### Summary of the safe sequence

1. `(InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(as_dict=True)` — name the failing table.
2. `populate_all_common("j1620210710_.nwb", raise_err=True)` in a fresh kernel — get the traceback.
3. Fix the upstream row (almost always `ProbeType`, sometimes `DataAcquisitionDevice`).
4. Re-run `populate_all_common(..., raise_err=True)` — `Probe` and `Electrode.probe_id` should fill in.
5. Only if step 3 isn't tractable in place (e.g. the NWB itself is malformed), then consider `insert_sessions(..., reinsert=True, rollback_on_fail=True)` after fixing the NWB — and only after you've read the `InsertError` row.
